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
import shutil
import signal
import struct
import subprocess
import termios
import time

from playwright.sync_api import Page

from shotlist.config import CliShot, ScrubRule, SessionShot, SessionStep
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


# --- Rendered sessions: one persistent shell, a terminal card per step ---------

_STEP_TIMEOUT = 120.0


def _session_shell_argv() -> list[str]:
    """Prefer ``bash --noprofile --norc`` for the session shell; fall back to sh."""
    bash = shutil.which("bash")
    if bash is not None:
        return [bash, "--noprofile", "--norc"]
    return [shutil.which("sh") or "/bin/sh"]


class _PtySession:
    """One long-lived shell that backs a rendered ``session`` shot.

    The shell's stdout and stderr are a PTY so tools emit their normal colors, but
    its stdin is an ordinary pipe. That makes the shell *non-interactive*, which is
    what keeps transcripts deterministic: a non-interactive shell prints no ``PS1``
    prompt, does not echo the commands we feed it, and — crucially — emits none of
    the job-control ``[1] <pid>`` / ``[1]+ Done`` notices that an interactive shell
    prints for ``&``-backgrounded commands (those carry a live PID and would land
    inside a later step's snapshot). State — env vars, ``cd``, background jobs —
    genuinely persists across steps because every step runs in this one process.
    """

    def __init__(self, cwd: str | None, cols: int, rows: int) -> None:
        self._cwd = cwd
        self._cols = cols
        self._rows = rows
        self._master = -1
        self._stdin = -1
        self._proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        master, slave = pty.openpty()
        _set_winsize(slave, self._cols, self._rows)
        stdin_r, stdin_w = os.pipe()
        env = {
            **os.environ,
            "TERM": "xterm-256color",
            "COLUMNS": str(self._cols),
            "FORCE_COLOR": "1",
            "CLICOLOR_FORCE": "1",
        }
        self._proc = subprocess.Popen(
            _session_shell_argv(),
            cwd=self._cwd,
            stdin=stdin_r,
            stdout=slave,
            stderr=slave,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave)
        os.close(stdin_r)
        self._master = master
        self._stdin = stdin_w
        # Disable job control as the very first thing in the shell. A pipe-fed
        # shell is already non-interactive (monitor mode off), so this is belt and
        # suspenders that also satisfies the contract for the ``sh`` fallback.
        os.write(self._stdin, b"set +m\n")

    def run_step(
        self, name: str, command: str, wait_ms: int, index: int, timeout: float
    ) -> str:
        """Run one command and return its output (no prompt, no sentinel).

        Completion is detected by writing the command followed by a per-step
        sentinel print and reading the PTY until the sentinel line appears; the
        sentinel is then stripped. After completion the PTY is drained for a
        further ``wait_ms`` so a ``&``-backgrounded command's output can land.
        """
        sentinel = f"__SHOTLIST_DONE_{index}__"
        os.write(self._stdin, f"{command}\nprintf '%s\\n' {sentinel}\n".encode())
        buf = self._read_until(sentinel, name, command, timeout)
        before, _sep, after = buf.partition(sentinel)
        # ``printf`` terminates the sentinel with a newline; drop that one newline
        # but keep anything a background job may already have printed after it.
        if after.startswith("\n"):
            after = after[1:]
        output = before + after
        if wait_ms > 0:
            output += self._drain(wait_ms / 1000.0)
        return output

    def _read_until(self, sentinel: str, name: str, command: str, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        raw = b""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    f"session step {name!r} timed out after {timeout:.0f}s "
                    f"running: {command}"
                )
            ready, _, _ = select.select([self._master], [], [], min(remaining, 0.5))
            if not ready:
                continue
            try:
                data = os.read(self._master, 65536)
            except OSError:
                break  # the shell closed the PTY
            if not data:
                break
            raw += data
            decoded = raw.decode(errors="replace").replace("\r\n", "\n")
            if sentinel in decoded:
                return decoded
        return raw.decode(errors="replace").replace("\r\n", "\n")

    def _drain(self, seconds: float) -> str:
        deadline = time.monotonic() + seconds
        raw = b""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ready, _, _ = select.select([self._master], [], [], remaining)
            if not ready:
                continue
            try:
                data = os.read(self._master, 65536)
            except OSError:
                break
            if not data:
                break
            raw += data
        return raw.decode(errors="replace").replace("\r\n", "\n")

    def close(self) -> None:
        """Tear the shell down, always — even on error.

        Closing stdin sends EOF, so a shell idle between steps exits on its own,
        cleanly and without a signal. Only if it is still running (e.g. blocked in
        a foreground command after a step timed out) do we SIGKILL its whole
        process group, mirroring ``run_command``'s finally discipline.
        """
        if self._stdin != -1:
            with contextlib.suppress(OSError):
                os.close(self._stdin)
            self._stdin = -1
        if self._proc is not None:
            try:
                self._proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    self._proc.wait(timeout=5.0)
            self._proc = None
        if self._master != -1:
            with contextlib.suppress(OSError):
                os.close(self._master)
            self._master = -1


def run_session_steps(
    steps: list[SessionStep],
    clear_between: bool,
    cwd: str | None,
    cols: int,
    rows: int = 30,
    scrub: list[ScrubRule] | None = None,
    timeout: float = _STEP_TIMEOUT,
) -> list[str]:
    """Run ``steps`` in one persistent shell; return the terminal-card TEXT per step.

    Each card is the synthetic prompt ``$ <command>`` followed by the command's
    output. With effective clear (``step.clear`` if set, else ``clear_between``)
    True the card shows only the current step; otherwise it shows the cumulative
    transcript of every step since the last clear. ``scrub`` rules are applied to
    each card's text before it is returned (rendered style only). Two runs of the
    same steps produce byte-identical cards. Raises ``RuntimeError`` (naming the
    step and command) if a step does not finish within ``timeout`` seconds.
    """
    rules = scrub or []
    session = _PtySession(cwd, cols, rows)
    session.start()
    cards: list[str] = []
    accumulated: list[str] = []
    try:
        for index, step in enumerate(steps):
            effective_clear = step.clear if step.clear is not None else clear_between
            output = session.run_step(step.name, step.command, step.wait_ms, index, timeout)
            block = f"$ {step.command}\n{output}"
            if effective_clear:
                accumulated = [block]
            else:
                accumulated.append(block)
            text = "".join(accumulated)
            for rule in rules:
                text = re.sub(rule.pattern, rule.replace, text)
            cards.append(text)
    finally:
        session.close()
    return cards


def capture_cli_session(page: Page, shot: SessionShot, cwd: str | None = None) -> list[bytes]:
    """Run a session's steps in one persistent shell and return one PNG per step.

    ``cwd`` overrides ``shot.cwd`` when given (the engine passes the working
    directory resolved relative to the repo root). Each step's transcript is
    rendered through the same terminal-card pipeline as :func:`capture_cli`, so the
    embedded JetBrains Mono keeps the shots byte-identical on macOS and Linux CI.
    """
    working_dir = cwd if cwd is not None else shot.cwd
    texts = run_session_steps(
        shot.steps, shot.clear_between, working_dir, shot.cols, shot.rows, shot.scrub
    )
    images: list[bytes] = []
    for text in texts:
        page.set_content(terminal_html(ansi_to_html(text), shot.cols))
        images.append(page.locator(".frame").screenshot())
    return images
