"""Pixel diffs for changed shots — show *what* moved, not just that it moved.

Used by ``capture check --diff``: for each shot whose bytes drifted, this renders
a 3-up image (baseline | current | the current with changed pixels highlighted)
plus a small ``diff.html`` gallery. Pure functions — the CLI owns the file IO.
"""

import html
import io
from dataclasses import dataclass

from PIL import Image, ImageChops

DIFF_GALLERY_NAME = "diff.html"

_GAP = 12
_BG = (13, 17, 23)
_HIGHLIGHT = (255, 45, 85)


@dataclass(frozen=True)
class DiffResult:
    """A rendered diff and the pixel counts behind it."""

    image: bytes
    changed_pixels: int
    total_pixels: int
    size_mismatch: bool


def _load(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


def _hstack(images: list[Image.Image]) -> Image.Image:
    """Lay images out left-to-right on a dark canvas, padding to the tallest."""
    height = max(im.height for im in images)
    width = sum(im.width for im in images) + _GAP * (len(images) - 1)
    canvas = Image.new("RGB", (width, height), _BG)
    x = 0
    for im in images:
        canvas.paste(im, (x, 0))
        x += im.width + _GAP
    return canvas


def _to_png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


def diff_images(baseline_png: bytes, current_png: bytes) -> DiffResult:
    """Compare two PNGs and render a side-by-side diff.

    When the dimensions match, the third panel highlights every changed pixel.
    When they differ, a pixel overlay is impossible, so the result is flagged as a
    size mismatch and only baseline and current are shown.
    """
    base = _load(baseline_png)
    current = _load(current_png)
    total = current.width * current.height

    if base.size != current.size:
        return DiffResult(
            image=_to_png(_hstack([base, current])),
            changed_pixels=total,
            total_pixels=total,
            size_mismatch=True,
        )

    delta = ImageChops.difference(base, current).convert("L")
    mask = delta.point(lambda p: 255 if p > 0 else 0)
    changed = mask.histogram()[255]
    highlight = Image.new("RGB", current.size, _HIGHLIGHT)
    overlay = Image.composite(highlight, current, mask)
    return DiffResult(
        image=_to_png(_hstack([base, current, overlay])),
        changed_pixels=changed,
        total_pixels=total,
        size_mismatch=False,
    )


_DIFF_CSS = """\
body { margin: 0; padding: 2rem; font: 15px/1.5 system-ui, sans-serif;
       background: #0d1117; color: #e6edf3; }
h1 { font-size: 1.3rem; margin: 0 0 .25rem; }
.sub { color: #8b949e; font-size: .9rem; margin-bottom: 1.5rem; }
figure { margin: 0 0 1.75rem; }
figcaption { margin-bottom: .4rem; }
.name { font-weight: 600; }
.legend { color: #8b949e; font-size: .85rem; }
img { width: 100%; border: 1px solid #30363d; border-radius: 8px; }
"""


def render_diff_gallery(entries: list[tuple[str, str]], *, generated_at: str) -> str:
    """Render a ``diff.html`` listing each changed shot's 3-up diff image.

    ``entries`` is ``(shot name, diff image filename)`` pairs.
    """
    figures = [
        "<figure>"
        f'<figcaption><span class="name">{html.escape(name)}</span> '
        '<span class="legend">— baseline · current · diff</span></figcaption>'
        f'<img src="{html.escape(filename, quote=True)}" alt="diff for {html.escape(name)}"/>'
        "</figure>"
        for name, filename in entries
    ]
    count = len(entries)
    plural = "" if count == 1 else "s"
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        "<title>capture — drift</title>\n"
        f"<style>\n{_DIFF_CSS}</style>\n</head>\n<body>\n"
        f"<h1>capture — {count} changed shot{plural}</h1>\n"
        f'<div class="sub">generated {html.escape(generated_at)}</div>\n'
        f"{''.join(figures)}\n"
        "</body>\n</html>\n"
    )
