"""Typer command-line interface for ``shotlist``.

Four commands cover the whole workflow: ``init`` writes a starter shot list,
``validate`` checks a shot list loads cleanly, ``run`` performs the capture, and
``check`` re-captures and fails if anything drifted from the committed baseline.
Errors from config loading and app readiness are turned into a single-line
message plus a non-zero exit, so the tool fails loudly but never with a
traceback.
"""

import hashlib
import importlib.metadata
import json
import platform
import sys
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

import typer

from shotlist import config as config_module
from shotlist import engine
from shotlist.check import CheckResult, compare_environments, compare_manifests
from shotlist.diff import CHECK_REPORT_NAME, ReportRow, diff_images, render_check_report
from shotlist.engine import _is_deterministic
from shotlist.lifecycle import ReadinessError
from shotlist.output import CaptureResult, Writer, slugify
from shotlist.report import MANIFEST_NAME, Manifest, build_manifest

app = typer.Typer(
    add_completion=False,
    help="Reproducible screenshot capture for docs.",
)

_STARTER_YAML = """\
# .shotlist.yaml — declarative shot list for `shotlist`.
# Describe how to start your app and what to capture, then run `shotlist run`.

output:
  dir: docs/screenshots   # where PNGs land
  # version: v1           # optional subfolder, e.g. docs/screenshots/v1/
  # readme: README.md     # optional: splice <img> snippets into this file

# `app` is optional — omit it for static sites or pure CLI shots.
app:
  command: "npm run dev"
  cwd: .
  ready:
    url: http://localhost:5173   # poll until it responds (or use: port / log_line)
    timeout: 30

shots:
  - name: home
    kind: web
    url: http://localhost:5173/
    viewport: { width: 1280, height: 800 }
    full_page: true
    alt: "Home page"
    # steps:                      # optional interactions before the screenshot
    #   - { click: "text=Sign in" }
    #   - { fill: ["#email", "demo@example.com"] }
    #   - { wait_for: "#chart" }

  - name: cli-help
    kind: cli
    command: "mytool --help"
    # style: native    # macOS default: a REAL Terminal.app screenshot.
    #                  # use 'rendered' for a synthetic terminal card (any OS, no permission).
    # cols: 90         # terminal width; rows controls window height
    # rows: 20
    alt: "Top-level CLI help output"

  # A session captures a stateful, multi-command flow in ONE persistent Terminal
  # window (macOS): the shell state carries across steps, one screenshot per step.
  # - name: demo-flow
  #   kind: session
  #   clear_between: true
  #   steps:
  #     - { name: step-one, command: "mytool init", alt: "first command" }
  #     - { name: step-two, command: "mytool run",  alt: "second, same shell" }
"""


@app.command()
def init(
    path: str = ".shotlist.yaml",
    force: bool = False,
) -> None:
    """Write a starter .shotlist.yaml shot list."""
    target = Path(path)
    if target.exists() and not force:
        typer.echo(f"refusing to overwrite existing {target} (use --force)")
        raise typer.Exit(1)
    target.write_text(_STARTER_YAML)
    typer.echo(f"wrote {target}")


@app.command()
def validate(
    config: str = typer.Option(".shotlist.yaml", "--config", "-c"),  # noqa: B008
) -> None:
    """Check that a shot list loads and is valid."""
    try:
        cfg = config_module.load(config)
    except config_module.ConfigError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    typer.echo(f"valid ({len(cfg.shots)} shots)")


