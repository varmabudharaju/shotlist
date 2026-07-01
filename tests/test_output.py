from pathlib import Path

import pytest

from shotlist.config import OutputSpec
from shotlist.output import CaptureResult, Writer, slugify


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Dashboard", "dashboard"),
        ("Search Help", "search-help"),
        ("search_help", "search-help"),
        ("  Hello   World  ", "hello-world"),
        ("Foo!!!Bar", "foobar"),
        ("a--b__c  d", "a-b-c-d"),
        ("--Leading and Trailing--", "leading-and-trailing"),
        ("Mix3d C0ntent", "mix3d-c0ntent"),
        ("café & co", "caf-co"),
    ],
)
def test_slugify(raw: str, expected: str) -> None:
    assert slugify(raw) == expected


def test_target_dir_without_version(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(dir="docs/screenshots"), tmp_path)
    assert writer.target_dir() == tmp_path / "docs" / "screenshots"


def test_target_dir_with_version(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(dir="docs/screenshots", version="v1"), tmp_path)
    assert writer.target_dir() == tmp_path / "docs" / "screenshots" / "v1"


def test_write_creates_file_and_src(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(dir="docs/screenshots", version="v1"), tmp_path)
    data = b"\x89PNG fake bytes"
    result = writer.write(1, "Dashboard View", data, alt="the dashboard", kind="web")

    expected_path = tmp_path / "docs" / "screenshots" / "v1" / "01-dashboard-view.png"
    assert result.path == expected_path
    assert expected_path.exists()
    assert expected_path.read_bytes() == data
    assert result.src == "docs/screenshots/v1/01-dashboard-view.png"
    assert result.name == "Dashboard View"
    assert result.alt == "the dashboard"
    assert result.kind == "web"


def test_write_zero_pads_index(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(dir="shots"), tmp_path)
    result = writer.write(7, "x", b"data", alt="", kind="cli")
    assert result.path.name == "07-x.png"


def test_write_src_falls_back_when_outside_repo_root(tmp_path: Path) -> None:
    # An absolute output dir outside the repo root (as `shotlist check` uses for its
    # temp probe) must not crash; src degrades to the bare filename.
    outside = tmp_path / "outside"
    writer = Writer(OutputSpec(dir=str(outside)), tmp_path / "repo")

    result = writer.write(1, "x", b"data", alt="", kind="cli")

    assert result.path == outside / "01-x.png"
    assert result.src == "01-x.png"


def test_img_snippet_escapes_alt(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(), tmp_path)
    result = CaptureResult(
        name="n",
        path=tmp_path / "01-n.png",
        src="docs/01-n.png",
        alt='a "quoted" & <tagged> alt',
        kind="web",
    )
    snippet = writer.img_snippet(result)
    assert '<img src="docs/01-n.png" width="100%"' in snippet
    assert '"' not in snippet.split('alt="', 1)[1].rsplit('"/>', 1)[0]
    assert "&quot;" in snippet
    assert "&amp;" in snippet
    assert "&lt;tagged&gt;" in snippet


def test_markdown_block_has_heading_and_img(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(), tmp_path)
    results = [
        CaptureResult(
            name="search-help",
            path=tmp_path / "01-search-help.png",
            src="docs/01-search-help.png",
            alt="help",
            kind="cli",
        ),
        CaptureResult(
            name="user_profile",
            path=tmp_path / "02-user-profile.png",
            src="docs/02-user-profile.png",
            alt="profile",
            kind="web",
        ),
    ]
    block = writer.markdown_block(results)
    assert "### search help" in block
    assert "### user profile" in block
    assert '<img src="docs/01-search-help.png"' in block
    assert '<img src="docs/02-user-profile.png"' in block


def _result(tmp_path: Path) -> CaptureResult:
    return CaptureResult(
        name="dashboard",
        path=tmp_path / "01-dashboard.png",
        src="docs/screenshots/01-dashboard.png",
        alt="the dashboard",
        kind="web",
    )


def test_update_readme_creates_file_when_absent(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(), tmp_path)
    readme = tmp_path / "README.md"
    changed = writer.update_readme([_result(tmp_path)], readme)

    assert changed is True
    assert readme.exists()
    text = readme.read_text()
    assert "## Screenshots" in text
    assert "<!-- shotlist:start -->" in text
    assert "<!-- shotlist:end -->" in text
    assert "### dashboard" in text


