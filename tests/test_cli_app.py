"""End-to-end tests for the Typer CLI via ``CliRunner``."""

import io
import threading
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner, Result

from capture import config as config_module
from capture.cli import app

runner = CliRunner()


def _fake_terminal(command: str, cwd: str, cols: int, rows: int) -> bytes:
    """Stand in for the real Terminal screenshot so the CLI test needs no GUI."""
    return b"\x89PNG\r\n\x1a\nX"


def _png(color: tuple[int, int, int]) -> bytes:
    """A real PNG of a solid color (the diff backend must be able to open it)."""
    buf = io.BytesIO()
    Image.new("RGB", (12, 12), color).save(buf, "PNG")
    return buf.getvalue()


def invoke_run(args: list[str]) -> Result:
    """Invoke the CLI on a worker thread so ``engine.run`` gets a clean loop.

    The session-scoped ``browser`` fixture keeps a ``sync_playwright`` loop alive
    for the whole suite; running the engine on the main thread would trip its
    nesting guard. A fresh thread has no running event loop, so the sync
    Playwright API used by ``capture run`` works there.
    """
    result: list[Result] = []

    def target() -> None:
        result.append(runner.invoke(app, args))

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    return result[0]


def test_init_creates_loadable_config(tmp_path: Path) -> None:
    target = tmp_path / ".capture.yaml"
    result = runner.invoke(app, ["init", "--path", str(target)])

    assert result.exit_code == 0, result.output
    assert target.exists()
    # The generated starter must be a valid shot list.
    cfg = config_module.load(target)
    assert len(cfg.shots) >= 1


def test_init_refuses_existing_without_force(tmp_path: Path) -> None:
    target = tmp_path / ".capture.yaml"
    target.write_text("shots: []\n")

    result = runner.invoke(app, ["init", "--path", str(target)])
    assert result.exit_code == 1
    # The original file is untouched.
    assert target.read_text() == "shots: []\n"


def test_init_force_overwrites(tmp_path: Path) -> None:
    target = tmp_path / ".capture.yaml"
    target.write_text("shots: []\n")

    result = runner.invoke(app, ["init", "--path", str(target), "--force"])
    assert result.exit_code == 0, result.output
    cfg = config_module.load(target)
    assert len(cfg.shots) >= 1


def test_validate_good_file(tmp_path: Path) -> None:
    target = tmp_path / ".capture.yaml"
    runner.invoke(app, ["init", "--path", str(target)])

    result = runner.invoke(app, ["validate", "--config", str(target)])
    assert result.exit_code == 0, result.output
    assert "valid" in result.output


def test_validate_bad_file(tmp_path: Path) -> None:
    target = tmp_path / ".capture.yaml"
    target.write_text("not: a valid shot list\n")

    result = runner.invoke(app, ["validate", "--config", str(target)])
    assert result.exit_code != 0


def test_run_single_cli_shot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("capture.engine.capture_terminal", _fake_terminal)
    target = tmp_path / ".capture.yaml"
    target.write_text(
        "output:\n"
        "  dir: shots\n"
        "shots:\n"
        "  - name: greet\n"
        "    kind: cli\n"
        "    command: echo hello\n"
    )

    result = invoke_run(["run", "--config", str(target)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "shots" / "01-greet.png").exists()
    assert "captured 1 shot(s)" in result.output
    # The report (manifest + gallery) is written by default.
    assert (tmp_path / "shots" / "manifest.json").exists()
    assert (tmp_path / "shots" / "index.html").exists()


def test_run_no_report_suppresses_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("capture.engine.capture_terminal", _fake_terminal)
    target = tmp_path / ".capture.yaml"
    target.write_text(
        "output:\n"
        "  dir: shots\n"
        "shots:\n"
        "  - name: greet\n"
        "    kind: cli\n"
        "    command: echo hello\n"
    )

    result = invoke_run(["run", "--config", str(target), "--no-report"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "shots" / "01-greet.png").exists()
    assert not (tmp_path / "shots" / "manifest.json").exists()
    assert not (tmp_path / "shots" / "index.html").exists()


_NATIVE_CONFIG = (
    "output:\n"
    "  dir: shots\n"
    "shots:\n"
    "  - name: greet\n"
    "    kind: cli\n"
    "    command: echo hi\n"
    "    style: native\n"
)


def test_check_errors_without_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("capture.engine.capture_terminal", _fake_terminal)
    target = tmp_path / ".capture.yaml"
    target.write_text(_NATIVE_CONFIG)

    result = invoke_run(["check", "--config", str(target)])
    assert result.exit_code != 0
    assert "baseline" in result.output.lower()


def test_check_update_then_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("capture.engine.capture_terminal", _fake_terminal)
    target = tmp_path / ".capture.yaml"
    target.write_text(_NATIVE_CONFIG)

    upd = invoke_run(["check", "--update", "--config", str(target)])
    assert upd.exit_code == 0, upd.output
    assert (tmp_path / "shots" / "manifest.json").exists()

    # The native shot can't be compared, so check is clean (skipped, not drift).
    chk = invoke_run(["check", "--config", str(target)])
    assert chk.exit_code == 0, chk.output


def test_check_detects_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    box = {"data": b"\x89PNG\r\n\x1a\nA"}
    monkeypatch.setattr("capture.engine.capture_web", lambda page, shot: box["data"])
    target = tmp_path / ".capture.yaml"
    target.write_text(
        "output:\n  dir: shots\n"
        "shots:\n  - name: home\n    kind: web\n    url: http://localhost/\n"
    )

    assert invoke_run(["check", "--update", "--config", str(target)]).exit_code == 0
    # Same bytes → no drift.
    assert invoke_run(["check", "--config", str(target)]).exit_code == 0
    # The page "changes" → drift → non-zero exit.
    box["data"] = b"\x89PNG\r\n\x1a\nB"
    drifted = invoke_run(["check", "--config", str(target)])
    assert drifted.exit_code != 0, drifted.output


def test_check_diff_writes_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    box = {"data": _png((255, 0, 0))}
    monkeypatch.setattr("capture.engine.capture_web", lambda page, shot: box["data"])
    target = tmp_path / ".capture.yaml"
    target.write_text(
        "output:\n  dir: shots\n"
        "shots:\n  - name: home\n    kind: web\n    url: http://localhost/\n"
    )

    assert invoke_run(["check", "--update", "--config", str(target)]).exit_code == 0

    # The page changes to a different color → drift, with a visual diff written.
    box["data"] = _png((0, 0, 255))
    diff_dir = tmp_path / "capture-diffs"
    result = invoke_run(["check", "--config", str(target), "--diff", str(diff_dir)])

    assert result.exit_code != 0, result.output
    assert (diff_dir / "home.diff.png").exists()
    assert (diff_dir / "diff.html").exists()
