"""Write captured screenshots to disk and weave them into Markdown.

This module owns the *output convention*: numbered ``NN-name.png`` files under
``dir/[version]/``, plus ready-to-paste ``<img>`` snippets and an idempotent
README splice between ``<!-- capture:start -->`` / ``<!-- capture:end -->``
markers, so re-running ``capture`` refreshes docs without piling up duplicates.
"""

import html
import re
from dataclasses import dataclass
from pathlib import Path

from capture.config import OutputSpec

_START_MARKER = "<!-- capture:start -->"
_END_MARKER = "<!-- capture:end -->"

_SLUG_SEP = re.compile(r"[\s_]+")
_SLUG_DROP = re.compile(r"[^a-z0-9-]+")
_SLUG_COLLAPSE = re.compile(r"-+")


def slugify(name: str) -> str:
    """Turn an arbitrary shot name into a filesystem-safe slug.

    Lowercases, maps whitespace and underscores to ``-``, drops every other
    character outside ``[a-z0-9-]``, collapses runs of ``-``, and strips any
    leading or trailing ``-``.
    """
    text = name.lower()
    text = _SLUG_SEP.sub("-", text)
    text = _SLUG_DROP.sub("", text)
    text = _SLUG_COLLAPSE.sub("-", text)
    return text.strip("-")


@dataclass(frozen=True)
class CaptureResult:
    """The on-disk artifact for a single captured shot.

    ``src`` is the POSIX path of the PNG relative to the repo root, suitable for
    dropping straight into an ``<img src="...">`` tag in committed Markdown.
    """

    name: str
    path: Path
    src: str
    alt: str
    kind: str


class Writer:
    """Persists screenshot bytes and renders the Markdown that embeds them."""

    def __init__(self, output: OutputSpec, repo_root: Path) -> None:
        self.output = output
        self.repo_root = repo_root

    def target_dir(self) -> Path:
        """Directory the PNGs land in: ``dir`` plus ``version`` when set."""
        base = self.repo_root / self.output.dir
        if self.output.version is not None:
            base = base / self.output.version
        return base

    def write(
        self,
        index: int,
        name: str,
        data: bytes,
        alt: str,
        kind: str,
    ) -> CaptureResult:
        """Write ``data`` as ``NN-slug.png`` and describe the result."""
        target = self.target_dir()
        target.mkdir(parents=True, exist_ok=True)
        filename = f"{index:02d}-{slugify(name)}.png"
        path = target / filename
        path.write_bytes(data)
        src = path.relative_to(self.repo_root).as_posix()
        return CaptureResult(name=name, path=path, src=src, alt=alt, kind=kind)

    def img_snippet(self, result: CaptureResult) -> str:
        """Render the ``<img>`` tag for one result, escaping ``alt``."""
        alt = html.escape(result.alt, quote=True)
        return f'<img src="{result.src}" width="100%" alt="{alt}"/>'

    def markdown_block(self, results: list[CaptureResult]) -> str:
        """Render a ``### title`` + image section per result, blank-line joined."""
        sections: list[str] = []
        for result in results:
            title = result.name.replace("-", " ").replace("_", " ")
            sections.append(f"### {title}\n\n{self.img_snippet(result)}\n")
        return "\n".join(sections)

    def update_readme(self, results: list[CaptureResult], readme_path: Path) -> bool:
        """Splice the rendered block into ``readme_path`` between the markers.

        Replaces whatever currently sits between the markers (idempotent on
        re-run), or appends a fresh ``## Screenshots`` section when the markers
        are absent, creating the file if needed. Returns whether the file's
        content actually changed.
        """
        block = self.markdown_block(results)
        original = readme_path.read_text() if readme_path.exists() else ""

        start = original.find(_START_MARKER)
        end = original.find(_END_MARKER)
        if start != -1 and end != -1 and start < end:
            before = original[: start + len(_START_MARKER)]
            after = original[end:]
            updated = f"{before}\n{block}\n{after}"
        else:
            section = (
                f"\n## Screenshots\n\n{_START_MARKER}\n{block}\n{_END_MARKER}\n"
            )
            updated = original + section

        if updated == original:
            return False
        readme_path.write_text(updated)
        return True
