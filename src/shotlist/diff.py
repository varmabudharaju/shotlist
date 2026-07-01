"""Pixel diffs and the drift report for ``shotlist check``.

Two jobs live here, both pure (the CLI owns the file IO):

- :func:`diff_images` compares two PNGs and renders a 3-up image
  (baseline | current | the current with changed pixels highlighted). The pixel
  counts it returns also drive the *tolerance* decision in :mod:`shotlist.check`
  — a shot only counts as drift when the changed-pixel ratio exceeds the
  configured budget, so anti-aliasing jitter no longer trips a false failure.
- :func:`render_check_report` renders ``check-report.html``: a self-contained
  page listing *every* shot with a status badge, its reason, and — for shots
  that actually drifted — the 3-up diff inline, so a CI artifact tells the whole
  story of a run at a glance.
"""

import html
import io
from dataclasses import dataclass

from PIL import Image, ImageChops

# The drift report used to be a bare "diff gallery" of only-changed shots; it is
# now a full run report, hence the rename. The CLI writes this filename.
CHECK_REPORT_NAME = "check-report.html"

_GAP = 12
_BG = (13, 17, 23)
_HIGHLIGHT = (255, 45, 85)


@dataclass(frozen=True)
class DiffResult:
    """A rendered diff and the pixel counts behind it.

    ``base_size`` / ``current_size`` are ``(width, height)`` for each input so a
    caller can describe a size change (``1280x800 -> 1280x912``) without re-opening
    the PNGs. On a size mismatch the changed/total counts are not comparable, so
    ``size_mismatch`` is set and the ratio should be ignored.
    """

    image: bytes
    changed_pixels: int
    total_pixels: int
    size_mismatch: bool
    base_size: tuple[int, int]
    current_size: tuple[int, int]

    @property
    def changed_ratio(self) -> float:
        """Fraction of pixels that differ (0.0 when the images are empty)."""
        if self.total_pixels == 0:
            return 0.0
        return self.changed_pixels / self.total_pixels


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
            base_size=base.size,
            current_size=current.size,
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
        base_size=base.size,
        current_size=current.size,
    )


@dataclass(frozen=True)
class ReportRow:
    """One shot's row in the check report.

    Decoupled from :class:`shotlist.check.ShotDiff` on purpose so this module has
    no dependency on :mod:`shotlist.check` (which already imports this one).
    ``diff_file`` is the bare filename of the 3-up diff PNG, present only for
    shots whose pixels drifted and a ``--diff`` directory was requested.
    """

    name: str
    status: str
    reason: str = ""
    diff_file: str | None = None


_STATUS_COLORS = {
    "unchanged": "#3fb950",
    "changed": "#f85149",
    "added": "#58a6ff",
    "removed": "#d29922",
    "skipped": "#8b949e",
}

_DIFF_CSS = """\
body { margin: 0; padding: 2rem; font: 15px/1.5 system-ui, sans-serif;
       background: #0d1117; color: #e6edf3; }
h1 { font-size: 1.3rem; margin: 0 0 .25rem; }
.sub { color: #8b949e; font-size: .9rem; margin-bottom: 1.5rem; }
figure { margin: 0 0 1.25rem; }
figcaption { margin-bottom: .4rem; display: flex; align-items: baseline; gap: .5rem;
             flex-wrap: wrap; }
.name { font-weight: 600; }
.reason { color: #8b949e; font-size: .85rem; }
.legend { color: #8b949e; font-size: .85rem; }
.badge { font-size: .72rem; font-weight: 600; text-transform: uppercase;
         letter-spacing: .03em; padding: .05rem .5rem; border-radius: 999px;
         color: #0d1117; }
img { width: 100%; border: 1px solid #30363d; border-radius: 8px; }
"""


def _badge(status: str) -> str:
    color = _STATUS_COLORS.get(status, "#8b949e")
    return f'<span class="badge" style="background:{color}">{html.escape(status)}</span>'


def render_check_report(rows: list[ReportRow], *, generated_at: str) -> str:
    """Render ``check-report.html`` listing every shot with a status badge.

    Changed shots that have a ``diff_file`` show their 3-up diff inline
    (baseline · current · diff); every other shot shows just its badge and
    reason, so the report is a complete record of the check run — not only the
    failures.
    """
    figures: list[str] = []
    for row in rows:
        caption = (
            "<figcaption>"
            f'<span class="name">{html.escape(row.name)}</span>'
            f"{_badge(row.status)}"
        )
        if row.reason:
            caption += f'<span class="reason">{html.escape(row.reason)}</span>'
        caption += "</figcaption>"
        image = ""
        if row.diff_file is not None:
            src = html.escape(row.diff_file, quote=True)
            image = (
                f'<img src="{src}" alt="diff for {html.escape(row.name)}"/>'
                '<div class="legend">baseline · current · diff</div>'
            )
        figures.append(f"<figure>{caption}{image}</figure>")

    total = len(rows)
    changed = sum(1 for row in rows if row.status in ("changed", "added", "removed"))
    plural = "" if total == 1 else "s"
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        "<title>shotlist — check report</title>\n"
        f"<style>\n{_DIFF_CSS}</style>\n</head>\n<body>\n"
        f"<h1>shotlist — {total} shot{plural}, {changed} drifted</h1>\n"
        f'<div class="sub">generated {html.escape(generated_at)}</div>\n'
        f"{''.join(figures)}\n"
        "</body>\n</html>\n"
    )
