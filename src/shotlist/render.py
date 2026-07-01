"""Turn captured terminal output into a styled "terminal window" HTML page.

CLI screenshots are produced by rendering the command's ANSI output as HTML in a
macOS-style terminal card, then screenshotting that with the same Chromium used
for web shots — so CLI and web docs share one consistent look.

The card embeds the JetBrains Mono typeface (SIL Open Font License 1.1; the full
license text ships next to the font files at ``shotlist/assets/OFL.txt``) as
base64 ``@font-face`` rules. Shipping the font in the page — rather than relying
on whatever monospace the host happens to have — is what makes a rendered CLI
card byte-identical on macOS and Linux CI.
"""

import base64
from functools import lru_cache
from importlib.resources import files

from ansi2html import Ansi2HTMLConverter

_converter = Ansi2HTMLConverter(inline=True, scheme="osx")

# JetBrains Mono faces embedded in the terminal card, keyed by CSS font-weight.
_FONT_FILES: dict[int, str] = {
    400: "JetBrainsMono-Regular.woff2",
    700: "JetBrainsMono-Bold.woff2",
}


def ansi_to_html(text: str) -> str:
    """Convert ANSI-coded terminal text to inline-styled, HTML-escaped markup."""
    return _converter.convert(text, full=False)


@lru_cache(maxsize=1)
def _font_faces() -> str:
    """Return ``@font-face`` CSS embedding both JetBrains Mono faces as base64.

    The woff2 files are read from the packaged ``assets`` directory and encoded
    once (the result is cached for the process). Loading lazily — rather than at
    import time — means a missing asset surfaces a clear error only when a CLI
    card is actually rendered, instead of breaking every import of this module.
    """
    assets = files("shotlist") / "assets"
    rules: list[str] = []
    for weight, filename in _FONT_FILES.items():
        try:
            data = (assets / filename).read_bytes()
        except (FileNotFoundError, OSError) as exc:
            raise RuntimeError(
                f"embedded font {filename!r} is missing from shotlist/assets; "
                "the package was not installed with its font data"
            ) from exc
        encoded = base64.b64encode(data).decode("ascii")
        rules.append(
            "@font-face { font-family: 'JetBrains Mono'; font-style: normal; "
            f"font-weight: {weight}; "
            f"src: url(data:font/woff2;base64,{encoded}) format('woff2'); }}"
        )
    return "\n".join(rules)


def terminal_html(body_html: str, cols: int) -> str:
    """Wrap converted output in a terminal-window card sized to ``cols`` columns."""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
{_font_faces()}
* {{ box-sizing: border-box; }}
body {{ margin: 0; }}
.frame {{ display: inline-block; padding: 28px; background: #0d1117; }}
.term {{ display: inline-block; background: #161b22; border: 1px solid #30363d;
  border-radius: 10px; box-shadow: 0 12px 32px rgba(0, 0, 0, .55); overflow: hidden; }}
.bar {{ display: flex; gap: 8px; padding: 11px 14px; background: #21262d; }}
.dot {{ width: 12px; height: 12px; border-radius: 50%; }}
.r {{ background: #ff5f56; }} .y {{ background: #ffbd2e; }} .g {{ background: #27c93f; }}
.body {{ padding: 14px 18px; }}
pre {{ margin: 0; min-width: {cols}ch; color: #c9d1d9; white-space: pre;
  font-family: 'JetBrains Mono', 'SF Mono', Menlo, Consolas, monospace;
  font-size: 13px; line-height: 1.5; }}
</style></head><body>
<div class="frame"><div class="term">
<div class="bar">
<span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
</div>
<div class="body"><pre>{body_html}</pre></div>
</div></div>
</body></html>"""
