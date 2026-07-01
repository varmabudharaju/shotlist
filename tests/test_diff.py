import io

from PIL import Image

from shotlist.diff import DiffResult, ReportRow, diff_images, render_check_report

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _png(color: tuple[int, int, int], size: tuple[int, int] = (10, 10)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def test_identical_images_have_no_changed_pixels() -> None:
    png = _png((200, 30, 30))

    result = diff_images(png, png)

    assert isinstance(result, DiffResult)
    assert result.changed_pixels == 0
    assert result.total_pixels == 100
    assert result.size_mismatch is False
    assert result.changed_ratio == 0.0
    assert result.image.startswith(PNG_MAGIC)


def test_differing_images_have_changed_pixels() -> None:
    result = diff_images(_png((255, 0, 0)), _png((0, 0, 255)))

    assert result.changed_pixels == 100  # every pixel differs
    assert result.changed_ratio == 1.0
    assert result.size_mismatch is False
    assert result.image.startswith(PNG_MAGIC)


def test_size_mismatch_is_flagged_and_reports_sizes() -> None:
    result = diff_images(_png((0, 0, 0), size=(10, 10)), _png((0, 0, 0), size=(20, 10)))

    assert result.size_mismatch is True
    assert result.base_size == (10, 10)
    assert result.current_size == (20, 10)
    assert result.image.startswith(PNG_MAGIC)


def test_partial_change_ratio_is_fraction_of_pixels() -> None:
    base = Image.new("RGB", (10, 10), (0, 0, 0))
    current = base.copy()
    # Flip a single pixel: 1 / 100 = 0.01 of the image.
    current.putpixel((0, 0), (255, 255, 255))
    buf_b, buf_c = io.BytesIO(), io.BytesIO()
    base.save(buf_b, "PNG")
    current.save(buf_c, "PNG")

    result = diff_images(buf_b.getvalue(), buf_c.getvalue())

    assert result.changed_pixels == 1
    assert result.changed_ratio == 0.01


def test_render_check_report_lists_every_shot_with_badges() -> None:
    rows = [
        ReportRow("dashboard", "changed", "0.32% pixels differ", diff_file="dashboard.diff.png"),
        ReportRow("home", "unchanged"),
        ReportRow("about", "added"),
        ReportRow("term", "skipped", "not reproducible (native)"),
    ]

    out = render_check_report(rows, generated_at="2026-06-25T00:00:00Z")

    # Every shot appears, changed shots embed their diff image inline.
    for name in ("dashboard", "home", "about", "term"):
        assert name in out
    assert 'src="dashboard.diff.png"' in out
    assert "0.32% pixels differ" in out
    # Status badges for each status are rendered as text.
    for status in ("changed", "unchanged", "added", "skipped"):
        assert status in out
    assert "2026-06-25T00:00:00Z" in out


def test_render_check_report_only_embeds_diffs_for_changed() -> None:
    rows = [ReportRow("home", "unchanged")]

    out = render_check_report(rows, generated_at="t")

    assert "<img" not in out  # nothing changed → no diff image embedded
