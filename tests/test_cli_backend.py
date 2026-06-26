import sys
from pathlib import Path

from playwright.sync_api import Page

from shotlist.backends.cli import capture_cli, run_command
from shotlist.config import CliShot
from shotlist.render import ansi_to_html, terminal_html
from tests.conftest import PNG_MAGIC


def test_run_command_captures_stdout() -> None:
    out = run_command("echo hello-world", cwd=None, cols=80)
    assert "hello-world" in out


def test_run_command_respects_cwd(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("x")
    out = run_command("ls", cwd=str(tmp_path), cols=80)
    assert "marker.txt" in out


def test_run_command_times_out() -> None:
    # A command that would hang forever must be killed by the timeout.
    out = run_command(
        f"{sys.executable} -c 'import time; time.sleep(30)'",
        cwd=None,
        cols=80,
        timeout=1.0,
    )
    assert isinstance(out, str)


def test_ansi_to_html_keeps_text_and_adds_color() -> None:
    html = ansi_to_html("\x1b[31mRED\x1b[0m plain")
    assert "RED" in html
    assert "plain" in html
    assert "color" in html.lower()


def test_ansi_to_html_escapes_markup() -> None:
    html = ansi_to_html("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_terminal_html_wraps_body() -> None:
    html = terminal_html("CONTENT", cols=80)
    assert "CONTENT" in html
    assert "min-width: 80ch" in html
    assert "term" in html


def test_capture_cli_produces_png(page: Page) -> None:
    shot = CliShot(name="t", kind="cli", command="echo hello")
    data = capture_cli(page, shot)
    assert data.startswith(PNG_MAGIC)
    assert len(data) > 100


def test_capture_cli_with_color(page: Page) -> None:
    code = "import sys; sys.stdout.write('\\x1b[32mGREEN\\x1b[0m\\n')"
    shot = CliShot(name="t", kind="cli", command=f"{sys.executable} -c \"{code}\"")
    data = capture_cli(page, shot)
    assert data.startswith(PNG_MAGIC)