@app.command()
def run(
    config: str = typer.Option(".shotlist.yaml", "--config", "-c"),  # noqa: B008
    only: list[str] = typer.Option(default_factory=list, show_default=False),  # noqa: B008
    version: str | None = typer.Option(None),
    report: bool | None = typer.Option(
        None,
        "--report/--no-report",
        help="Write manifest.json + index.html beside the shots (default: on).",
    ),
) -> None:
    """Capture all configured shots (filter with --only)."""
    try:
        cfg = config_module.load(config)
        if version is not None:
            cfg.output.version = version
        if report is not None:
            cfg.output.report = report
        repo_root = Path(config).resolve().parent
        results = engine.run(cfg, repo_root, only or None, config_path=config)
    except (config_module.ConfigError, ReadinessError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc

    for result in results:
        typer.echo(f"{result.name} -> {result.src}")
    typer.echo(f"captured {len(results)} shot(s)")


_CHECK_SYMBOLS = {
    "unchanged": "✓",
    "changed": "✗",
    "added": "+",
    "removed": "–",
    "skipped": "·",
}


def _recapture_probe(cfg: config_module.Config, tmp: str) -> config_module.Config:
    """A copy of ``cfg`` that captures into ``tmp`` with no side-effect artifacts.

    ``check`` re-captures into a throwaway directory so it never overwrites the
    committed baseline, splices the README, or renumbers files.
    """
    return cfg.model_copy(
        update={
            "output": cfg.output.model_copy(
                update={"dir": tmp, "version": None, "readme": None, "report": False}
            )
        }
    )


def _write_check_report(
    result: CheckResult,
    baseline: Manifest,
    current_by_name: dict[str, CaptureResult],
    baseline_dir: Path,
    diff_dir: Path,
) -> dict[str, str]:
    """Write a 3-up diff PNG per changed shot plus a full ``check-report.html``.

    The report lists *every* shot (not only the failures) with a status badge and
    reason; changed shots additionally embed their diff image. Returns the
    ``name -> diff filename`` map so callers can link each drift to its PNG.
    """
    base_by_name = {shot["name"]: shot for shot in baseline["shots"]}
    diff_dir.mkdir(parents=True, exist_ok=True)
    diff_files: dict[str, str] = {}
    for shot_diff in result.diffs:
        if shot_diff.status != "changed":
            continue
        if shot_diff.name not in base_by_name or shot_diff.name not in current_by_name:
            continue
        baseline_png = (baseline_dir / base_by_name[shot_diff.name]["file"]).read_bytes()
        current_png = current_by_name[shot_diff.name].path.read_bytes()
        filename = f"{slugify(shot_diff.name)}.diff.png"
        (diff_dir / filename).write_bytes(diff_images(baseline_png, current_png).image)
        diff_files[shot_diff.name] = filename

    rows = [
        ReportRow(
            name=shot_diff.name,
            status=shot_diff.status,
            reason=shot_diff.reason,
            diff_file=diff_files.get(shot_diff.name),
        )
        for shot_diff in result.diffs
    ]
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    (diff_dir / CHECK_REPORT_NAME).write_text(render_check_report(rows, generated_at=generated_at))
    return diff_files


def _package_version(name: str) -> str | None:
    """Installed version of ``name``, or ``None`` when it can't be resolved."""
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _chromium_version() -> str | None:
    """Launch headless Chromium briefly to read its version; ``None`` on failure.

    Only called when the baseline recorded a Chromium version, so an ordinary
    check never pays this launch cost. Playwright is already a hard dependency.
    """
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                return browser.version
            finally:
                browser.close()
    except Exception:
        return None


def _current_environment(*, probe_chromium: bool) -> dict[str, str | None]:
    """Build this machine's environment stamp in Contract-A shape.

    ``chromium`` is resolved only when ``probe_chromium`` is set — i.e. when the
    baseline carries a Chromium version worth comparing against — otherwise it is
    ``None`` and skipped by :func:`compare_environments`. A small local helper on
    purpose: the report module owns its own copy and the integrate task unifies
    them later.
    """
    return {
        "shotlist": _package_version("shotlist"),
        "python": platform.python_version(),
        "platform": sys.platform,
        "playwright": _package_version("playwright"),
        "chromium": _chromium_version() if probe_chromium else None,
    }


def _environment_mismatches(baseline: Mapping[str, object]) -> list[tuple[str, str, str]]:
    """Compare the baseline's optional ``environment`` block against this machine."""
    raw_env = baseline.get("environment")
    baseline_env = raw_env if isinstance(raw_env, Mapping) else None
    probe_chromium = baseline_env is not None and baseline_env.get("chromium") is not None
    current_env = _current_environment(probe_chromium=probe_chromium)
    return compare_environments(baseline_env, current_env)


def _json_document(
    result: CheckResult,
    env_mismatches: list[tuple[str, str, str]],
    diff_files: dict[str, str],
) -> dict[str, object]:
    """The machine-readable drift report (Contract B) emitted by ``--json``."""
    return {
        "drifted": result.drifted,
        "environment_mismatch": [f"{key}: {old} -> {new}" for key, old, new in env_mismatches],
        "shots": [
            {
                "name": d.name,
                "status": d.status,
                "reason": d.reason,
                "changed_pixel_ratio": d.changed_pixel_ratio,
                "diff_file": diff_files.get(d.name),
            }
            for d in result.diffs
        ],
    }


def _print_human_report(
    result: CheckResult,
    env_mismatches: list[tuple[str, str, str]],
    diff_files: dict[str, str],
    diff_dir: Path | None,
) -> None:
    """Print the per-shot lines, environment warnings, and the drift verdict."""
    for shot_diff in result.diffs:
        line = f"{_CHECK_SYMBOLS[shot_diff.status]} {shot_diff.name}  {shot_diff.status}"
        if shot_diff.reason:
            line += f" ({shot_diff.reason})"
        if diff_dir is not None and shot_diff.name in diff_files:
            line += f"  → {diff_dir / diff_files[shot_diff.name]}"
        typer.echo(line)
    for key, old, new in env_mismatches:
        typer.echo(f"⚠ environment: {key} {old} -> {new} (drift may be environmental)")
    if result.drifted:
        if diff_files and diff_dir is not None:
            typer.echo(f"drift detected — see {diff_dir / CHECK_REPORT_NAME}")
        else:
            typer.echo("drift detected — run `shotlist check --update` to accept")
    else:
        typer.echo("no drift")


def _selective_update(
    cfg: config_module.Config,
    repo_root: Path,
    config_path: str,
    only: list[str],
    human: Callable[[str], None],
) -> None:
    """Re-bless just the named deterministic shots, in place.

    Recaptures only ``only``, writes each new PNG over the baseline file recorded
    in the manifest (preserving its ``NN-`` numbering — the engine is *not* let
    loose to renumber), and rewrites just those entries' ``sha256``/``bytes`` plus
    the manifest ``generated_at``. Every other entry and every top-level key this
    command doesn't manage — including a Contract-A ``environment`` stamp — is
    copied through untouched. A selectively re-blessed shot therefore keeps the
    OLD environment stamp; run a full ``check --update`` to refresh it.
    """
    baseline_dir = Writer(cfg.output, repo_root).target_dir()
    baseline_path = baseline_dir / MANIFEST_NAME
    if not baseline_path.exists():
        human(
            f"no baseline manifest at {baseline_path}; "
            "run `shotlist run` (or `shotlist check --update`) first"
        )
        raise typer.Exit(1)
    baseline = json.loads(baseline_path.read_text())
    base_by_name = {shot["name"]: shot for shot in baseline["shots"]}
    known = {shot.name for shot in cfg.shots}
    deterministic = {shot.name for shot in cfg.shots if _is_deterministic(shot)}

    for name in only:
        if name not in known:
            human(f"unknown shot: {name}")
            raise typer.Exit(1)
        if name not in deterministic:
            human(f"cannot re-bless '{name}': native/session shots aren't drift-checkable")
            raise typer.Exit(1)
        if name not in base_by_name:
            human(f"cannot re-bless '{name}': not in the baseline manifest (run a full --update)")
            raise typer.Exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        results = engine.run(
            _recapture_probe(cfg, tmp), repo_root, only=list(only), config_path=config_path
        )
        current_by_name = {result.name: result for result in results}
        for name in only:
            data = current_by_name[name].path.read_bytes()
            (baseline_dir / base_by_name[name]["file"]).write_bytes(data)
            entry = base_by_name[name]
            entry["sha256"] = hashlib.sha256(data).hexdigest()
            entry["bytes"] = len(data)

    baseline["generated_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    baseline_path.write_text(json.dumps(baseline, indent=2) + "\n")
    human("re-blessed: " + ", ".join(only))


@app.command()
def check(
    config: str = typer.Option(".shotlist.yaml", "--config", "-c"),  # noqa: B008
    update: bool = typer.Option(
        False, "--update", help="Accept the current screenshots as the new baseline."
    ),
    only: list[str] = typer.Option(  # noqa: B008
        default_factory=list,
        show_default=False,
        help="With --update, re-bless only these shots in place (repeatable).",
    ),
    diff: str | None = typer.Option(
        None,
        "--diff",
        help="Write per-shot diff PNGs + check-report.html into DIR.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit the drift report as JSON on stdout (human lines go to stderr).",
    ),
) -> None:
    """Re-capture and fail if deterministic shots drifted from the committed baseline.

    Compares a fresh capture against the committed ``manifest.json``. An identical
    sha256 is unchanged; otherwise, when ``check.max_diff_pixel_ratio`` is set, the
    shot is pixel-diffed and only counts as drift once the changed-pixel fraction
    exceeds that budget (the reason carries the stats). Only deterministic shots
    (web, rendered CLI) are compared; native/session shots are skipped. Exits
    non-zero on drift.

    ``--update`` re-shoots and writes the whole baseline instead of checking.
    ``--update --only NAME`` (repeatable) re-blesses just those shots in place,
    preserving the baseline's file numbering and every manifest key it doesn't
    manage — including a top-level ``environment`` stamp, which therefore keeps its
    OLD value for a selectively re-blessed shot (an accepted trade-off; run a full
    ``--update`` to refresh it). With ``--json`` stdout carries only the JSON
    document; all human lines are routed to stderr.
    """

    def human(message: str) -> None:
        typer.echo(message, err=json_output)

    diff_dir = Path(diff) if diff is not None else None
    try:
        cfg = config_module.load(config)
        repo_root = Path(config).resolve().parent

        if only and not update:
            raise typer.BadParameter("--only is only valid together with --update")
        if update and only:
            _selective_update(cfg, repo_root, config, only, human)
            return
        if update:
            engine.run(cfg, repo_root, config_path=config)
            human("baseline updated")
            return

        baseline_dir = Writer(cfg.output, repo_root).target_dir()
        baseline_path = baseline_dir / MANIFEST_NAME
        if not baseline_path.exists():
            human(
                f"no baseline manifest at {baseline_path}; "
                "run `shotlist run` (or `shotlist check --update`) first"
            )
            raise typer.Exit(1)
        baseline = json.loads(baseline_path.read_text())
        env_mismatches = _environment_mismatches(baseline)
        max_ratio = cfg.check.max_diff_pixel_ratio
        diff_files: dict[str, str] = {}

        # Re-capture only the deterministic shots, into a temp dir, so checking is
        # non-destructive and never re-shoots a real Terminal window.
        checkable = [shot.name for shot in cfg.shots if _is_deterministic(shot)]
        if checkable:
            with tempfile.TemporaryDirectory() as tmp:
                results = engine.run(
                    _recapture_probe(cfg, tmp), repo_root, only=checkable, config_path=config
                )
                current = build_manifest(results, generated_at="", config=config)
                current_by_name = {result.name: result for result in results}
                base_by_name = {shot["name"]: shot for shot in baseline["shots"]}

                def _load_pair(name: str) -> tuple[bytes, bytes]:
                    baseline_png = (baseline_dir / base_by_name[name]["file"]).read_bytes()
                    return baseline_png, current_by_name[name].path.read_bytes()

                result = compare_manifests(
                    baseline, current, max_diff_pixel_ratio=max_ratio, load_pair=_load_pair
                )
                if diff_dir is not None:
                    diff_files = _write_check_report(
                        result, baseline, current_by_name, baseline_dir, diff_dir
                    )
        else:
            current = build_manifest([], generated_at="", config=config)
            result = compare_manifests(baseline, current, max_diff_pixel_ratio=max_ratio)
            if diff_dir is not None:
                diff_files = _write_check_report(result, baseline, {}, baseline_dir, diff_dir)

        if json_output:
            typer.echo(json.dumps(_json_document(result, env_mismatches, diff_files)))
        else:
            _print_human_report(result, env_mismatches, diff_files, diff_dir)
        if result.drifted:
            raise typer.Exit(1)
    except (config_module.ConfigError, ReadinessError) as exc:
        human(str(exc))
        raise typer.Exit(1) from exc
