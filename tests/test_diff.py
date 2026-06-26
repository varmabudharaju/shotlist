import io

from PIL import Image

from shotlist.diff import DiffResult, diff_images, render_diff_gallery

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
    assert result.image.startswith(PNG_MAGIC)


def test_differing_images_have_changed_pixels() -> None:
    result = diff_images(_png((255, 0, 0)), _png((0, 0, 255)))

    assert result.changed_pixels == 100  # every pixel differs
    assert result.size_mismatch is False
    assert result.image.startswith(PNG_MAGIC)


def test_size_mismatch_is_flagged_not_crashing() -> None:
    result = diff_images(_png((0, 0, 0), size=(10, 10)), _png((0, 0, 0), size=(20, 10)))

    assert result.size_mismatch is True
    assert result.image.startswith(PNG_MAGIC)


def test_render_diff_gallery_lists_each_entry() -> None:
    out = render_diff_gallery(
        [("dashboard", "dashboard.diff.png")], generated_at="2026-06-25T00:00:00Z"
    )

    assert "dashboard" in out
    assert 'src="dashboard.diff.png"' in out
    assert "2026-06-25T00:00:00Z" in out
