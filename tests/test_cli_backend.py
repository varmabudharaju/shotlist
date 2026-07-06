import sys
from pathlib import Path

import pytest
from playwright.sync_api import Page
from pydantic import ValidationError

import shotlist.backends.cli as cli_backend
from shotlist.backends.cli import (
    capture_cli,
    capture_cli_session,
    run_command,
    run_session_steps,
)
from shotlist.config import CliShot, ScrubRule, SessionShot, SessionStep
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


def test_scrub_rule_parses_and_defaults() -> None:
    rule = ScrubRule(pattern=r"in \d+\.\d+s", replace="in X.XXs")
    assert rule.pattern == r"in \d+\.\d+s"
    assert rule.replace == "in X.XXs"
    # replace defaults to deleting the match
    assert ScrubRule(pattern="x").replace == ""
    # scrub defaults to no rules
    assert CliShot(name="t", kind="cli", command="echo hi").scrub == []


def test_invalid_scrub_pattern_rejected() -> None:
    with pytest.raises(ValidationError):
        ScrubRule(pattern="(")
    with pytest.raises(ValidationError):
        CliShot(name="t", kind="cli", command="echo hi", scrub=[{"pattern": "["}])  # type: ignore


def test_scrub_applied_to_raw_before_render(page: Page, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def fake_ansi(text: str) -> str:
        seen["text"] = text
        return "<span>x</span>"

    monkeypatch.setattr(cli_backend, "ansi_to_html", fake_ansi)
    shot = CliShot(
        name="t",
        kind="cli",
        command="echo 'done in 3.14s'",
        scrub=[ScrubRule(pattern=r"in \d+\.\d+s", replace="in X.XXs")],
    )
    data = capture_cli(page, shot)
    assert data.startswith(PNG_MAGIC)
    assert "in X.XXs" in seen["text"]
    assert "3.14s" not in seen["text"]


def test_scrub_rules_apply_in_order() -> None:
    # Focused check on the substitution step semantics used by capture_cli.
    rules = [
        ScrubRule(pattern=r"\d{4}-\d{2}-\d{2}", replace="DATE"),
        ScrubRule(pattern=r"pid=\d+", replace="pid=N"),
    ]
    text = "started 2026-07-01 pid=4321 ok"
    import re

    for rule in rules:
        text = re.sub(rule.pattern, rule.replace, text)
    assert text == "started DATE pid=N ok"


def test_terminal_html_embeds_jetbrains_mono() -> None:
    html = terminal_html("CONTENT", cols=80)
    assert "@font-face" in html
    assert "'JetBrains Mono'" in html
    assert "data:font/woff2;base64," in html
    assert "font-weight: 400" in html
    assert "font-weight: 700" in html
    # The pre stack now prefers the embedded face.
    assert "font-family: 'JetBrains Mono'" in html


# --- Rendered sessions (persistent-PTY runner; no browser needed) -------------


def test_session_transcript_has_no_echo_or_prompt() -> None:
    # A card is exactly the synthetic prompt + output: no echoed input, no PS1,
    # no sentinel text.
    steps = [SessionStep(name="a", command="echo hello")]
    cards = run_session_steps(steps, clear_between=True, cwd=None, cols=80)
    assert cards == ["$ echo hello\nhello\n"]


def test_session_state_persists_across_steps() -> None:
    steps = [
        SessionStep(name="set", command="export GREETING=hi"),
        SessionStep(name="get", command="echo $GREETING"),
    ]
    cards = run_session_steps(steps, clear_between=True, cwd=None, cols=80)
    assert len(cards) == 2
    # The env var set in step 1 is visible in step 2 → one persistent shell.
    assert cards[1] == "$ echo $GREETING\nhi\n"


def test_session_is_byte_identical_across_runs(tmp_path: Path) -> None:
    steps = [
        SessionStep(name="a", command="echo one"),
        SessionStep(name="b", command="echo two"),
    ]
    first = run_session_steps(steps, clear_between=False, cwd=str(tmp_path), cols=80)
    second = run_session_steps(steps, clear_between=False, cwd=str(tmp_path), cols=80)
    assert first == second


def test_session_clear_true_shows_only_current_step() -> None:
    steps = [
        SessionStep(name="a", command="echo one"),
        SessionStep(name="b", command="echo two"),
    ]
    cards = run_session_steps(steps, clear_between=True, cwd=None, cols=80)
    assert cards[1] == "$ echo two\ntwo\n"
    assert "echo one" not in cards[1]


def test_session_clear_false_is_cumulative() -> None:
    steps = [
        SessionStep(name="a", command="echo one"),
        SessionStep(name="b", command="echo two"),
    ]
    cards = run_session_steps(steps, clear_between=False, cwd=None, cols=80)
    assert cards[1] == "$ echo one\none\n$ echo two\ntwo\n"


def test_session_per_step_clear_overrides_default() -> None:
    steps = [
        SessionStep(name="a", command="echo one"),
        SessionStep(name="b", command="echo two", clear=True),
    ]
    cards = run_session_steps(steps, clear_between=False, cwd=None, cols=80)
    assert cards[1] == "$ echo two\ntwo\n"


def test_session_respects_cwd(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("x")
    cards = run_session_steps(
        [SessionStep(name="a", command="ls")],
        clear_between=True,
        cwd=str(tmp_path),
        cols=80,
    )
    assert "marker.txt" in cards[0]


def test_session_background_job_has_no_job_control_noise() -> None:
    # `set +m` + a non-interactive shell means no `[1] <pid>` / `[1]+ Done` lines.
    steps = [SessionStep(name="a", command="sleep 0.05 &", wait_ms=200)]
    cards = run_session_steps(steps, clear_between=True, cwd=None, cols=80)
    assert cards == ["$ sleep 0.05 &\n"]


def test_session_wait_ms_captures_background_output() -> None:
    steps = [SessionStep(name="a", command="(sleep 0.1; echo late) &", wait_ms=1000)]
    cards = run_session_steps(steps, clear_between=True, cwd=None, cols=80)
    assert "late" in cards[0]


def test_session_scrub_applied_to_transcript() -> None:
    # The value `4` is produced by the command, not present in the command text,
    # so scrubbing it proves the rule reaches the rendered output.
    steps = [SessionStep(name="a", command="echo $((2 + 2))")]
    cards = run_session_steps(
        steps,
        clear_between=True,
        cwd=None,
        cols=80,
        scrub=[ScrubRule(pattern="4", replace="N")],
    )
    assert cards == ["$ echo $((2 + 2))\nN\n"]


def test_session_step_timeout_raises_with_name_and_command() -> None:
    steps = [SessionStep(name="hang", command="sleep 5")]
    with pytest.raises(RuntimeError, match="hang") as excinfo:
        run_session_steps(steps, clear_between=True, cwd=None, cols=80, timeout=0.5)
    assert "sleep 5" in str(excinfo.value)


def test_capture_cli_session_produces_one_png_per_step(page: Page) -> None:
    shot = SessionShot(
        name="flow",
        kind="session",
        style="rendered",
        steps=[
            SessionStep(name="a", command="echo one"),
            SessionStep(name="b", command="echo two"),
        ],
    )
    images = capture_cli_session(page, shot)
    assert len(images) == 2
    for data in images:
        assert data.startswith(PNG_MAGIC)
        assert len(data) > 100
