import socket
import sys

import pytest

from shotlist.config import ReadySpec
from shotlist.lifecycle import AppProcess, ReadinessError


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


def http_server(port: int) -> str:
    return f"{sys.executable} -m http.server {port} --bind 127.0.0.1"


def test_ready_by_url_then_teardown() -> None:
    port = free_port()
    app = AppProcess(http_server(port))
    with app:
        app.wait_ready(ReadySpec(url=f"http://127.0.0.1:{port}/", timeout=10))
        assert connectable(port)
    # context exit must kill the server
    assert not connectable(port)
    assert app.returncode is not None


def test_ready_by_port() -> None:
    port = free_port()
    app = AppProcess(http_server(port))
    with app:
        app.wait_ready(ReadySpec(port=port, timeout=10))
        assert connectable(port)


def test_ready_by_log_line() -> None:
    code = 'import time; print("SERVER READY"); time.sleep(30)'
    app = AppProcess(f"{sys.executable} -u -c '{code}'")
    with app:
        app.wait_ready(ReadySpec(log_line="SERVER READY", timeout=10))
        assert "SERVER READY" in app.output


def test_timeout_when_never_ready() -> None:
    app = AppProcess(f"{sys.executable} -u -c 'import time; time.sleep(10)'")
    with app, pytest.raises(ReadinessError):
        app.wait_ready(ReadySpec(port=free_port(), timeout=1))


def test_app_exiting_early_is_reported() -> None:
    app = AppProcess(f"{sys.executable} -c 'raise SystemExit(3)'")
    with app, pytest.raises(ReadinessError, match="exited"):
        app.wait_ready(ReadySpec(port=free_port(), timeout=5))


def test_explicit_stop_is_idempotent() -> None:
    port = free_port()
    app = AppProcess(http_server(port))
    app.start()
    app.wait_ready(ReadySpec(url=f"http://127.0.0.1:{port}/", timeout=10))
    app.stop()
    app.stop()  # second stop must not raise
    assert not connectable(port)
