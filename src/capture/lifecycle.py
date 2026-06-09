"""Start an app, wait until it is genuinely ready, and tear it down cleanly.

The two failure modes this module exists to prevent:

1. Screenshotting a half-booted app — solved by :meth:`AppProcess.wait_ready`,
   which polls an HTTP endpoint, TCP port, or log line until the app responds.
2. Leaking the dev server after capture — solved by launching the app in its own
   process group and killing the whole group on exit (even on crash / Ctrl-C).
"""

import contextlib
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from types import TracebackType
from typing import Self

from capture.config import ReadySpec


class ReadinessError(RuntimeError):
    """Raised when the app fails to become ready before its timeout."""


def _http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (local dev urls)
            return int(resp.status) < 500
    except urllib.error.HTTPError as exc:
        # Server responded (e.g. 404) — it is up.
        return int(exc.code) < 500
    except (urllib.error.URLError, OSError):
        return False


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class AppProcess:
    """A child app process launched in its own process group.

    Usage::

        with AppProcess("npm run dev") as app:
            app.wait_ready(ready_spec)
            ...  # capture
        # app (and any children it spawned) are guaranteed dead here
    """

    def __init__(
        self,
        command: str,
        cwd: str = ".",
        env: dict[str, str] | None = None,
    ) -> None:
        self.command = command
        self.cwd = cwd
        self.env = env or {}
        self._proc: subprocess.Popen[bytes] | None = None
        self._lines: list[str] = []
        self._reader: threading.Thread | None = None

    def start(self) -> Self:
        full_env = {**os.environ, **self.env}
        self._proc = subprocess.Popen(
            self.command,
            shell=True,
            cwd=self.cwd,
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # detach into its own process group
        )
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()
        return self

    def _drain(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for raw in proc.stdout:
            self._lines.append(raw.decode(errors="replace"))

    @property
    def output(self) -> str:
        """Everything the app has printed to stdout/stderr so far."""
        return "".join(self._lines)

    @property
    def returncode(self) -> int | None:
        return None if self._proc is None else self._proc.poll()

    def wait_ready(self, ready: ReadySpec) -> None:
        """Block until the readiness probe passes or the timeout elapses."""
        if self._proc is None:
            raise ReadinessError("app was not started before wait_ready()")
        deadline = time.monotonic() + ready.timeout
        while time.monotonic() < deadline:
            code = self._proc.poll()
            if code is not None:
                raise ReadinessError(
                    f"app exited early with code {code} before becoming ready.\n"
                    f"--- app output ---\n{self.output}"
                )
            if self._is_ready(ready):
                return
            time.sleep(0.1)
        raise ReadinessError(
            f"app not ready after {ready.timeout}s.\n--- app output ---\n{self.output}"
        )

    def _is_ready(self, ready: ReadySpec) -> bool:
        if ready.url is not None:
            return _http_ok(ready.url)
        if ready.port is not None:
            return _port_open(ready.port)
        if ready.log_line is not None:
            return ready.log_line in self.output
        return True

    def stop(self, grace: float = 5.0) -> None:
        """Terminate the app's whole process group; safe to call repeatedly."""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            self._signal_group(proc, signal.SIGTERM)
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                self._signal_group(proc, signal.SIGKILL)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=grace)
        if self._reader is not None:
            self._reader.join(timeout=1.0)
            self._reader = None

    @staticmethod
    def _signal_group(proc: subprocess.Popen[bytes], sig: int) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError):
            # Already gone, or group disappeared between poll and signal.
            with contextlib.suppress(ProcessLookupError):
                proc.send_signal(sig)

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
