"""Emit a run manifest and a gallery from a set of captured shots.

A shotlist run produces a list of :class:`~shotlist.output.CaptureResult`. This
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
import platform
import subprocess
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import NotRequired, TypedDict

from shotlist.output import CaptureResult

SCHEMA_VERSION = "1"
MANIFEST_NAME = "manifest.json"
GALLERY_NAME = "index.html"


class ShotEntry(TypedDict):
    """One shot's record in the manifest.

    ``source`` (the shot's URL or command) is ``NotRequired`` so manifests
    written before it existed still type-check when loaded.
    """

    index: int
    name: str
    kind: str
    alt: str
    file: str
    bytes: int
    sha256: str
    deterministic: bool
    source: NotRequired[str]


class Manifest(TypedDict):
    """The full run manifest written to ``manifest.json``.

    ``environment`` and ``git_sha`` are ``NotRequired`` so a manifest written by
    an older shotlist (before this stamping existed) remains a valid ``Manifest``
    and stays readable by ``check``.
    """

    schema_version: str
    generated_at: str
    config: str
    shot_count: int
    shots: list[ShotEntry]
    environment: NotRequired[dict[str, str | None]]
    git_sha: NotRequired[str | None]


@dataclass(frozen=True)
class RunReport:
    """Where the manifest and gallery for a run were written."""

    manifest_path: Path
    gallery_path: Path


def _package_version(name: str) -> str:
    """Installed version of ``name``, or ``"unknown"`` when it can't be resolved."""
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "unknown"


def collect_environment(chromium: str | None = None) -> dict[str, str | None]:
    """Collect the Contract A environment block stamped onto a run manifest.

    Records the versions that determine what a capture looks like, so a manifest
    is self-documenting and a later ``check`` can warn on an environment
    mismatch. The keys are exactly ``shotlist``, ``python``, ``platform``,
    ``playwright``, and ``chromium``:

    - ``shotlist`` / ``playwright`` — installed package versions;
    - ``python`` — the interpreter version (``platform.python_version()``);
    - ``platform`` — ``sys.platform`` (e.g. ``darwin``);
    - ``chromium`` — the Playwright browser version passed in (``browser.version``),
      or ``None`` when no browser was launched for the run.
    """
    return {
        "shotlist": _package_version("shotlist"),
        "python": platform.python_version(),
        "platform": sys.platform,
        "playwright": _package_version("playwright"),
        "chromium": chromium,
    }


def _git_sha(repo_root: Path) -> str | None:
    """Short commit SHA of ``repo_root``, or ``None`` on any failure.

    Never raises: returns ``None`` when git is missing, ``repo_root`` isn't a
    repository, or the command otherwise fails — so a run offline or outside a
    repo still writes a manifest.
    """
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def build_manifest(
    results: list[CaptureResult],
    *,
    generated_at: str,
    config: str,
    chromium: str | None = None,
    repo_root: Path | None = None,
) -> Manifest:
    """Build the JSON-serializable manifest for a run.

    Each shot records its 1-based ``index``, ``name``, ``kind``, ``alt`` text,
    the ``file`` (bare PNG filename), its size in ``bytes``, and the ``source``
    (URL or command) that produced it. The manifest also always carries an
    ``environment`` block (Contract A — see :func:`collect_environment`, seeded
    with ``chromium``) and a ``git_sha`` (short SHA of ``repo_root``, or ``None``
    when ``repo_root`` is absent or not a repository). Both ``chromium`` and
    ``repo_root`` are optional so the historical
    ``build_manifest(results, generated_at=..., config=...)`` call keeps working.
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
            "source": result.source,
        }
        for index, result in enumerate(results, start=1)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "config": config,
        "shot_count": len(results),
        "shots": shots,
        "environment": collect_environment(chromium),
        "git_sha": _git_sha(repo_root) if repo_root is not None else None,
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
.source { margin: .45rem 0 0; }
.source code { display: block; overflow-x: auto; padding: .3rem .5rem; font-size: .8rem;
               border-radius: 6px; background: #eaeef2; color: #24292f;
               font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
@media (prefers-color-scheme: dark) {
  body { background: #0d1117; color: #e6edf3; }
  figure { background: #161b22; border-color: #30363d; }
  figure img { background: #0d1117; }
  .sub, .alt, .badge { color: #8b949e; }
  .badge { background: #21262d; }
  .source code { background: #21262d; color: #e6edf3; }
}
"""


def render_gallery(
    results: list[CaptureResult],
    *,
    generated_at: str,
    title: str = "shotlist",
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
        source = ""
        if result.source:
            source = f'<p class="source"><code>{html.escape(result.source)}</code></p>'
        cards.append(
            "<figure>"
            f'<img src="{file}" alt="{alt}" loading="lazy"/>'
            "<figcaption>"
            f'<span class="name">{name}</span><span class="badge">{kind}</span>'
            f'<p class="alt">{alt}</p>'
            f"{source}"
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
    title: str = "shotlist",
    chromium: str | None = None,
    repo_root: Path | None = None,
) -> RunReport:
    """Write ``manifest.json`` and ``index.html`` into ``target_dir``.

    ``chromium`` (the Playwright browser version) and ``repo_root`` seed the
    manifest's environment/``git_sha`` stamping; ``title`` sets the gallery
    heading and ``<title>``.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(
        results,
        generated_at=generated_at,
        config=config,
        chromium=chromium,
        repo_root=repo_root,
    )
    manifest_path = target_dir / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    gallery_path = target_dir / GALLERY_NAME
    gallery_path.write_text(render_gallery(results, generated_at=generated_at, title=title))
    return RunReport(manifest_path=manifest_path, gallery_path=gallery_path)
