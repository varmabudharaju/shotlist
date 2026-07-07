"""Engine integration tests.

These exercise :func:`capture.engine.run`, which manages its own
``sync_playwright``. They must NOT request the ``page``/``browser`` fixtures from
``conftest`` — nesting two ``sync_playwright`` contexts raises.

The session-scoped ``browser`` fixture in ``conftest`` keeps a ``sync_playwright``
loop running for the whole test session, so calling ``engine.run`` (which opens
its own) on the main thread would hit that nesting guard. We therefore drive the
engine on a fresh worker thread, which has no running event loop — the standard
way to use the sync Playwright API alongside another sync session.
"""

import json
import socket
import sys
import threading
from pathlib import Path

import pytest

from shotlist.config import (
    AppSpec,
    CliShot,
    Config,
    OutputSpec,
    ReadySpec,
    SessionShot,
    SessionStep,
    Viewport,
    WebShot,
)
from shotlist.engine import (
    CaptureError,
    RunOutcome,
    ShotFailure,
    _capture_shot,
    _is_deterministic,
    _shot_needs_page,
    run,
)
from shotlist.output import CaptureResult
from tests.conftest import PNG_MAGIC

INDEX_HTML = (
    "<!doctype html><html><head><meta charset='utf-8'></head>"
    "<body><h1>hello capture</h1></body></html>"
)


def _fake_terminal(command: str, cwd: str, cols: int, rows: int) -> bytes:
    """Stand in for the real Terminal screenshot — no GUI in tests."""
    return PNG_MAGIC + command.encode()


def _fake_session(
    steps: list[tuple[str, bool, int]],
    cwd: str,
    cols: int,
    rows: int,
) -> list[bytes]:
    return [PNG_MAGIC + command.encode() for command, _clear, _wait in steps]


def run_outcome(
    config: Config,
    repo_root: Path,
    only: list[str] | None = None,
    keep_going: bool = False,
) -> RunOutcome:
    """Run :func:`engine.run` on a worker thread so it gets a clean event loop.

    The session-scoped ``browser`` fixture keeps a ``sync_playwright`` loop alive,
    so the engine (which opens its own) must run off the main thread. Any
    exception is captured and re-raised on the main thread for the test to assert.
    """
    box: list[RunOutcome] = []
    error: list[BaseException] = []

    def target() -> None:
        try:
            box.append(run(config, repo_root, only, keep_going=keep_going))
        except BaseException as exc:  # noqa: BLE001 - re-raised on the main thread
            error.append(exc)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return box[0]


def run_engine(
    config: Config,
    repo_root: Path,
    only: list[str] | None = None,
) -> list[CaptureResult]:
    """Run the engine and return just the successful results (legacy helper)."""
    return run_outcome(config, repo_root, only).results


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


