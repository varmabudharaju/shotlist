"""End-to-end tests for the Typer CLI via ``CliRunner``."""

import io
import json
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from typer.testing import CliRunner, Result

from shotlist import config as config_module
from shotlist.cli import app

runner = CliRunner()


def _fake_terminal(command: str, cwd: str, cols: int, rows: int) -> bytes:
    """Stand in for the real Terminal screenshot so the CLI test needs no GUI."""
    return b"\x89PNG\r\n\x1a\nX"


def _png(color: tuple[int, int, int]) -> bytes:
    """A real PNG of a solid color (the diff backend must be able to open it)."""
    buf = io.BytesIO()
    Image.new("RGB", (12, 12), color).save(buf, "PNG")
    return buf.getvalue()


def _png_flipped(flipped: int) -> bytes:
    """A 12x12 black PNG with ``flipped`` white pixels (of 144 total)."""
    image = Image.new("RGB", (12, 12), (0, 0, 0))
    for i in range(flipped):
        image.putpixel((i % 12, i // 12), (255, 255, 255))
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


def invoke_run(args: list[str]) -> Result:
    """Invoke the CLI on a worker thread so ``engine.run`` gets a clean loop.

    The session-scoped ``browser`` fixture keeps a ``sync_playwright`` loop alive
    for the whole suite; running the engine on the main thread would trip its
    nesting guard. A fresh thread has no running event loop, so the sync
    Playwright API used by ``shotlist run`` works there.
    """
    result: list[Result] = []

    def target() -> None:
        result.append(runner.invoke(app, args))

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    return result[0]


def test_init_creates_loadable_config(tmp_path: Path) -> None:
    target = tmp_path / ".shotlist.yaml"
    result = runner.invoke(app, ["init", "--path", str(target)])

    assert result.exit_code == 0, result.output
    assert target.exists()
    # The generated starter must be a valid shot list.
    cfg = config_module.load(target)
    assert len(cfg.shots) >= 1


def test_init_refuses_existing_without_force(tmp_path: Path) -> None:
    target = tmp_path / ".shotlist.yaml"
    target.write_text("shots: []\n")

    result = runner.invoke(app, ["init", "--path", str(target)])
    assert result.exit_code == 1
    # The original file is untouched.
    assert target.read_text() == "shots: []\n"


def test_init_force_overwrites(tmp_path: Path) -> None:
    target = tmp_path / ".shotlist.yaml"
    target.write_text("shots: []\n")

    result = runner.invoke(app, ["init", "--path", str(target), "--force"])
    assert result.exit_code == 0, result.output
    cfg = config_module.load(target)
    assert len(cfg.shots) >= 1


def test_validate_good_file(tmp_path: Path) -> None:
    target = tmp_path / ".shotlist.yaml"
    runner.invoke(app, ["init", "--path", str(target)])

    result = runner.invoke(app, ["validate", "--config", str(target)])
    assert result.exit_code == 0, result.output
    assert "valid" in result.output


def test_validate_bad_file(tmp_path: Path) -> None:
    target = tmp_path / ".shotlist.yaml"
    target.write_text("not: a valid shot list\n")

    result = runner.invoke(app, ["validate", "--config", str(target)])
    assert result.exit_code != 0


def test_run_single_cli_shot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    target = tmp_path / ".shotlist.yaml"
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
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    target = tmp_path / ".shotlist.yaml"
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
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    target = tmp_path / ".shotlist.yaml"
    target.write_text(_NATIVE_CONFIG)

    result = invoke_run(["check", "--config", str(target)])
    assert result.exit_code != 0
    assert "baseline" in result.output.lower()


def test_check_update_then_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    target = tmp_path / ".shotlist.yaml"
    target.write_text(_NATIVE_CONFIG)

    upd = invoke_run(["check", "--update", "--config", str(target)])
    assert upd.exit_code == 0, upd.output
    assert (tmp_path / "shots" / "manifest.json").exists()

    # The native shot can't be compared, so check is clean (skipped, not drift).
    chk = invoke_run(["check", "--config", str(target)])
    assert chk.exit_code == 0, chk.output


def test_check_detects_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    box = {"data": b"\x89PNG\r\n\x1a\nA"}
    monkeypatch.setattr("shotlist.engine.capture_web", lambda page, shot: box["data"])
    target = tmp_path / ".shotlist.yaml"
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
    monkeypatch.setattr("shotlist.engine.capture_web", lambda page, shot: box["data"])
    target = tmp_path / ".shotlist.yaml"
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
    assert (diff_dir / "check-report.html").exists()
    # The report lists every shot with its status badge.
    report = (diff_dir / "check-report.html").read_text()
    assert "home" in report
    assert "changed" in report


_WEB_CONFIG = (
    "output:\n  dir: shots\n"
    "shots:\n  - name: home\n    kind: web\n    url: http://localhost/\n"
)


def _tolerant_config(ratio: float) -> str:
    return (
        "output:\n  dir: shots\n"
        f"check:\n  max_diff_pixel_ratio: {ratio}\n"
        "shots:\n  - name: home\n    kind: web\n    url: http://localhost/\n"
    )


def _manifest(tmp_path: Path) -> Any:
    return json.loads((tmp_path / "shots" / "manifest.json").read_text())


def test_check_tolerance_absorbs_small_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 5% budget; baseline all-black, current flips 3/144 pixels (~2%) → no drift.
    box = {"data": _png_flipped(0)}
    monkeypatch.setattr("shotlist.engine.capture_web", lambda page, shot: box["data"])
    target = tmp_path / ".shotlist.yaml"
    target.write_text(_tolerant_config(0.05))

    assert invoke_run(["check", "--update", "--config", str(target)]).exit_code == 0
    box["data"] = _png_flipped(3)
    within = invoke_run(["check", "--config", str(target)])
    assert within.exit_code == 0, within.output
    assert "within tolerance" in within.output

    # A larger change (20/144 ~ 14%) exceeds the budget → drift.
    box["data"] = _png_flipped(20)
    over = invoke_run(["check", "--config", str(target)])
    assert over.exit_code != 0, over.output
    assert "pixels differ" in over.output


def test_check_json_emits_contract_b(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    box = {"data": _png_flipped(0)}
    monkeypatch.setattr("shotlist.engine.capture_web", lambda page, shot: box["data"])
    target = tmp_path / ".shotlist.yaml"
    target.write_text(_tolerant_config(0.01))

    assert invoke_run(["check", "--update", "--config", str(target)]).exit_code == 0
    box["data"] = _png_flipped(20)  # ~14% > 1% budget → drift with computed ratio
    diff_dir = tmp_path / "diffs"
    result = invoke_run(["check", "--config", str(target), "--json", "--diff", str(diff_dir)])

    assert result.exit_code != 0, result.output
    payload = json.loads(result.output.strip())  # stdout is ONLY the JSON document
    assert payload["drifted"] is True
    assert payload["environment_mismatch"] == []
    shot = payload["shots"][0]
    assert shot["name"] == "home"
    assert shot["status"] == "changed"
    assert shot["changed_pixel_ratio"] is not None
    assert shot["changed_pixel_ratio"] > 0.01
    assert shot["diff_file"] == "home.diff.png"


def test_check_json_ratio_null_on_exact_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Default (exact) mode never decodes pixels → changed_pixel_ratio is null.
    box = {"data": b"\x89PNG\r\n\x1a\nA"}
    monkeypatch.setattr("shotlist.engine.capture_web", lambda page, shot: box["data"])
    target = tmp_path / ".shotlist.yaml"
    target.write_text(_WEB_CONFIG)

    assert invoke_run(["check", "--update", "--config", str(target)]).exit_code == 0
    box["data"] = b"\x89PNG\r\n\x1a\nB"
    result = invoke_run(["check", "--config", str(target), "--json"])

    assert result.exit_code != 0
    payload = json.loads(result.output.strip())
    assert payload["shots"][0]["changed_pixel_ratio"] is None
    assert payload["shots"][0]["diff_file"] is None


def test_check_update_only_reblesses_named_shot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = {"home": _png((0, 0, 0)), "about": _png((0, 0, 0))}
    monkeypatch.setattr("shotlist.engine.capture_web", lambda page, shot: frames[shot.name])
    target = tmp_path / ".shotlist.yaml"
    target.write_text(
        "output:\n  dir: shots\n"
        "shots:\n"
        "  - name: home\n    kind: web\n    url: http://localhost/a\n"
        "  - name: about\n    kind: web\n    url: http://localhost/b\n"
    )

    assert invoke_run(["check", "--update", "--config", str(target)]).exit_code == 0
    before = {s["name"]: s["sha256"] for s in _manifest(tmp_path)["shots"]}
    # Inject an unknown top-level key that selective update must preserve.
    manifest_path = tmp_path / "shots" / "manifest.json"
    doc = json.loads(manifest_path.read_text())
    doc["environment"] = {"chromium": "126.0"}
    manifest_path.write_text(json.dumps(doc))

    # Both shots now render differently, but re-bless only `home`.
    frames["home"] = _png((255, 0, 0))
    frames["about"] = _png((0, 0, 255))
    upd = invoke_run(["check", "--update", "--only", "home", "--config", str(target)])
    assert upd.exit_code == 0, upd.output

    after = {s["name"]: s["sha256"] for s in _manifest(tmp_path)["shots"]}
    assert after["home"] != before["home"]  # home re-blessed
    assert after["about"] == before["about"]  # about untouched
    # Original numbering + unknown keys preserved.
    files = {s["name"]: s["file"] for s in _manifest(tmp_path)["shots"]}
    assert files == {"home": "01-home.png", "about": "02-about.png"}
    assert _manifest(tmp_path)["environment"] == {"chromium": "126.0"}

    # A plain check now: home matches, about still drifts.
    chk = invoke_run(["check", "--config", str(target)])
    assert chk.exit_code != 0, chk.output
    assert "about" in chk.output


def test_check_update_only_rejects_native_shot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    target = tmp_path / ".shotlist.yaml"
    target.write_text(_NATIVE_CONFIG)

    assert invoke_run(["check", "--update", "--config", str(target)]).exit_code == 0
    result = invoke_run(["check", "--update", "--only", "greet", "--config", str(target)])
    assert result.exit_code != 0
    assert "greet" in result.output


def test_check_only_without_update_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shotlist.engine.capture_terminal", _fake_terminal)
    target = tmp_path / ".shotlist.yaml"
    target.write_text(_NATIVE_CONFIG)

    result = invoke_run(["check", "--only", "greet", "--config", str(target)])
    assert result.exit_code != 0


def _write_native_baseline(tmp_path: Path, environment: Mapping[str, object]) -> Path:
    """A hand-crafted baseline for a native (non-deterministic) shot + env block.

    A native shot is never recaptured by check, so no browser is launched and the
    environment comparison can be exercised in isolation.
    """
    shots_dir = tmp_path / "shots"
    shots_dir.mkdir()
    (shots_dir / "01-greet.png").write_bytes(b"\x89PNG\r\n\x1a\nX")
    manifest = {
        "schema_version": "1",
        "generated_at": "t",
        "config": "c",
        "shot_count": 1,
        "shots": [
            {
                "index": 1,
                "name": "greet",
                "kind": "cli",
                "alt": "",
                "file": "01-greet.png",
                "bytes": 1,
                "sha256": "deadbeef",
                "deterministic": False,
            }
        ],
        "environment": environment,
    }
    (shots_dir / "manifest.json").write_text(json.dumps(manifest))
    target = tmp_path / ".shotlist.yaml"
    target.write_text(_NATIVE_CONFIG)
    return target


def test_check_warns_on_environment_mismatch(tmp_path: Path) -> None:
    target = _write_native_baseline(tmp_path, {"python": "0.0.0", "chromium": None})

    result = runner.invoke(app, ["check", "--config", str(target)])

    assert result.exit_code == 0, result.output  # native shot skipped → no shot drift
    assert "environment: python 0.0.0 ->" in result.output


def test_check_environment_chromium_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shotlist.cli._chromium_version", lambda: "131.0")
    target = _write_native_baseline(tmp_path, {"chromium": "126.0"})

    result = runner.invoke(app, ["check", "--config", str(target)])

    assert result.exit_code == 0, result.output
    assert "environment: chromium 126.0 -> 131.0" in result.output


def test_check_json_reports_environment_mismatch(tmp_path: Path) -> None:
    target = _write_native_baseline(tmp_path, {"python": "0.0.0", "chromium": None})

    result = runner.invoke(app, ["check", "--config", str(target), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip())
    assert any(entry.startswith("python: 0.0.0 ->") for entry in payload["environment_mismatch"])
