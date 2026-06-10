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

import socket
import sys
import threading
from pathlib import Path

import pytest

from capture.config import (
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
from capture.engine import run
from capture.output import CaptureResult
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


def run_engine(
    config: Config,
    repo_root: Path,
    only: list[str] | None = None,
) -> list[CaptureResult]:
    """Run :func:`engine.run` on a worker thread so it gets a clean event loop."""
    results: list[CaptureResult] = []
    error: list[BaseException] = []

    def target() -> None:
        try:
            results.extend(run(config, repo_root, only))
        except BaseException as exc:  # noqa: BLE001 - re-raised on the main thread
            error.append(exc)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return results


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
    monkeypatch.setattr("capture.engine.capture_terminal", _fake_terminal)
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
    monkeypatch.setattr("capture.engine.capture_terminal", _fake_terminal)
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
    monkeypatch.setattr("capture.engine.capture_terminal", _fake_terminal)
    config = Config(
        output=OutputSpec(dir="shots", readme="README.md"),
        app=None,
        shots=[CliShot(name="greet", kind="cli", command="echo hi", alt="a greeting")],
    )
    run_engine(config, tmp_path)

    readme = tmp_path / "README.md"
    assert readme.exists()
    text = readme.read_text()
    assert "<!-- capture:start -->" in text
    assert "<img" in text


def test_session_expands_to_numbered_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("capture.engine.capture_terminal_session", _fake_session)
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
