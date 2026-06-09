"""Turn captured terminal output into a styled "terminal window" HTML page.

CLI screenshots are produced by rendering the command's ANSI output as HTML in a
macOS-style terminal card, then screenshotting that with the same Chromium used
for web shots — so CLI and web docs share one consistent look.
"""

from ansi2html import Ansi2HTMLConverter

_converter = Ansi2HTMLConverter(inline=True, scheme="osx")


def ansi_to_html(text: str) -> str:
    """Convert ANSI-coded terminal text to inline-styled, HTML-escaped markup."""
    return _converter.convert(text, full=False)


def terminal_html(body_html: str, cols: int) -> str:
    """Wrap converted output in a terminal-window card sized to ``cols`` columns."""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
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
  font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 13px; line-height: 1.5; }}
</style></head><body>
<div class="frame"><div class="term">
<div class="bar">
<span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
</div>
<div class="body"><pre>{body_html}</pre></div>
</div></div>
</body></html>"""
