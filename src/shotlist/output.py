"""Write captured screenshots to disk and weave them into Markdown.

This module owns the *output convention*: numbered ``NN-name.png`` files under
``dir/[version]/``, plus ready-to-paste ``<img>`` snippets and an idempotent
README splice between ``<!-- shotlist:start -->`` / ``<!-- shotlist:end -->``
markers, so re-running ``shotlist`` refreshes docs without piling up duplicates.
"""

import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from shotlist.config import OutputSpec

_START_MARKER = "<!-- shotlist:start -->"
_END_MARKER = "<!-- shotlist:end -->"

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
    ``source`` records *what* produced the shot — the page URL for a web shot, or
    the command for a CLI shot or session step — so the manifest and gallery are
    self-documenting evidence. ``deterministic`` is whether the shot reproduces
    byte-for-byte across runs (web and rendered-CLI do; a real Terminal screenshot
    does not) — drift checks only compare deterministic shots.
    """

    name: str
    path: Path
    src: str
    alt: str
    kind: str
    deterministic: bool = True
    source: str = ""


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
        deterministic: bool = True,
        source: str = "",
    ) -> CaptureResult:
        """Write ``data`` as ``NN-slug.png`` and describe the result.

        ``source`` is the URL or command that produced the shot; it is carried
        through onto the returned :class:`CaptureResult` for the manifest and
        gallery. It defaults to ``""`` so existing callers keep working.
        """
        target = self.target_dir()
        target.mkdir(parents=True, exist_ok=True)
        filename = f"{index:02d}-{slugify(name)}.png"
        path = target / filename
        path.write_bytes(data)
        try:
            src = path.relative_to(self.repo_root).as_posix()
        except ValueError:
            # Output dir lives outside the repo root (e.g. `shotlist check`'s temp
            # probe); a repo-relative src is meaningless, so use the bare filename.
            src = filename
        return CaptureResult(
            name=name,
            path=path,
            src=src,
            alt=alt,
            kind=kind,
            deterministic=deterministic,
            source=source,
        )

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

    def evidence_block(self, results: list[CaptureResult]) -> str:
        """Render a captioned test-evidence section per result, blank-line joined.

        Each section is a title-cased ``### heading``, the ``<img>`` snippet, the
        ``alt`` text as a caption line, and the ``source`` (URL or command) as an
        inline-code line — the empty caption/source lines are simply omitted.
        """
        sections: list[str] = []
        for result in results:
            title = result.name.replace("-", " ").replace("_", " ").title()
            parts = [f"### {title}", self.img_snippet(result)]
            if result.alt:
                parts.append(result.alt)
            if result.source:
                parts.append(f"`{result.source}`")
            sections.append("\n\n".join(parts) + "\n")
        return "\n".join(sections)

    def _splice(self, path: Path, block: str, fresh_section: str) -> bool:
        """Splice ``block`` between the markers in ``path``, idempotently.

        Replaces whatever currently sits between the markers (idempotent on
        re-run), or appends ``fresh_section`` (which must itself carry the
        markers around ``block``) when they are absent, creating the file if
        needed. Returns whether the file's content actually changed.
        """
        original = path.read_text() if path.exists() else ""

        start = original.find(_START_MARKER)
        end = original.find(_END_MARKER)
        if start != -1 and end != -1 and start < end:
            before = original[: start + len(_START_MARKER)]
            after = original[end:]
            updated = f"{before}\n{block}\n{after}"
        else:
            updated = original + fresh_section

        if updated == original:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated)
        return True

    def update_readme(self, results: list[CaptureResult], readme_path: Path) -> bool:
        """Splice the rendered block into ``readme_path`` between the markers.

        Replaces whatever currently sits between the markers (idempotent on
        re-run), or appends a fresh ``## Screenshots`` section when the markers
        are absent, creating the file if needed. Returns whether the file's
        content actually changed.
        """
        block = self.markdown_block(results)
        fresh_section = f"\n## Screenshots\n\n{_START_MARKER}\n{block}\n{_END_MARKER}\n"
        return self._splice(readme_path, block, fresh_section)

    def write_evidence(
        self,
        results: list[CaptureResult],
        evidence_path: Path,
        *,
        generated_at: str | None = None,
        title: str = "shotlist",
    ) -> bool:
        """Write/splice a captioned test-evidence Markdown doc at ``evidence_path``.

        When the file is absent it is created with a ``# <title> — test evidence``
        heading and a generated timestamp, then the captioned sections between the
        markers. On re-run the sections between the markers are replaced in place
        (idempotent) while the existing heading/timestamp are left untouched.
        Returns whether the file's content actually changed.
        """
        block = self.evidence_block(results)
        stamp = generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        heading = f"# {title} — test evidence"
        fresh_section = (
            f"{heading}\n\n_Generated {stamp}._\n\n{_START_MARKER}\n{block}\n{_END_MARKER}\n"
        )
        return self._splice(evidence_path, block, fresh_section)
