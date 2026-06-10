"""Capture a *real* macOS Terminal window — an authentic screenshot.

Unlike the rendered CLI backend (which recreates output as styled HTML), this
drives the actual Terminal.app via AppleScript: open a window, size it, run the
command after a ``clear``, wait for it to finish, then ``screencapture`` the live
window and close it — all atomically so nothing can slide in front mid-capture.

Requires macOS and Screen-Recording permission for the controlling terminal
(System Settings → Privacy & Security → Screen Recording).
"""

import contextlib
import subprocess
import sys
import tempfile
from pathlib import Path

# AppleScript args: cwd, command, cols, rows, out_path
_APPLESCRIPT = r'''on run argv
    set theCwd to item 1 of argv
    set theCmd to item 2 of argv
    set theCols to (item 3 of argv) as integer
    set theRows to (item 4 of argv) as integer
    set outPath to item 5 of argv
    tell application "Terminal"
        activate
        set t to do script ""
        delay 0.4
        set w to front window
        set number of columns of w to theCols
        set number of rows of w to theRows
        delay 0.2
        do script ("cd " & quoted form of theCwd & " && clear && " & theCmd) in t
        delay 0.4
        set tries to 0
        repeat while (busy of t) and (tries < 600)
            delay 0.2
            set tries to tries + 1
        end repeat
        delay 0.5
        -- Capture by WINDOW ID, not screen region: a region grab photographs whatever
        -- pixels are stacked on top (e.g. the user's own frontmost terminal), leaking
        -- unrelated window content into the shot. -l targets this window regardless of
        -- stacking and doesn't require it to be frontmost.
        set wid to id of w
        do shell script "screencapture -x -o -l " & wid & " " & quoted form of outPath
        close w saving no
    end tell
end run
'''


class NativeCaptureError(RuntimeError):
    """Raised when a real Terminal capture cannot be performed."""


def capture_terminal(
    command: str,
    cwd: str,
    cols: int,
    rows: int,
    timeout: float = 120.0,
) -> bytes:
    """Run ``command`` in a real Terminal window and return PNG bytes of it."""
    if sys.platform != "darwin":
        raise NativeCaptureError(
            "native terminal capture requires macOS; set 'style: rendered' on this platform"
        )
    with tempfile.TemporaryDirectory() as tmp:
        script_path = Path(tmp) / "capture.applescript"
        out_path = Path(tmp) / "shot.png"
        script_path.write_text(_APPLESCRIPT)
        try:
            subprocess.run(
                [
                    "osascript",
                    str(script_path),
                    cwd,
                    command,
                    str(cols),
                    str(rows),
                    str(out_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.CalledProcessError as exc:
            raise NativeCaptureError(
                "Terminal capture failed. Grant Screen Recording permission to your "
                "terminal in System Settings → Privacy & Security → Screen Recording, "
                f"then retry.\n{exc.stderr.strip()}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise NativeCaptureError(
                f"Terminal capture timed out after {timeout:.0f}s running: {command}"
            ) from exc
        if not out_path.exists():
            raise NativeCaptureError("Terminal capture produced no image")
        return out_path.read_bytes()


# --- Persistent sessions: one window, many commands, a screenshot after each ---

# args: cwd, cols, rows  -> prints the Terminal window id
_CREATE_SCRIPT = r'''on run argv
    set theCwd to item 1 of argv
    set theCols to (item 2 of argv) as integer
    set theRows to (item 3 of argv) as integer
    tell application "Terminal"
        activate
        set t to do script ""
        delay 0.4
        set w to front window
        set number of columns of w to theCols
        set number of rows of w to theRows
        delay 0.2
        do script ("cd " & quoted form of theCwd & " && clear") in t
        delay 0.3
        return (id of w) as text
    end tell
end run
'''

# args: window_id, command, clear("1"/"0"), wait_ms, out_path
_STEP_SCRIPT = r'''on run argv
    set wid to (item 1 of argv) as integer
    set theCmd to item 2 of argv
    set doClear to (item 3 of argv) is "1"
    set waitMs to (item 4 of argv) as integer
    set outPath to item 5 of argv
    tell application "Terminal"
        set w to window id wid
        set t to selected tab of w
        if doClear then
            do script "clear" in t
            delay 0.3
        end if
        do script theCmd in t
        delay 0.3
        set tries to 0
        repeat while (busy of t) and (tries < 1500)
            delay 0.2
            set tries to tries + 1
        end repeat
        if waitMs > 0 then
            delay (waitMs / 1000)
        end if
        delay 0.3
        -- Capture by WINDOW ID (see the single-shot script): region grabs leak whatever
        -- window is stacked on top; -l hits this window even when it isn't frontmost.
        do shell script "screencapture -x -o -l " & wid & " " & quoted form of outPath
    end tell
end run
'''

# args: window_id
_CLOSE_SCRIPT = r'''on run argv
    set wid to (item 1 of argv) as integer
    tell application "Terminal" to close (window id wid) saving no
end run
'''


def _run_osascript(script_body: str, args: list[str], timeout: float) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "script.applescript"
        path.write_text(script_body)
        try:
            proc = subprocess.run(
                ["osascript", str(path), *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.CalledProcessError as exc:
            raise NativeCaptureError(
                "Terminal automation failed. Grant Screen Recording permission to your "
                "terminal in System Settings → Privacy & Security → Screen Recording.\n"
                f"{exc.stderr.strip()}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise NativeCaptureError(f"Terminal automation timed out after {timeout:.0f}s") from exc
    return proc.stdout.strip()


def _create_session(cwd: str, cols: int, rows: int) -> str:
    return _run_osascript(_CREATE_SCRIPT, [cwd, str(cols), str(rows)], timeout=60.0)


def _run_step(wid: str, command: str, clear: bool, wait_ms: int, out_path: str) -> None:
    _run_osascript(
        _STEP_SCRIPT,
        [wid, command, "1" if clear else "0", str(wait_ms), out_path],
        timeout=600.0,
    )


def _close_session(wid: str) -> None:
    _run_osascript(_CLOSE_SCRIPT, [wid], timeout=30.0)


def capture_terminal_session(
    steps: list[tuple[str, bool, int]],
    cwd: str,
    cols: int,
    rows: int,
) -> list[bytes]:
    """Run ``steps`` in one persistent Terminal window, capturing after each.

    Each step is ``(command, clear_first, wait_ms)``. The shell state persists
    across steps; the window is captured after every step and closed at the end
    (even on error). Returns one PNG per step, in order.
    """
    if sys.platform != "darwin":
        raise NativeCaptureError(
            "native terminal capture requires macOS; set 'style: rendered' on this platform"
        )
    images: list[bytes] = []
    with tempfile.TemporaryDirectory() as tmp:
        wid = _create_session(cwd, cols, rows)
        try:
            for index, (command, clear, wait_ms) in enumerate(steps):
                out_path = Path(tmp) / f"{index:03d}.png"
                _run_step(wid, command, clear, wait_ms, str(out_path))
                if not out_path.exists():
                    raise NativeCaptureError(f"no image produced for step {index + 1}")
                images.append(out_path.read_bytes())
        finally:
            with contextlib.suppress(NativeCaptureError):
                _close_session(wid)
    return images
