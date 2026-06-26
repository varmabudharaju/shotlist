import hashlib
import json
from pathlib import Path

from shotlist.output import CaptureResult
from shotlist.report import (
    SCHEMA_VERSION,
    RunReport,
    build_manifest,
    render_gallery,
    write_report,
)


def _result(
    target: Path,
    index: int,
    name: str,
    kind: str,
    alt: str,
    data: bytes,
    deterministic: bool = True,
) -> CaptureResult:
    """A CaptureResult backed by a real PNG file inside ``target``."""
    target.mkdir(parents=True, exist_ok=True)
    filename = f"{index:02d}-{name}.png"
    path = target / filename
    path.write_bytes(data)
    return CaptureResult(
        name=name,
        path=path,
        src=f"docs/{filename}",
        alt=alt,
        kind=kind,
        deterministic=deterministic,
    )


def test_build_manifest_describes_each_shot(tmp_path: Path) -> None:
    data1, data2 = b"x" * 10, b"y" * 20
    r1 = _result(tmp_path, 1, "home", "web", "the home page", data1)
    r2 = _result(tmp_path, 2, "help", "cli", "help output", data2)

    manifest = build_manifest(
        [r1, r2], generated_at="2026-06-25T00:00:00Z", config=".shotlist.yaml"
    )

    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["generated_at"] == "2026-06-25T00:00:00Z"
    assert manifest["config"] == ".shotlist.yaml"
    assert manifest["shot_count"] == 2
    assert manifest["shots"][0] == {
        "index": 1,
        "name": "home",
        "kind": "web",
        "alt": "the home page",
        "file": "01-home.png",
        "bytes": 10,
        "sha256": hashlib.sha256(data1).hexdigest(),
        "deterministic": True,
    }
    assert manifest["shots"][1]["sha256"] == hashlib.sha256(data2).hexdigest()


def test_build_manifest_records_determinism(tmp_path: Path) -> None:
    r = _result(tmp_path, 1, "term", "cli", "a real terminal", b"data", deterministic=False)

    manifest = build_manifest([r], generated_at="t", config="c")

    assert manifest["shots"][0]["deterministic"] is False


def test_render_gallery_lists_every_shot(tmp_path: Path) -> None:
    r1 = _result(tmp_path, 1, "home", "web", "the home page", b"x" * 10)
    r2 = _result(tmp_path, 2, "help", "cli", "help output", b"y" * 20)

    out = render_gallery([r1, r2], generated_at="2026-06-25T00:00:00Z")

    assert "the home page" in out
    assert "help output" in out
    assert 'src="01-home.png"' in out
    assert 'src="02-help.png"' in out
    assert "2026-06-25T00:00:00Z" in out
    assert "2 shots" in out


def test_render_gallery_escapes_user_text(tmp_path: Path) -> None:
    r = _result(tmp_path, 1, "x", "web", '<script>alert(1)</script> "&', b"z")

    out = render_gallery([r], generated_at="t")

    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "&amp;" in out


def test_write_report_writes_manifest_and_gallery(tmp_path: Path) -> None:
    target = tmp_path / "out"
    r1 = _result(target, 1, "home", "web", "the home page", b"x" * 10)

    report = write_report([r1], target, generated_at="t", config="c")

    assert isinstance(report, RunReport)
    assert report.manifest_path == target / "manifest.json"
    assert report.gallery_path == target / "index.html"
    assert report.manifest_path.exists()
    assert report.gallery_path.exists()

    loaded = json.loads(report.manifest_path.read_text())
    assert loaded == build_manifest([r1], generated_at="t", config="c")
