import os
import subprocess
import sys
from pathlib import Path

import pytest

from capture.backends.native_terminal import (
    NativeCaptureError,
    capture_terminal,
    capture_terminal_session,
)

_SYS = "capture.backends.native_terminal.sys.platform"
_RUN = "capture.backends.native_terminal.subprocess.run"
_CREATE = "capture.backends.native_terminal._create_session"
_STEP = "capture.backends.native_terminal._run_step"
_CLOSE = "capture.backends.native_terminal._close_session"


def test_requires_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_SYS, "linux")
    with pytest.raises(NativeCaptureError, match="macOS"):
        capture_terminal("echo hi", "/tmp", 80, 24)


def test_success_returns_png_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_SYS, "darwin")
    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"\x89PNG\r\n\x1a\nDATA")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(_RUN, fake_run)
    data = capture_terminal("echo hi", "/work/dir", 90, 28)
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    cmd = captured["cmd"]
    assert cmd[0] == "osascript"
    assert cmd[2] == "/work/dir"
    assert cmd[3] == "echo hi"
    assert cmd[4] == "90"
    assert cmd[5] == "28"


def test_failure_raises_with_permission_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_SYS, "darwin")

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, cmd, "", "not allowed")

    monkeypatch.setattr(_RUN, fake_run)
    with pytest.raises(NativeCaptureError, match="Screen Recording"):
        capture_terminal("echo hi", "/tmp", 80, 24)


def test_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_SYS, "darwin")

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd, 1.0)

    monkeypatch.setattr(_RUN, fake_run)
    with pytest.raises(NativeCaptureError, match="timed out"):
        capture_terminal("sleep 5", "/tmp", 80, 24)


def test_session_requires_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_SYS, "linux")
    with pytest.raises(NativeCaptureError, match="macOS"):
        capture_terminal_session([("echo a", True, 0)], "/tmp", 80, 24)


def test_session_captures_each_step_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_SYS, "darwin")
    calls: list[tuple[str, str, bool, int]] = []
    closed: list[str] = []

    monkeypatch.setattr(_CREATE, lambda cwd, cols, rows: "777")

    def fake_step(wid: str, command: str, clear: bool, wait_ms: int, out_path: str) -> None:
        calls.append((wid, command, clear, wait_ms))
        Path(out_path).write_bytes(b"\x89PNG\r\n\x1a\n" + command.encode())

    monkeypatch.setattr(_STEP, fake_step)
    monkeypatch.setattr(_CLOSE, lambda wid: closed.append(wid))

    images = capture_terminal_session(
        [("echo a", True, 0), ("echo b", False, 100)], "/work", 90, 22
    )

    assert len(images) == 2
    assert images[0].startswith(b"\x89PNG\r\n\x1a\n")
    assert calls == [("777", "echo a", True, 0), ("777", "echo b", False, 100)]
    assert closed == ["777"]  # window closed exactly once, at the end


def test_session_closes_window_even_on_step_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_SYS, "darwin")
    closed: list[str] = []
    monkeypatch.setattr(_CREATE, lambda cwd, cols, rows: "5")

    def boom(wid: str, command: str, clear: bool, wait_ms: int, out_path: str) -> None:
        raise NativeCaptureError("step blew up")

    monkeypatch.setattr(_STEP, boom)
    monkeypatch.setattr(_CLOSE, lambda wid: closed.append(wid))

    with pytest.raises(NativeCaptureError, match="blew up"):
        capture_terminal_session([("echo a", True, 0)], "/tmp", 80, 24)
    assert closed == ["5"]


@pytest.mark.skipif(
    sys.platform != "darwin" or os.environ.get("CAPTURE_E2E") != "1",
    reason="real Terminal capture; set CAPTURE_E2E=1 on macOS to run",
)
def test_real_capture_e2e(tmp_path: Path) -> None:
    """Genuinely drive Terminal.app and screenshot it (opt-in, not in CI)."""
    data = capture_terminal("echo e2e-ok", str(tmp_path), 70, 8)
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(data) > 1000
