"""Capture a *real* macOS Terminal window — an authentic screenshot.

Unlike the rendered CLI backend (which recreates output as styled HTML), this
drives the actual Terminal.app via AppleScript: open a window, size it, run the
command after a ``clear``, wait for it to finish, then ``screencapture`` the live
window and close it — all atomically so nothing can slide in front mid-capture.

Requires macOS and Screen-Recording permission for the controlling terminal
(System Settings → Privacy & Security → Screen Recording).
"""

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
        set b to bounds of w
        set x to item 1 of b
        set y to item 2 of b
        set wd to (item 3 of b) - x
        set ht to (item 4 of b) - y
        set theRegion to ("" & x & "," & y & "," & wd & "," & ht)
        do shell script "screencapture -x -R" & theRegion & " " & quoted form of outPath
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
