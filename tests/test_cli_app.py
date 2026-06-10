"""End-to-end tests for the Typer CLI via ``CliRunner``."""

import threading
from pathlib import Path

from typer.testing import CliRunner, Result

from capture import config as config_module
from capture.cli import app

runner = CliRunner()


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


def test_run_single_cli_shot(tmp_path: Path) -> None:
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
