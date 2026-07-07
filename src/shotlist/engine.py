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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

from shotlist.backends.cli import capture_cli, capture_cli_session
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


@dataclass(frozen=True)
class ShotFailure:
    """A shot that exhausted its attempts, recorded when ``keep_going`` is set.

    ``kind`` is the shot's declared kind (``web``/``cli``/``session``) and
    ``error`` is a one-line reason (see :func:`_one_line_error`).
    """

    name: str
    kind: str
    error: str


class CaptureError(RuntimeError):
    """Raised when a shot fails its last attempt and the run is failing fast.

    The message is exactly ``shot '<name>' failed: <one-line reason>``; the
    original exception is chained (``raise ... from exc``) so the traceback is
    preserved for anyone who wants it, while the CLI can print just the message.
    """


@dataclass(frozen=True)
class RunOutcome:
    """The result of a run: the shots that were written, and any that failed.

    ``failures`` is only ever non-empty when the run was invoked with
    ``keep_going`` — fail-fast runs raise :class:`CaptureError` instead.
    """

    results: list[CaptureResult]
    failures: list[ShotFailure]


def _one_line_error(exc: Exception) -> str:
    """A single-line, user-facing reason for ``exc``.

    Uses the first line of ``str(exc)``; when the exception carries no message
    (e.g. ``raise RuntimeError``) it falls back to the exception's class name so
    the reason is never blank.
    """
    text = str(exc)
    first_line = text.splitlines()[0].strip() if text.strip() else ""
    return first_line or type(exc).__name__


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


def _effective_style(shot: CliShot | SessionShot) -> str:
    """Resolve a CLI or session shot's capture style, defaulting to native on macOS."""
    if shot.style is not None:
        return shot.style
    return "native" if sys.platform == "darwin" else "rendered"


def _is_deterministic(shot: Shot) -> bool:
    """Whether a shot reproduces byte-for-byte across runs (so it can be drift-checked).

    Web pages and *rendered* CLI/session cards are Chromium renders and reproduce;
    a real Terminal screenshot (``native`` CLI and ``native`` session) does not.
    """
    if isinstance(shot, WebShot):
        return True
    return _effective_style(shot) == "rendered"


def _resolve_cwd(cwd: str | None, repo_root: Path) -> str:
    return str((repo_root / cwd).resolve()) if cwd is not None else str(repo_root)


def _shot_needs_page(shot: Shot) -> bool:
    """True if the shot must render through Chromium (web, or rendered CLI/session)."""
    if isinstance(shot, WebShot):
        return True
    return _effective_style(shot) == "rendered"


def _capture_shot(shot: Shot, repo_root: Path, page: Page | None) -> list[Capture]:
    """Capture one shot, returning one or more images (sessions yield many)."""
    if isinstance(shot, WebShot):
        assert page is not None  # guaranteed by _shot_needs_page
        return [(shot.name, shot.alt, "web", capture_web(page, shot), shot.url)]

    if isinstance(shot, SessionShot):
        cwd = _resolve_cwd(shot.cwd, repo_root)
        if _effective_style(shot) == "rendered":
            assert page is not None  # guaranteed by _shot_needs_page
            images = capture_cli_session(page, shot, cwd)
        else:
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


def _capture_with_retries(
    shot: Shot,
    repo_root: Path,
    browser: Browser | None,
) -> list[Capture]:
    """Capture one shot, retrying up to ``shot.retries`` extra times on failure.

    Total attempts are ``getattr(shot, "retries", 0) + 1`` — the ``getattr`` means
    session shots (which have no ``retries`` field) naturally get a single attempt.
    Each attempt gets a FRESH Playwright page (closed in a ``finally``) so a page
    left in a bad state by a failed attempt never poisons the retry. Only
    ``Exception`` is caught, so ``KeyboardInterrupt`` still aborts the run; the
    last attempt's exception is re-raised when every attempt has failed.
    """
    attempts = getattr(shot, "retries", 0) + 1
    last_exc: Exception | None = None
    for _ in range(attempts):
        page = browser.new_page() if (browser is not None and _shot_needs_page(shot)) else None
        try:
            return _capture_shot(shot, repo_root, page)
        except Exception as exc:  # noqa: BLE001 - retried, then surfaced to the caller
            last_exc = exc
        finally:
            if page is not None:
                page.close()
    assert last_exc is not None  # attempts >= 1, so a failure was recorded
    raise last_exc


def _capture_all(
    selected: list[Shot],
    repo_root: Path,
    writer: Writer,
    browser: Browser | None,
    keep_going: bool = False,
) -> RunOutcome:
    """Capture every selected shot, writing each to a contiguously-numbered file.

    A shot that exhausts its attempts either aborts the run with a
    :class:`CaptureError` (``keep_going`` off) or is recorded as a
    :class:`ShotFailure` and skipped (``keep_going`` on). A failed shot consumes
    no index, so successful shots stay numbered ``01, 02, ...`` with no gaps.
    """
    results: list[CaptureResult] = []
    failures: list[ShotFailure] = []
    index = 0
    for shot in selected:
        try:
            captures = _capture_with_retries(shot, repo_root, browser)
        except Exception as exc:  # noqa: BLE001 - reported cleanly, never as a traceback
            reason = _one_line_error(exc)
            if not keep_going:
                raise CaptureError(f"shot '{shot.name}' failed: {reason}") from exc
            failures.append(ShotFailure(name=shot.name, kind=shot.kind, error=reason))
            continue
        deterministic = _is_deterministic(shot)
        for name, alt, kind, data, source in captures:
            index += 1
            results.append(
                writer.write(index, name, data, alt, kind, deterministic, source)
            )
    return RunOutcome(results=results, failures=failures)


def run(
    config: Config,
    repo_root: Path,
    only: list[str] | None = None,
    config_path: str | None = None,
    keep_going: bool = False,
) -> RunOutcome:
    """Capture the configured shots and return a :class:`RunOutcome`.

    Boots ``config.app`` when present (waiting on ``ready`` if given), captures
    each selected shot to ``NN-name.png`` via :class:`~shotlist.output.Writer`
    (a session expands to one image per step), and optionally splices the images
    into the README. Unless ``output.report`` is off it then writes the run's
    proof-report artifacts beside the PNGs: a captioned ``output.evidence`` doc
    (when configured) plus a ``manifest.json`` (stamped with per-shot sources, the
    run environment, and the git SHA) and an ``index.html`` gallery. The browser
    (when used) and the app are always torn down.

    Each shot may fail its attempts (``shot.retries`` + 1). With ``keep_going``
    off the first such failure aborts with a :class:`CaptureError`; with it on the
    failure is collected into ``RunOutcome.failures`` and the run continues, and
    every artifact (README splice, evidence, manifest, gallery) is written from
    the successful results only.
    """
    selected = _select_shots(config, only)
    writer = Writer(config.output, repo_root)
    outcome = RunOutcome(results=[], failures=[])
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
                    outcome = _capture_all(selected, repo_root, writer, browser, keep_going)
                finally:
                    browser.close()
        else:
            outcome = _capture_all(selected, repo_root, writer, None, keep_going)
    finally:
        if app is not None:
            app.stop()

    results = outcome.results
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

    return outcome