def connectable(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def test_cli_shot_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    config = Config(
        output=OutputSpec(dir="shots"),
        app=None,
        shots=[CliShot(name="greet", kind="cli", command="echo hello")],
    )
    results = run_engine(config, tmp_path)

    assert len(results) == 1
    expected = tmp_path / "shots" / "01-greet.png"
    assert expected.exists()
    assert expected.read_bytes().startswith(PNG_MAGIC)
    assert results[0].path == expected
    assert results[0].name == "greet"


def test_only_filter_selects_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    config = Config(
        output=OutputSpec(dir="shots"),
        app=None,
        shots=[
            CliShot(name="first", kind="cli", command="echo one"),
            CliShot(name="second", kind="cli", command="echo two"),
        ],
    )
    results = run_engine(config, tmp_path, only=["second"])

    assert len(results) == 1
    assert results[0].name == "second"
    assert (tmp_path / "shots" / "01-second.png").exists()


def test_only_filter_unknown_name_raises(tmp_path: Path) -> None:
    config = Config(
        output=OutputSpec(dir="shots"),
        app=None,
        shots=[CliShot(name="first", kind="cli", command="echo one")],
    )
    with pytest.raises(ValueError, match="nope"):
        run_engine(config, tmp_path, only=["nope"])


def test_web_shot_with_app_lifecycle(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(INDEX_HTML)
    port = free_port()
    config = Config(
        output=OutputSpec(dir="shots"),
        app=AppSpec(
            command=f"{sys.executable} -m http.server {port} --bind 127.0.0.1",
            cwd=".",
            ready=ReadySpec(url=f"http://127.0.0.1:{port}/", timeout=10),
        ),
        shots=[
            WebShot(
                name="home",
                kind="web",
                url=f"http://127.0.0.1:{port}/index.html",
                viewport=Viewport(width=640, height=480),
                full_page=True,
            )
        ],
    )
    results = run_engine(config, tmp_path)

    assert len(results) == 1
    png = tmp_path / "shots" / "01-home.png"
    assert png.exists()
    assert png.read_bytes().startswith(PNG_MAGIC)
    # The app must be torn down after the run.
    assert not connectable(port)


def test_readme_insertion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    config = Config(
        output=OutputSpec(dir="shots", readme="README.md"),
        app=None,
        shots=[CliShot(name="greet", kind="cli", command="echo hi", alt="a greeting")],
    )
    run_engine(config, tmp_path)

    readme = tmp_path / "README.md"
    assert readme.exists()
    text = readme.read_text()
    assert "<!-- shotlist:start -->" in text
    assert "<img" in text


def test_session_expands_to_numbered_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal_session", _fake_session)
    config = Config(
        output=OutputSpec(dir="shots"),
        app=None,
        shots=[
            SessionShot(
                name="flow",
                kind="session",
                steps=[
                    SessionStep(name="first", command="echo one", alt="step one"),
                    SessionStep(name="second", command="echo two"),
                ],
            )
        ],
    )
    results = run_engine(config, tmp_path)

    assert len(results) == 2
    assert [r.name for r in results] == ["first", "second"]
    assert (tmp_path / "shots" / "01-first.png").exists()
    assert (tmp_path / "shots" / "02-second.png").exists()


def test_run_writes_manifest_and_gallery_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    config = Config(
        output=OutputSpec(dir="shots"),
        app=None,
        shots=[CliShot(name="greet", kind="cli", command="echo hi", alt="a greeting")],
    )
    run_engine(config, tmp_path)

    target = tmp_path / "shots"
    assert (target / "manifest.json").exists()
    assert (target / "index.html").exists()
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["shot_count"] == 1
    assert manifest["shots"][0]["name"] == "greet"
    assert manifest["shots"][0]["file"] == "01-greet.png"


def test_run_report_can_be_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    config = Config(
        output=OutputSpec(dir="shots", report=False),
        app=None,
        shots=[CliShot(name="greet", kind="cli", command="echo hi")],
    )
    run_engine(config, tmp_path)

    target = tmp_path / "shots"
    assert not (target / "manifest.json").exists()
    assert not (target / "index.html").exists()


def test_is_deterministic_by_kind_and_style() -> None:
    assert _is_deterministic(WebShot(name="w", kind="web", url="http://x")) is True
    assert (
        _is_deterministic(CliShot(name="c", kind="cli", command="x", style="rendered"))
        is True
    )
    assert (
        _is_deterministic(CliShot(name="c", kind="cli", command="x", style="native"))
        is False
    )
    # style pinned both ways: the platform default differs (native on macOS,
    # rendered on Linux), so an unpinned assertion flips per CI leg.
    assert (
        _is_deterministic(
            SessionShot(
                name="s",
                kind="session",
                style="native",
                steps=[SessionStep(name="a", command="x")],
            )
        )
        is False
    )
    assert (
        _is_deterministic(
            SessionShot(
                name="s",
                kind="session",
                style="rendered",
                steps=[SessionStep(name="a", command="x")],
            )
        )
        is True
    )


def test_rendered_session_is_deterministic_and_needs_page() -> None:
    rendered = SessionShot(
        name="s",
        kind="session",
        style="rendered",
        steps=[SessionStep(name="a", command="echo x")],
    )
    native = SessionShot(
        name="s",
        kind="session",
        style="native",
        steps=[SessionStep(name="a", command="echo x")],
    )
    assert _is_deterministic(rendered) is True
    assert _shot_needs_page(rendered) is True
    assert _is_deterministic(native) is False
    assert _shot_needs_page(native) is False


def test_rendered_session_routes_to_cli_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_capture(page: object, shot: SessionShot, cwd: str) -> list[bytes]:
        seen["page"] = page
        seen["cwd"] = cwd
        return [PNG_MAGIC + step.command.encode() for step in shot.steps]

    monkeypatch.setattr("shotlist.engine.capture_cli_session", fake_capture)
    shot = SessionShot(
        name="flow",
        kind="session",
        style="rendered",
        steps=[
            SessionStep(name="first", command="echo one", alt="step one"),
            SessionStep(name="second", command="echo two"),
        ],
    )
    sentinel_page = object()
    captures = _capture_shot(shot, tmp_path, sentinel_page)  # type: ignore[arg-type]

    # Routed to the rendered PTY backend with the engine's page and resolved cwd.
    assert seen["page"] is sentinel_page
    assert seen["cwd"] == str(tmp_path)
    # One Capture per step; kind stays "session"; source is the step command.
    assert [c[0] for c in captures] == ["first", "second"]
    assert [c[1] for c in captures] == ["step one", ""]
    assert [c[2] for c in captures] == ["session", "session"]
    assert [c[4] for c in captures] == ["echo one", "echo two"]


def test_run_marks_native_cli_as_nondeterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    config = Config(
        output=OutputSpec(dir="shots"),
        app=None,
        shots=[CliShot(name="term", kind="cli", command="echo hi", style="native")],
    )
    run_engine(config, tmp_path)

    manifest = json.loads((tmp_path / "shots" / "manifest.json").read_text())
    assert manifest["shots"][0]["deterministic"] is False
    assert manifest["shots"][0]["sha256"]


def test_run_records_command_as_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    config = Config(
        output=OutputSpec(dir="shots"),
        app=None,
        shots=[CliShot(name="greet", kind="cli", command="echo hello")],
    )
    results = run_engine(config, tmp_path)

    assert results[0].source == "echo hello"
    manifest = json.loads((tmp_path / "shots" / "manifest.json").read_text())
    assert manifest["shots"][0]["source"] == "echo hello"


def test_run_session_source_is_step_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal_session", _fake_session)
    config = Config(
        output=OutputSpec(dir="shots"),
        app=None,
        shots=[
            SessionShot(
                name="flow",
                kind="session",
                steps=[
                    SessionStep(name="first", command="echo one", alt="step one"),
                    SessionStep(name="second", command="echo two"),
                ],
            )
        ],
    )
    results = run_engine(config, tmp_path)

    assert [r.source for r in results] == ["echo one", "echo two"]
    manifest = json.loads((tmp_path / "shots" / "manifest.json").read_text())
    assert [s["source"] for s in manifest["shots"]] == ["echo one", "echo two"]


def test_run_stamps_environment_and_git_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    config = Config(
        output=OutputSpec(dir="shots"),
        app=None,
        # style pinned: the platform default resolves to `rendered` on Linux,
        # which launches Chromium and stamps a real version instead of None.
        shots=[CliShot(name="greet", kind="cli", command="echo hi", style="native")],
    )
    run_engine(config, tmp_path)

    manifest = json.loads((tmp_path / "shots" / "manifest.json").read_text())
    env = manifest["environment"]
    assert set(env) == {"shotlist", "python", "platform", "playwright", "chromium"}
    # No browser was launched for a native CLI shot.
    assert env["chromium"] is None
    # tmp_path is not a git repo, so git_sha degrades to None (present as a key).
    assert "git_sha" in manifest
    assert manifest["git_sha"] is None


def test_run_writes_evidence_doc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    config = Config(
        output=OutputSpec(dir="shots", evidence="docs/test-evidence.md"),
        app=None,
        shots=[CliShot(name="greet", kind="cli", command="echo hi", alt="a greeting")],
    )
    run_engine(config, tmp_path)

    evidence = tmp_path / "docs" / "test-evidence.md"
    assert evidence.exists()
    text = evidence.read_text()
    assert text.startswith("# shotlist — test evidence")
    assert "### Greet" in text
    assert "a greeting" in text
    assert "`echo hi`" in text

    # Idempotent: a second run leaves the content byte-identical.
    before = evidence.read_text()
    run_engine(config, tmp_path)
    assert evidence.read_text() == before


def test_run_evidence_skipped_when_report_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `shotlist check` probes with report=False; evidence must not be written then,
    # so a check never rewrites the committed evidence doc from temp captures.
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    config = Config(
        output=OutputSpec(dir="shots", report=False, evidence="docs/test-evidence.md"),
        app=None,
        shots=[CliShot(name="greet", kind="cli", command="echo hi")],
    )
    run_engine(config, tmp_path)

    assert not (tmp_path / "docs" / "test-evidence.md").exists()


def test_run_gallery_uses_config_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    config = Config(
        output=OutputSpec(dir="shots", title="Acme Docs"),
        app=None,
        shots=[CliShot(name="greet", kind="cli", command="echo hi")],
    )
    run_engine(config, tmp_path)

    gallery = (tmp_path / "shots" / "index.html").read_text()
    assert "<h1>Acme Docs screenshots</h1>" in gallery


class _FlakyTerminal:
    """A ``capture_terminal`` stub that fails ``fails`` times, then succeeds.

    Records how many times it was called so retry accounting can be asserted
    without any real Terminal window or browser.
    """

    def __init__(self, fails: int) -> None:
        self.fails = fails
        self.calls = 0

    def __call__(self, command: str, cwd: str, cols: int, rows: int) -> bytes:
        self.calls += 1
        if self.calls <= self.fails:
            raise RuntimeError(f"terminal boom {self.calls}")
        return PNG_MAGIC + command.encode()


def _native(name: str, command: str, retries: int = 0) -> CliShot:
    return CliShot(name=name, kind="cli", command=command, style="native", retries=retries)


def test_run_returns_run_outcome(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    config = Config(output=OutputSpec(dir="shots"), app=None, shots=[_native("greet", "echo hi")])

    outcome = run_outcome(config, tmp_path)

    assert isinstance(outcome, RunOutcome)
    assert [r.name for r in outcome.results] == ["greet"]
    assert outcome.failures == []


def test_retry_succeeds_after_transient_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flaky = _FlakyTerminal(fails=2)
    monkeypatch.setattr("shotlist.engine.capture_terminal", flaky)
    config = Config(
        output=OutputSpec(dir="shots"),
        app=None,
        shots=[_native("greet", "echo hi", retries=2)],
    )

    outcome = run_outcome(config, tmp_path)

    # attempts = retries(2) + 1, exhausted only 2 failures before the success.
    assert flaky.calls == 3
    assert [r.name for r in outcome.results] == ["greet"]
    assert outcome.failures == []
    assert (tmp_path / "shots" / "01-greet.png").exists()


def test_retry_exhausted_raises_capture_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flaky = _FlakyTerminal(fails=5)
    monkeypatch.setattr("shotlist.engine.capture_terminal", flaky)
    config = Config(
        output=OutputSpec(dir="shots"),
        app=None,
        shots=[_native("greet", "echo hi", retries=1)],
    )

    with pytest.raises(CaptureError, match=r"shot 'greet' failed: terminal boom 2"):
        run_outcome(config, tmp_path)
    # attempts = retries(1) + 1 = 2, no more.
    assert flaky.calls == 2


def test_fail_fast_capture_error_is_one_line_and_chained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(command: str, cwd: str, cols: int, rows: int) -> bytes:
        raise RuntimeError("line one\nline two")

    monkeypatch.setattr("shotlist.engine.capture_terminal", boom)
    config = Config(output=OutputSpec(dir="shots"), app=None, shots=[_native("greet", "echo hi")])

    with pytest.raises(CaptureError) as exc_info:
        run_outcome(config, tmp_path)
    assert str(exc_info.value) == "shot 'greet' failed: line one"
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_keep_going_collects_failures_and_stays_contiguous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def selective(command: str, cwd: str, cols: int, rows: int) -> bytes:
        if "boom" in command:
            raise RuntimeError("kaboom")
        return PNG_MAGIC + command.encode()

    monkeypatch.setattr("shotlist.engine.capture_terminal", selective)
    config = Config(
        output=OutputSpec(dir="shots"),
        app=None,
        shots=[
            _native("first", "echo one"),
            _native("broken", "echo boom"),
            _native("third", "echo three"),
        ],
    )

    outcome = run_outcome(config, tmp_path, keep_going=True)

    assert [r.name for r in outcome.results] == ["first", "third"]
    assert outcome.failures == [ShotFailure(name="broken", kind="cli", error="kaboom")]
    # A failed shot consumes no index: numbering stays contiguous (01, 02).
    assert (tmp_path / "shots" / "01-first.png").exists()
    assert (tmp_path / "shots" / "02-third.png").exists()
    assert not (tmp_path / "shots" / "03-third.png").exists()
    # Partial outputs: manifest is written from the successful results only.
    manifest = json.loads((tmp_path / "shots" / "manifest.json").read_text())
    assert manifest["shot_count"] == 2
    assert [s["name"] for s in manifest["shots"]] == ["first", "third"]


def test_keep_going_empty_message_uses_exception_class_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(command: str, cwd: str, cols: int, rows: int) -> bytes:
        raise RuntimeError

    monkeypatch.setattr("shotlist.engine.capture_terminal", boom)
    config = Config(output=OutputSpec(dir="shots"), app=None, shots=[_native("greet", "echo hi")])

    outcome = run_outcome(config, tmp_path, keep_going=True)

    assert outcome.results == []
    assert outcome.failures == [ShotFailure(name="greet", kind="cli", error="RuntimeError")]


def test_keyboard_interrupt_is_not_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(command: str, cwd: str, cols: int, rows: int) -> bytes:
        raise KeyboardInterrupt

    monkeypatch.setattr("shotlist.engine.capture_terminal", interrupt)
    config = Config(output=OutputSpec(dir="shots"), app=None, shots=[_native("greet", "echo hi")])

    # Even with keep_going, a BaseException like Ctrl-C must propagate.
    with pytest.raises(KeyboardInterrupt):
        run_outcome(config, tmp_path, keep_going=True)
