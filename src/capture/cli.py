"""Typer command-line interface for ``capture``.

Four commands cover the whole workflow: ``init`` writes a starter shot list,
``validate`` checks a shot list loads cleanly, ``run`` performs the capture, and
``check`` re-captures and fails if anything drifted from the committed baseline.
Errors from config loading and app readiness are turned into a single-line
message plus a non-zero exit, so the tool fails loudly but never with a
traceback.
"""

import json
import tempfile
from pathlib import Path

import typer

from capture import config as config_module
from capture import engine
from capture.check import compare_manifests
from capture.engine import _is_deterministic
from capture.lifecycle import ReadinessError
from capture.output import Writer
from capture.report import MANIFEST_NAME, build_manifest

app = typer.Typer(
    add_completion=False,
    help="Reproducible screenshot capture for docs.",
)

_STARTER_YAML = """\
# .capture.yaml — declarative shot list for `capture`.
# Describe how to start your app and what to capture, then run `capture run`.

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
    path: str = ".capture.yaml",
    force: bool = False,
) -> None:
    """Write a starter .capture.yaml shot list."""
    target = Path(path)
    if target.exists() and not force:
        typer.echo(f"refusing to overwrite existing {target} (use --force)")
        raise typer.Exit(1)
    target.write_text(_STARTER_YAML)
    typer.echo(f"wrote {target}")


@app.command()
def validate(
    config: str = typer.Option(".capture.yaml", "--config", "-c"),  # noqa: B008
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
    config: str = typer.Option(".capture.yaml", "--config", "-c"),  # noqa: B008
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


@app.command()
def check(
    config: str = typer.Option(".capture.yaml", "--config", "-c"),  # noqa: B008
    update: bool = typer.Option(
        False, "--update", help="Accept the current screenshots as the new baseline."
    ),
) -> None:
    """Re-capture and fail if deterministic shots drifted from the committed baseline.

    Compares a fresh capture against the committed ``manifest.json`` by per-shot
    hash. Only deterministic shots (web, rendered CLI) are compared; native shots
    are skipped. Exits non-zero on drift. ``--update`` re-shoots and writes the new
    baseline instead of checking.
    """
    try:
        cfg = config_module.load(config)
        repo_root = Path(config).resolve().parent

        if update:
            engine.run(cfg, repo_root, config_path=config)
            typer.echo("baseline updated")
            return

        baseline_path = Writer(cfg.output, repo_root).target_dir() / MANIFEST_NAME
        if not baseline_path.exists():
            typer.echo(
                f"no baseline manifest at {baseline_path}; "
                "run `capture run` (or `capture check --update`) first"
            )
            raise typer.Exit(1)
        baseline = json.loads(baseline_path.read_text())

        # Re-capture only the deterministic shots, into a temp dir, so checking is
        # non-destructive and never re-shoots a real Terminal window.
        checkable = [shot.name for shot in cfg.shots if _is_deterministic(shot)]
        if checkable:
            with tempfile.TemporaryDirectory() as tmp:
                probe = cfg.model_copy(
                    update={
                        "output": cfg.output.model_copy(
                            update={
                                "dir": tmp,
                                "version": None,
                                "readme": None,
                                "report": False,
                            }
                        )
                    }
                )
                results = engine.run(probe, repo_root, only=checkable, config_path=config)
                current = build_manifest(results, generated_at="", config=config)
        else:
            current = build_manifest([], generated_at="", config=config)

        result = compare_manifests(baseline, current)
    except (config_module.ConfigError, ReadinessError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc

    for diff in result.diffs:
        line = f"{_CHECK_SYMBOLS[diff.status]} {diff.name}  {diff.status}"
        if diff.reason:
            line += f" ({diff.reason})"
        typer.echo(line)

    if result.drifted:
        typer.echo("drift detected — run `capture check --update` to accept")
        raise typer.Exit(1)
    typer.echo("no drift")
