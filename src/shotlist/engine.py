"""Orchestrate a shotlist run: boot the app, capture each shot, write outputs.

This module glues the pieces together. It optionally starts the app via
:class:`~shotlist.lifecycle.AppProcess`, then walks the selected shots routing
each to the right backend:

- web pages and *rendered* CLI shots go through one Chromium;
- *native* CLI shots screenshot a real Terminal window;
- *session* shots run several commands in one persistent Terminal window,
  capturing after each — so one session yields several numbered images.

Chromium is only launched when a shot actually needs it. A ``try``/``finally``
guarantees the browser is closed and the app is stopped even when capture fails.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

from shotlist.backends.cli import capture_cli
from shotlist.backends.native_terminal import capture_terminal, capture_terminal_session
from shotlist.backends.web import capture_web
from shotlist.config import CliShot, Config, SessionShot, WebShot
from shotlist.lifecycle import AppProcess
from shotlist.output import CaptureResult, Writer
from shotlist.report import write_report

Shot = WebShot | CliShot | SessionShot

# One produced image: (name, alt, kind, png_bytes, source).
# ``source`` is the URL (web) or command (cli / session step) that produced it.
Capture = tuple[str, str, str, bytes, str]


def _select_shots(config: Config, only: list[str] | None) -> list[Shot]:
    """Return the shots to capture, honoring an ``only`` name filter.

    Raises :class:`ValueError` listing any requested names that do not match a
    shot in the config.
    """
    if only is None:
        return list(config.shots)
    known = {shot.name for shot in config.shots}
    unknown = [name for name in only if name not in known]
    if unknown:
        raise ValueError(f"unknown shot names: {unknown}")
    wanted = set(only)
    return [shot for shot in config.shots if shot.name in wanted]


def _effective_style(shot: CliShot) -> str:
    """Resolve a CLI shot's capture style, defaulting to native on macOS."""
    if shot.style is not None:
        return shot.style
    return "native" if sys.platform == "darwin" else "rendered"


def _is_deterministic(shot: Shot) -> bool:
    """Whether a shot reproduces byte-for-byte across runs (so it can be drift-checked).

    Web pages and *rendered* CLI cards are Chromium renders and reproduce; a real
    Terminal screenshot (``native`` CLI and every ``session``) does not.
    """
    if isinstance(shot, WebShot):
        return True
    if isinstance(shot, CliShot):
        return _effective_style(shot) == "rendered"
    return False


def _resolve_cwd(cwd: str | None, repo_root: Path) -> str:
    return str((repo_root / cwd).resolve()) if cwd is not None else str(repo_root)


def _shot_needs_page(shot: Shot) -> bool:
    """True if the shot must render through Chromium (web or rendered CLI)."""
    if isinstance(shot, WebShot):
        return True
    if isinstance(shot, CliShot):
        return _effective_style(shot) == "rendered"
    return False


def _capture_shot(shot: Shot, repo_root: Path, page: Page | None) -> list[Capture]:
    """Capture one shot, returning one or more images (sessions yield many)."""
    if isinstance(shot, WebShot):
        assert page is not None  # guaranteed by _shot_needs_page
        return [(shot.name, shot.alt, "web", capture_web(page, shot), shot.url)]

    if isinstance(shot, SessionShot):
        cwd = _resolve_cwd(shot.cwd, repo_root)
        steps = [
            (
                step.command,
                step.clear if step.clear is not None else shot.clear_between,
                step.wait_ms,
            )
            for step in shot.steps
        ]
        images = capture_terminal_session(steps, cwd, shot.cols, shot.rows)
        return [
            (step.name, step.alt, "session", data, step.command)
            for step, data in zip(shot.steps, images, strict=True)
        ]

    cwd = _resolve_cwd(shot.cwd, repo_root)
    if _effective_style(shot) == "native":
        data = capture_terminal(shot.command, cwd, shot.cols, shot.rows)
        return [(shot.name, shot.alt, "cli", data, shot.command)]
    assert page is not None  # rendered CLI needs the browser
    return [(shot.name, shot.alt, "cli", capture_cli(page, shot, cwd), shot.command)]


def _capture_all(
    selected: list[Shot],
    repo_root: Path,
    writer: Writer,
    browser: Browser | None,
) -> list[CaptureResult]:
    results: list[CaptureResult] = []
    index = 0
    for shot in selected:
        page = browser.new_page() if (browser is not None and _shot_needs_page(shot)) else None
        try:
            captures = _capture_shot(shot, repo_root, page)
        finally:
            if page is not None:
                page.close()
        deterministic = _is_deterministic(shot)
        for name, alt, kind, data, source in captures:
            index += 1
            results.append(
                writer.write(index, name, data, alt, kind, deterministic, source)
            )
    return results


def run(
    config: Config,
    repo_root: Path,
    only: list[str] | None = None,
    config_path: str | None = None,
) -> list[CaptureResult]:
    """Capture the configured shots and return their on-disk results.

    Boots ``config.app`` when present (waiting on ``ready`` if given), captures
    each selected shot to ``NN-name.png`` via :class:`~shotlist.output.Writer`
    (a session expands to one image per step), and optionally splices the images
    into the README. Unless ``output.report`` is off it then writes the run's
    proof-report artifacts beside the PNGs: a captioned ``output.evidence`` doc
    (when configured) plus a ``manifest.json`` (stamped with per-shot sources, the
    run environment, and the git SHA) and an ``index.html`` gallery. The browser
    (when used) and the app are always torn down.
    """
    selected = _select_shots(config, only)
    writer = Writer(config.output, repo_root)
    results: list[CaptureResult] = []
    chromium_version: str | None = None

    app: AppProcess | None = None
    if config.app is not None:
        app = AppProcess(
            config.app.command,
            cwd=str((repo_root / config.app.cwd).resolve()),
            env=config.app.env,
        )
        app.start()
    try:
        if app is not None and config.app is not None and config.app.ready is not None:
            app.wait_ready(config.app.ready)

        if any(_shot_needs_page(shot) for shot in selected):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                chromium_version = browser.version
                try:
                    results = _capture_all(selected, repo_root, writer, browser)
                finally:
                    browser.close()
        else:
            results = _capture_all(selected, repo_root, writer, None)
    finally:
        if app is not None:
            app.stop()

    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    title = config.output.title or "shotlist"

    if config.output.readme is not None:
        writer.update_readme(results, repo_root / config.output.readme)

    # The evidence doc and the manifest/gallery are the run's "proof report"
    # artifacts, so both are gated on ``report``. This also keeps ``shotlist
    # check`` non-destructive: its probe runs with ``report=False`` and so never
    # rewrites the committed evidence doc from temp-dir captures.
    if config.output.report:
        if config.output.evidence is not None:
            writer.write_evidence(
                results,
                repo_root / config.output.evidence,
                generated_at=generated_at,
                title=title,
            )
        write_report(
            results,
            writer.target_dir(),
            generated_at=generated_at,
            config=config_path or "",
            title=title,
            chromium=chromium_version,
            repo_root=repo_root,
        )

    return results