def test_update_readme_appends_section_when_markers_absent(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(), tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text("# My Project\n\nSome intro.\n")
    changed = writer.update_readme([_result(tmp_path)], readme)

    assert changed is True
    text = readme.read_text()
    assert text.startswith("# My Project\n\nSome intro.\n")
    assert "## Screenshots" in text
    assert "### dashboard" in text


def test_update_readme_replaces_between_markers(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(), tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Project\n\n## Screenshots\n\n"
        "<!-- shotlist:start -->\n"
        "### old stale heading\n\nstale content\n"
        "<!-- shotlist:end -->\n\nfooter\n"
    )
    changed = writer.update_readme([_result(tmp_path)], readme)

    assert changed is True
    text = readme.read_text()
    assert "old stale heading" not in text
    assert "stale content" not in text
    assert "### dashboard" in text
    # Surrounding content is preserved.
    assert text.startswith("# Project\n")
    assert text.rstrip().endswith("footer")
    # Markers are not duplicated.
    assert text.count("<!-- shotlist:start -->") == 1
    assert text.count("<!-- shotlist:end -->") == 1


def test_update_readme_is_idempotent(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(), tmp_path)
    readme = tmp_path / "README.md"

    first = writer.update_readme([_result(tmp_path)], readme)
    assert first is True
    after_first = readme.read_text()

    second = writer.update_readme([_result(tmp_path)], readme)
    assert second is False
    assert readme.read_text() == after_first


def test_capture_result_default_source() -> None:
    result = CaptureResult(
        name="n", path=Path("01-n.png"), src="docs/01-n.png", alt="a", kind="web"
    )
    assert result.source == ""


def test_write_carries_source(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(dir="shots"), tmp_path)
    result = writer.write(1, "x", b"data", alt="", kind="web", source="http://x/")
    assert result.source == "http://x/"


def _sourced(tmp_path: Path) -> CaptureResult:
    return CaptureResult(
        name="search-help",
        path=tmp_path / "01-search-help.png",
        src="docs/screenshots/01-search-help.png",
        alt="the help output",
        kind="cli",
        source="mytool --help",
    )


def test_evidence_block_has_heading_img_caption_and_source(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(), tmp_path)
    block = writer.evidence_block([_sourced(tmp_path)])

    assert "### Search Help" in block
    assert '<img src="docs/screenshots/01-search-help.png"' in block
    assert "the help output" in block
    assert "`mytool --help`" in block


def test_evidence_block_omits_empty_alt_and_source(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(), tmp_path)
    result = CaptureResult(
        name="bare",
        path=tmp_path / "01-bare.png",
        src="docs/01-bare.png",
        alt="",
        kind="cli",
    )
    block = writer.evidence_block([result])

    assert "### Bare" in block
    assert "``" not in block  # no empty inline-code source line


def test_write_evidence_creates_file_when_absent(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(), tmp_path)
    evidence = tmp_path / "docs" / "test-evidence.md"

    changed = writer.write_evidence(
        [_sourced(tmp_path)], evidence, generated_at="2026-06-25T00:00:00Z"
    )

    assert changed is True
    text = evidence.read_text()
    assert text.startswith("# shotlist — test evidence")
    assert "_Generated 2026-06-25T00:00:00Z._" in text
    assert "<!-- shotlist:start -->" in text
    assert "<!-- shotlist:end -->" in text
    assert "### Search Help" in text
    assert "`mytool --help`" in text


def test_write_evidence_uses_title(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(), tmp_path)
    evidence = tmp_path / "e.md"

    writer.write_evidence([_sourced(tmp_path)], evidence, generated_at="t", title="Acme")

    assert evidence.read_text().startswith("# Acme — test evidence")


def test_write_evidence_is_idempotent(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(), tmp_path)
    evidence = tmp_path / "e.md"

    first = writer.write_evidence([_sourced(tmp_path)], evidence, generated_at="t1")
    assert first is True
    after_first = evidence.read_text()

    # A later run with a different timestamp must not churn the file: the block
    # between the markers is unchanged, so nothing is rewritten.
    second = writer.write_evidence([_sourced(tmp_path)], evidence, generated_at="t2")
    assert second is False
    assert evidence.read_text() == after_first


def test_write_evidence_replaces_between_markers(tmp_path: Path) -> None:
    writer = Writer(OutputSpec(), tmp_path)
    evidence = tmp_path / "e.md"
    writer.write_evidence([_sourced(tmp_path)], evidence, generated_at="t1")

    updated = CaptureResult(
        name="new-shot",
        path=tmp_path / "01-new-shot.png",
        src="docs/01-new-shot.png",
        alt="fresh",
        kind="web",
        source="http://new/",
    )
    changed = writer.write_evidence([updated], evidence, generated_at="t2")

    assert changed is True
    text = evidence.read_text()
    assert "### Search Help" not in text
    assert "### New Shot" in text
    # Header/timestamp from the first run are preserved (idempotent splice).
    assert "_Generated t1._" in text
    assert text.count("<!-- shotlist:start -->") == 1
    assert text.count("<!-- shotlist:end -->") == 1
