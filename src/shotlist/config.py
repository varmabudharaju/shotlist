"""Configuration model and loader for ``.shotlist.yaml`` shot lists.

The shot list is the heart of ``shotlist``: a committed, declarative description
of *how to start the app* and *what to capture*. Everything downstream consumes
the validated :class:`Config` produced by :func:`load`.
"""

import re
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ConfigError(Exception):
    """Raised when a shot list is missing, unreadable, or invalid.

    Wraps lower-level YAML and validation errors in a single, user-facing type
    so the CLI can report one clear message.
    """


class _Strict(BaseModel):
    """Base model that rejects unknown keys, turning typos into clear errors."""

    model_config = ConfigDict(extra="forbid")


class Viewport(_Strict):
    width: int = 1280
    height: int = 800


class Step(_Strict):
    """A single interaction performed before a web shot is captured.

    Exactly one action field must be set per step.
    """

    click: str | None = None
    fill: list[str] | None = None
    wait_for: str | None = None
    wait_ms: int | None = None
    press: str | None = None
    goto: str | None = None

    @model_validator(mode="after")
    def _exactly_one_action(self) -> Self:
        actions = {
            "click": self.click,
            "fill": self.fill,
            "wait_for": self.wait_for,
            "wait_ms": self.wait_ms,
            "press": self.press,
            "goto": self.goto,
        }
        present = [name for name, value in actions.items() if value is not None]
        if len(present) != 1:
            raise ValueError(
                f"each step must have exactly one action; got {present or 'none'}"
            )
        if self.fill is not None and len(self.fill) != 2:
            raise ValueError('fill must be [selector, value] (two items)')
        return self


class WebShot(_Strict):
    name: str
    kind: Literal["web"]
    url: str
    viewport: Viewport = Field(default_factory=Viewport)
    full_page: bool = True
    selector: str | None = None
    steps: list[Step] = Field(default_factory=list)
    # CSS selectors whose regions are overlaid with a solid box before capture,
    # hiding non-deterministic content (timestamps, avatars, live data) so shots
    # stay reproducible.
    mask: list[str] = Field(default_factory=list)
    alt: str = ""


class ScrubRule(_Strict):
    """A regex substitution applied to raw CLI output before it is rendered.

    Blanks out non-deterministic fragments (durations, timestamps, PIDs) so a
    ``rendered`` CLI shot is byte-stable across runs. ``pattern`` is a Python
    regular expression and ``replace`` its replacement (default: delete the
    match). Example: ``{pattern: 'in \\d+\\.\\d+s', replace: 'in X.XXs'}``.
    """

    pattern: str
    replace: str = ""

    @model_validator(mode="after")
    def _valid_pattern(self) -> Self:
        try:
            re.compile(self.pattern)
        except re.error as exc:
            raise ValueError(f"invalid scrub pattern {self.pattern!r}: {exc}") from exc
        return self


class CliShot(_Strict):
    name: str
    kind: Literal["cli"]
    command: str
    cwd: str | None = None
    cols: int = 100
    rows: int = 30
    style: Literal["native", "rendered"] | None = None
    # Regex substitutions applied to the raw output before rendering, to remove
    # non-deterministic text (rendered style only; see :class:`ScrubRule`).
    scrub: list[ScrubRule] = Field(default_factory=list)
    alt: str = ""


class SessionStep(_Strict):
    """One command in a session; produces one screenshot named after ``name``."""

    name: str
    command: str
    alt: str = ""
    wait_ms: int = 0
    clear: bool | None = None  # overrides the session's clear_between for this step


class SessionShot(_Strict):
    """A persistent Terminal session: run several commands in one window.

    The shell state (cwd, env, background jobs) persists across steps; with
    ``clear_between`` the screen is cleared before each command so every shot is
    clean while the session keeps running. The window is captured after each step
    and closed at the end. Long-running commands should be backgrounded (``&``)
    with a ``wait_ms`` so they are up before the screenshot. macOS only.
    """

    name: str
    kind: Literal["session"]
    cwd: str | None = None
    cols: int = 100
    rows: int = 30
    clear_between: bool = True
    steps: list[SessionStep] = Field(min_length=1)


Shot = Annotated[WebShot | CliShot | SessionShot, Field(discriminator="kind")]


class ReadySpec(_Strict):
    """How to know the app is ready: exactly one probe, plus a timeout."""

    url: str | None = None
    port: int | None = None
    log_line: str | None = None
    timeout: float = 30.0

    @model_validator(mode="after")
    def _exactly_one_target(self) -> Self:
        targets = [t for t in (self.url, self.port, self.log_line) if t is not None]
        if len(targets) != 1:
            raise ValueError("ready must specify exactly one of: url, port, log_line")
        return self


class AppSpec(_Strict):
    command: str
    cwd: str = "."
    env: dict[str, str] = Field(default_factory=dict)
    ready: ReadySpec | None = None


class OutputSpec(_Strict):
    dir: str = "docs/screenshots"
    version: str | None = None
    readme: str | None = None
    report: bool = True  # write manifest.json + index.html gallery alongside the PNGs
    title: str | None = None  # gallery / evidence page title (defaults to "shotlist")
    evidence: str | None = None  # optional path to a captioned test-evidence Markdown doc


class Config(_Strict):
    output: OutputSpec = Field(default_factory=OutputSpec)
    app: AppSpec | None = None
    shots: list[Shot] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_shot_names(self) -> Self:
        names = [s.name for s in self.shots]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"duplicate shot names: {dupes}")
        # Every produced image is named after a shot (web/cli) or a session step;
        # those must be unique too, or output filenames would collide.
        image_names: list[str] = []
        for shot in self.shots:
            if isinstance(shot, SessionShot):
                image_names.extend(step.name for step in shot.steps)
            else:
                image_names.append(shot.name)
        img_dupes = sorted({n for n in image_names if image_names.count(n) > 1})
        if img_dupes:
            raise ValueError(f"duplicate capture names (filenames would collide): {img_dupes}")
        return self


def load(path: str | Path) -> Config:
    """Load and validate a shot list from ``path``.

    Raises :class:`ConfigError` for any problem — missing file, malformed YAML,
    or a config that fails validation — with a message suitable for the CLI.
    """
    p = Path(path)
    try:
        text = p.read_text()
    except OSError as exc:
        raise ConfigError(f"cannot read config file {p}: {exc}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {p}: {exc}") from exc

    if data is None:
        raise ConfigError(f"config file {p} is empty")
    if not isinstance(data, dict):
        raise ConfigError(f"config root must be a mapping, got {type(data).__name__}")

    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid config in {p}:\n{exc}") from exc
