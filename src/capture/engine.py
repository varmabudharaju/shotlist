"""Orchestrate a capture run: boot the app, drive Chromium, write outputs.

This module glues the pieces together. It optionally starts the app via
:class:`~capture.lifecycle.AppProcess`, launches a single Chromium browser, walks
the selected shots routing each by ``kind`` to the web or CLI backend, and hands
the resulting bytes to :class:`~capture.output.Writer`. A ``try``/``finally``
guarantees the browser is closed and the app is stopped even when capture fails.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

from capture.backends.cli import capture_cli
from capture.backends.web import capture_web
from capture.config import CliShot, Config, WebShot
from capture.lifecycle import AppProcess
from capture.output import CaptureResult, Writer


def _select_shots(config: Config, only: list[str] | None) -> list[WebShot | CliShot]:
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


def run(
    config: Config,
    repo_root: Path,
    only: list[str] | None = None,
) -> list[CaptureResult]:
    """Capture the configured shots and return their on-disk results.

    Boots ``config.app`` when present (waiting on ``ready`` if given), launches
    one Chromium, captures each selected shot to ``NN-name.png`` via
    :class:`~capture.output.Writer`, and optionally splices the images into the
    README. The browser and app are always torn down, even on error.
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

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                for index, shot in enumerate(selected, start=1):
                    page = browser.new_page()
                    try:
                        if shot.kind == "web":
                            data = capture_web(page, shot)
                        else:
                            data = capture_cli(page, shot)
                        result = writer.write(index, shot.name, data, shot.alt, shot.kind)
                        results.append(result)
                    finally:
                        page.close()
            finally:
                browser.close()
    finally:
        if app is not None:
            app.stop()

    if config.output.readme is not None:
        writer.update_readme(results, repo_root / config.output.readme)

    return results
