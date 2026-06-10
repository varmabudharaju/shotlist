import subprocess
from pathlib import Path

import pytest

from capture.backends.native_terminal import NativeCaptureError, capture_terminal

_SYS = "capture.backends.native_terminal.sys.platform"
_RUN = "capture.backends.native_terminal.subprocess.run"


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
