"""Capture screenshots of live web pages with Playwright."""

from playwright.sync_api import Page

from shotlist.config import Step, WebShot


def apply_step(page: Page, step: Step) -> None:
    """Run one declarative interaction against the page."""
    if step.goto is not None:
        page.goto(step.goto)
    elif step.click is not None:
        page.click(step.click)
    elif step.fill is not None:
        selector, value = step.fill
        page.fill(selector, value)
    elif step.wait_for is not None:
        page.wait_for_selector(step.wait_for)
    elif step.wait_ms is not None:
        page.wait_for_timeout(step.wait_ms)
    elif step.press is not None:
        page.keyboard.press(step.press)


def capture_web(page: Page, shot: WebShot) -> bytes:
    """Navigate, run any interaction steps, and return PNG bytes.

    Uses Playwright's default ``load`` wait (not ``networkidle``) so apps holding
    open connections — websockets, SSE — do not hang; use a ``wait_for`` step to
    gate on dynamic content instead.
    """
    page.set_viewport_size({"width": shot.viewport.width, "height": shot.viewport.height})
    page.goto(shot.url)
    for step in shot.steps:
        apply_step(page, step)
    if shot.selector is not None:
        return page.locator(shot.selector).screenshot()
    return page.screenshot(full_page=shot.full_page)
