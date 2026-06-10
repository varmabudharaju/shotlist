"""Orchestrate a capture run: boot the app, capture each shot, write outputs.

This module glues the pieces together. It optionally starts the app via
:class:`~capture.lifecycle.AppProcess`, then walks the selected shots routing
each to the right backend — web pages and *rendered* CLI shots go through one
Chromium; *native* CLI shots screenshot a real Terminal window. Chromium is only
launched when a shot actually needs it. A ``try``/``finally`` guarantees the
browser is closed and the app is stopped even when capture fails.
"""

import sys
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

from capture.backends.cli import capture_cli
from capture.backends.native_terminal import capture_terminal
from capture.backends.web import capture_web
from capture.config import CliShot, Config, WebShot
from capture.lifecycle import AppProcess
from capture.output import CaptureResult, Writer

Shot = WebShot | CliShot


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


def _resolve_cwd(shot: CliShot, repo_root: Path) -> str:
    if shot.cwd is not None:
        return str((repo_root / shot.cwd).resolve())
    return str(repo_root)


def _needs_browser(selected: list[Shot]) -> bool:
    """True if any shot must render through Chromium (web or rendered CLI)."""
    for shot in selected:
        if isinstance(shot, WebShot) or _effective_style(shot) == "rendered":
            return True
    return False


def _capture_shot(shot: Shot, repo_root: Path, page: Page | None) -> bytes:
    if isinstance(shot, WebShot):
        assert page is not None  # guaranteed by _needs_browser
        return capture_web(page, shot)
    cwd = _resolve_cwd(shot, repo_root)
    if _effective_style(shot) == "native":
        return capture_terminal(shot.command, cwd, shot.cols, shot.rows)
    assert page is not None  # rendered CLI needs the browser
    return capture_cli(page, shot, cwd)


def _capture_all(
    selected: list[Shot],
    repo_root: Path,
    writer: Writer,
    browser: Browser | None,
) -> list[CaptureResult]:
    results: list[CaptureResult] = []
    for index, shot in enumerate(selected, start=1):
        page = browser.new_page() if browser is not None else None
        try:
            data = _capture_shot(shot, repo_root, page)
        finally:
            if page is not None:
                page.close()
        results.append(writer.write(index, shot.name, data, shot.alt, shot.kind))
    return results


def run(
    config: Config,
    repo_root: Path,
    only: list[str] | None = None,
) -> list[CaptureResult]:
    """Capture the configured shots and return their on-disk results.

    Boots ``config.app`` when present (waiting on ``ready`` if given), captures
    each selected shot to ``NN-name.png`` via :class:`~capture.output.Writer`,
    and optionally splices the images into the README. The browser (when used)
    and the app are always torn down, even on error.
    """
    selected = _select_shots(config, only)
    writer = Writer(config.output, repo_root)
    results: list[CaptureResult] = []

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

        if _needs_browser(selected):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    results = _capture_all(selected, repo_root, writer, browser)
                finally:
                    browser.close()
        else:
            results = _capture_all(selected, repo_root, writer, None)
    finally:
        if app is not None:
            app.stop()

    if config.output.readme is not None:
        writer.update_readme(results, repo_root / config.output.readme)

    return results
