"""Capture CLI output as a styled terminal-window screenshot.

The command runs under a pseudo-terminal so tools emit their normal colors, the
output is converted to HTML, rendered as a terminal card (:mod:`capture.render`),
and screenshotted with Playwright.
"""

import contextlib
import fcntl
import os
import pty
import re
import select
import signal
import struct
import subprocess
import termios
import time

from playwright.sync_api import Page

from shotlist.config import CliShot
from shotlist.render import ansi_to_html, terminal_html


def _set_winsize(fd: int, cols: int, rows: int = 50) -> None:
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def run_command(
    command: str,
    cwd: str | None,
    cols: int,
    timeout: float = 60.0,
) -> str:
    """Run ``command`` under a PTY and return its raw (ANSI) output.

    A PTY makes tools emit colors as if attached to a real terminal. The command
    is killed if it does not finish within ``timeout`` so capture never hangs.
    """
    master, slave = pty.openpty()
    _set_winsize(slave, cols)
    env = {
        **os.environ,
        "TERM": "xterm-256color",
        "COLUMNS": str(cols),
        "FORCE_COLOR": "1",
        "CLICOLOR_FORCE": "1",
    }
    proc = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        start_new_session=True,
        close_fds=True,
    )
    os.close(slave)

    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.2)
            if not ready:
                continue
            try:
                data = os.read(master, 4096)
            except OSError:
                break  # slave closed — child finished
            if not data:
                break
            chunks.append(data)
    finally:
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait()
        os.close(master)

    return b"".join(chunks).decode(errors="replace")


def capture_cli(page: Page, shot: CliShot, cwd: str | None = None) -> bytes:
    """Run the shot's command and return a PNG of its rendered terminal output.

    ``cwd`` overrides ``shot.cwd`` when given (the engine passes the working
    directory resolved relative to the repo root).
    """
    working_dir = cwd if cwd is not None else shot.cwd
    raw = run_command(shot.command, working_dir, shot.cols)
    # Scrub non-deterministic fragments out of the raw ANSI text before it is
    # converted to HTML, so rendered CLI shots stay byte-stable across runs.
    for rule in shot.scrub:
        raw = re.sub(rule.pattern, rule.replace, raw)
    page.set_content(terminal_html(ansi_to_html(raw), shot.cols))
    return page.locator(".frame").screenshot()
