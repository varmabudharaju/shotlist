from pathlib import Path

from playwright.sync_api import Page

from shotlist.backends.web import capture_web
from shotlist.config import Step, Viewport, WebShot
from tests.conftest import PNG_MAGIC

PAGE_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
body { font-family: sans-serif; margin: 40px; }
#box { width: 120px; height: 80px; background: #4f46e5; color: #fff; }
</style>
<script>
function reveal() {
  var d = document.createElement('div');
  d.id = 'done';
  d.textContent = 'done!';
  document.body.appendChild(d);
}
</script></head><body>
<h1 id="title">Hello capture</h1>
<div id="box">box</div>
<input id="name" />
<button id="btn" onclick="reveal()">Go</button>
</body></html>"""


def page_url(tmp_path: Path) -> str:
    f = tmp_path / "page.html"
    f.write_text(PAGE_HTML)
    return f.as_uri()


def web_shot(url: str, **kw: object) -> WebShot:
    return WebShot(name="t", kind="web", url=url, **kw)  # type: ignore[arg-type]


def test_full_page_screenshot(page: Page, tmp_path: Path) -> None:
    data = capture_web(page, web_shot(page_url(tmp_path), full_page=True))
    assert data.startswith(PNG_MAGIC)
    assert len(data) > 100


def test_element_screenshot(page: Page, tmp_path: Path) -> None:
    full = capture_web(page, web_shot(page_url(tmp_path), full_page=True))
    element = capture_web(page, web_shot(page_url(tmp_path), selector="#box"))
    assert element.startswith(PNG_MAGIC)
    # An element shot of a small box should be smaller than the whole page.
    assert len(element) < len(full)


def test_fill_step_runs(page: Page, tmp_path: Path) -> None:
    shot = web_shot(page_url(tmp_path), steps=[Step(fill=["#name", "hello"])])
    capture_web(page, shot)
    assert page.input_value("#name") == "hello"


def test_click_and_wait_steps_run(page: Page, tmp_path: Path) -> None:
    shot = web_shot(
        page_url(tmp_path),
        steps=[Step(click="#btn"), Step(wait_for="#done")],
    )
    capture_web(page, shot)
    assert page.locator("#done").count() == 1


def test_viewport_is_applied(page: Page, tmp_path: Path) -> None:
    shot = web_shot(page_url(tmp_path), viewport=Viewport(width=640, height=480), full_page=False)
    capture_web(page, shot)
    assert page.viewport_size == {"width": 640, "height": 480}
