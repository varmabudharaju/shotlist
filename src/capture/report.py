"""Emit a run manifest and a gallery from a set of captured shots.

A capture run produces a list of :class:`~capture.output.CaptureResult`. This
module turns that list into two artifacts written next to the PNGs:

- ``manifest.json`` — a machine-readable record of the run (a pipeline artifact);
- ``index.html`` — a self-contained gallery you can open or share as a proof
  report.

Both reference the images by bare filename, so the output directory is portable:
copy it anywhere and the gallery still renders.
"""

import hashlib
import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from capture.output import CaptureResult

SCHEMA_VERSION = "1"
MANIFEST_NAME = "manifest.json"
GALLERY_NAME = "index.html"


class ShotEntry(TypedDict):
    """One shot's record in the manifest."""

    index: int
    name: str
    kind: str
    alt: str
    file: str
    bytes: int
    sha256: str
    deterministic: bool


class Manifest(TypedDict):
    """The full run manifest written to ``manifest.json``."""

    schema_version: str
    generated_at: str
    config: str
    shot_count: int
    shots: list[ShotEntry]


@dataclass(frozen=True)
class RunReport:
    """Where the manifest and gallery for a run were written."""

    manifest_path: Path
    gallery_path: Path


def build_manifest(
    results: list[CaptureResult],
    *,
    generated_at: str,
    config: str,
) -> Manifest:
    """Build the JSON-serializable manifest for a run.

    Each shot records its 1-based ``index``, ``name``, ``kind``, ``alt`` text,
    the ``file`` (bare PNG filename), and its size in ``bytes``.
    """
    shots: list[ShotEntry] = [
        {
            "index": index,
            "name": result.name,
            "kind": result.kind,
            "alt": result.alt,
            "file": result.path.name,
            "bytes": result.path.stat().st_size,
            "sha256": hashlib.sha256(result.path.read_bytes()).hexdigest(),
            "deterministic": result.deterministic,
        }
        for index, result in enumerate(results, start=1)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "config": config,
        "shot_count": len(results),
        "shots": shots,
    }


_GALLERY_CSS = """\
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; padding: 2rem; font: 15px/1.5 system-ui, sans-serif;
       background: #f6f7f9; color: #1b1f24; }
header { max-width: 1100px; margin: 0 auto 1.5rem; }
h1 { margin: 0 0 .25rem; font-size: 1.4rem; }
.sub { color: #6a737d; font-size: .9rem; }
.grid { max-width: 1100px; margin: 0 auto; display: grid; gap: 1.25rem;
        grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); }
figure { margin: 0; background: #fff; border: 1px solid #e1e4e8; border-radius: 10px;
         overflow: hidden; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
figure img { width: 100%; display: block; background: #fafbfc; }
figcaption { padding: .75rem .9rem; }
.name { font-weight: 600; }
.badge { display: inline-block; margin-left: .5rem; padding: .05rem .45rem; font-size: .72rem;
         border-radius: 999px; background: #eaeef2; color: #57606a; vertical-align: middle; }
.alt { margin: .35rem 0 0; color: #57606a; font-size: .88rem; }
@media (prefers-color-scheme: dark) {
  body { background: #0d1117; color: #e6edf3; }
  figure { background: #161b22; border-color: #30363d; }
  figure img { background: #0d1117; }
  .sub, .alt, .badge { color: #8b949e; }
  .badge { background: #21262d; }
}
"""


def render_gallery(
    results: list[CaptureResult],
    *,
    generated_at: str,
    title: str = "capture",
) -> str:
    """Render a self-contained ``index.html`` gallery of the results."""
    count = len(results)
    plural = "" if count == 1 else "s"
    cards: list[str] = []
    for result in results:
        name = html.escape(result.name)
        kind = html.escape(result.kind)
        alt = html.escape(result.alt)
        file = html.escape(result.path.name, quote=True)
        cards.append(
            "<figure>"
            f'<img src="{file}" alt="{alt}" loading="lazy"/>'
            "<figcaption>"
            f'<span class="name">{name}</span><span class="badge">{kind}</span>'
            f'<p class="alt">{alt}</p>'
            "</figcaption>"
            "</figure>"
        )
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        f"<title>{html.escape(title)} — screenshots</title>\n"
        f"<style>\n{_GALLERY_CSS}</style>\n</head>\n<body>\n"
        "<header>\n"
        f"<h1>{html.escape(title)} screenshots</h1>\n"
        f'<div class="sub">{count} shot{plural} · generated {html.escape(generated_at)}</div>\n'
        "</header>\n"
        f'<div class="grid">\n{"".join(cards)}\n</div>\n'
        "</body>\n</html>\n"
    )


def write_report(
    results: list[CaptureResult],
    target_dir: Path,
    *,
    generated_at: str,
    config: str,
) -> RunReport:
    """Write ``manifest.json`` and ``index.html`` into ``target_dir``."""
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(results, generated_at=generated_at, config=config)
    manifest_path = target_dir / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    gallery_path = target_dir / GALLERY_NAME
    gallery_path.write_text(render_gallery(results, generated_at=generated_at))
    return RunReport(manifest_path=manifest_path, gallery_path=gallery_path)
