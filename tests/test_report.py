import hashlib
import json
import platform
import sys
from pathlib import Path

from shotlist.output import CaptureResult
from shotlist.report import (
    SCHEMA_VERSION,
    RunReport,
    build_manifest,
    collect_environment,
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
    source: str = "",
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
        source=source,
    )


def test_build_manifest_describes_each_shot(tmp_path: Path) -> None:
    data1, data2 = b"x" * 10, b"y" * 20
    r1 = _result(tmp_path, 1, "home", "web", "the home page", data1, source="http://x/")
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
        "source": "http://x/",
    }
    assert manifest["shots"][1]["sha256"] == hashlib.sha256(data2).hexdigest()


def test_build_manifest_records_source_per_shot(tmp_path: Path) -> None:
    r1 = _result(tmp_path, 1, "home", "web", "home", b"x", source="http://localhost/")
    r2 = _result(tmp_path, 2, "help", "cli", "help", b"y", source="mytool --help")

    manifest = build_manifest([r1, r2], generated_at="t", config="c")

    assert manifest["shots"][0]["source"] == "http://localhost/"
    assert manifest["shots"][1]["source"] == "mytool --help"


def test_build_manifest_stamps_environment_contract_a(tmp_path: Path) -> None:
    r = _result(tmp_path, 1, "home", "web", "home", b"x")

    manifest = build_manifest([r], generated_at="t", config="c", chromium="121.0.0")

    env = manifest["environment"]
    # Contract A: exactly these keys, in this shape.
    assert set(env) == {"shotlist", "python", "platform", "playwright", "chromium"}
    assert isinstance(env["shotlist"], str)
    assert isinstance(env["playwright"], str)
    assert env["python"] == platform.python_version()
    assert env["platform"] == sys.platform
    assert env["chromium"] == "121.0.0"


def test_build_manifest_chromium_none_when_no_browser(tmp_path: Path) -> None:
    r = _result(tmp_path, 1, "help", "cli", "help", b"x")

    manifest = build_manifest([r], generated_at="t", config="c")

    assert manifest["environment"]["chromium"] is None


def test_build_manifest_git_sha_none_without_repo_root(tmp_path: Path) -> None:
    r = _result(tmp_path, 1, "home", "web", "home", b"x")

    manifest = build_manifest([r], generated_at="t", config="c")

    # repo_root not passed -> no git lookup attempted.
    assert manifest["git_sha"] is None


def test_build_manifest_git_sha_none_outside_repo(tmp_path: Path) -> None:
    r = _result(tmp_path, 1, "home", "web", "home", b"x")

    # tmp_path is not a git repository, so the lookup fails cleanly to None.
    manifest = build_manifest([r], generated_at="t", config="c", repo_root=tmp_path)

    assert manifest["git_sha"] is None


def test_collect_environment_shape() -> None:
    env = collect_environment()

    assert set(env) == {"shotlist", "python", "platform", "playwright", "chromium"}
    assert env["chromium"] is None
    assert collect_environment("120.0")["chromium"] == "120.0"


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


def test_render_gallery_shows_source(tmp_path: Path) -> None:
    r = _result(tmp_path, 1, "home", "web", "home", b"x", source="http://localhost:5173/")

    out = render_gallery([r], generated_at="t")

    assert "<code>http://localhost:5173/</code>" in out


def test_render_gallery_escapes_source(tmp_path: Path) -> None:
    r = _result(tmp_path, 1, "x", "cli", "help", b"z", source='echo "<hi>" & bye')

    out = render_gallery([r], generated_at="t")

    assert 'echo "<hi>" & bye' not in out
    assert "&lt;hi&gt;" in out
    assert "&amp;" in out
    assert "&quot;" in out


def test_render_gallery_omits_source_when_empty(tmp_path: Path) -> None:
    r = _result(tmp_path, 1, "x", "cli", "help", b"z")

    out = render_gallery([r], generated_at="t")

    assert 'class="source"' not in out


def test_render_gallery_uses_custom_title(tmp_path: Path) -> None:
    r = _result(tmp_path, 1, "home", "web", "home", b"x")

    out = render_gallery([r], generated_at="t", title="Acme Docs")

    assert "<title>Acme Docs — screenshots</title>" in out
    assert "<h1>Acme Docs screenshots</h1>" in out


def test_render_gallery_default_title(tmp_path: Path) -> None:
    r = _result(tmp_path, 1, "home", "web", "home", b"x")

    out = render_gallery([r], generated_at="t")

    assert "shotlist screenshots" in out


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


def test_write_report_threads_title_and_chromium(tmp_path: Path) -> None:
    target = tmp_path / "out"
    r1 = _result(target, 1, "home", "web", "home", b"x" * 10, source="http://x/")

    report = write_report(
        [r1], target, generated_at="t", config="c", title="Acme", chromium="121.0"
    )

    gallery = report.gallery_path.read_text()
    assert "<h1>Acme screenshots</h1>" in gallery
    manifest = json.loads(report.manifest_path.read_text())
    assert manifest["environment"]["chromium"] == "121.0"
    assert manifest["shots"][0]["source"] == "http://x/"
