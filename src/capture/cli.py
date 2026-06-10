"""Typer command-line interface for ``capture``.

Three commands cover the whole workflow: ``init`` writes a starter shot list,
``validate`` checks a shot list loads cleanly, and ``run`` performs the capture.
Errors from config loading and app readiness are turned into a single-line
message plus a non-zero exit, so the tool fails loudly but never with a
traceback.
"""

from pathlib import Path

import typer

from capture import config as config_module
from capture import engine
from capture.lifecycle import ReadinessError

app = typer.Typer(
    add_completion=False,
    help="Reproducible screenshot capture for docs.",
)

_STARTER_YAML = """\
# .capture.yaml — declarative shot list for `capture`.
# Describe how to start your app and what to capture, then run `capture run`.

output:
  dir: docs/screenshots   # where PNGs land
  # version: v1           # optional subfolder, e.g. docs/screenshots/v1/
  # readme: README.md     # optional: splice <img> snippets into this file

# `app` is optional — omit it for static sites or pure CLI shots.
app:
  command: "npm run dev"
  cwd: .
  ready:
    url: http://localhost:5173   # poll until it responds (or use: port / log_line)
    timeout: 30

shots:
  - name: home
    kind: web
    url: http://localhost:5173/
    viewport: { width: 1280, height: 800 }
    full_page: true
    alt: "Home page"
    # steps:                      # optional interactions before the screenshot
    #   - { click: "text=Sign in" }
    #   - { fill: ["#email", "demo@example.com"] }
    #   - { wait_for: "#chart" }

  - name: cli-help
    kind: cli
    command: "mytool --help"
    alt: "Top-level CLI help output"
"""


@app.command()
def init(
    path: str = ".capture.yaml",
    force: bool = False,
) -> None:
    """Write a starter .capture.yaml shot list."""
    target = Path(path)
    if target.exists() and not force:
        typer.echo(f"refusing to overwrite existing {target} (use --force)")
        raise typer.Exit(1)
    target.write_text(_STARTER_YAML)
    typer.echo(f"wrote {target}")


@app.command()
def validate(
    config: str = typer.Option(".capture.yaml", "--config", "-c"),  # noqa: B008
) -> None:
    """Check that a shot list loads and is valid."""
    try:
        cfg = config_module.load(config)
    except config_module.ConfigError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc
    typer.echo(f"valid ({len(cfg.shots)} shots)")


@app.command()
def run(
    config: str = typer.Option(".capture.yaml", "--config", "-c"),  # noqa: B008
    only: list[str] = typer.Option(default_factory=list),  # noqa: B008
    version: str | None = typer.Option(None),
) -> None:
    """Capture all configured shots (filter with --only)."""
    try:
        cfg = config_module.load(config)
        if version is not None:
            cfg.output.version = version
        repo_root = Path(config).resolve().parent
        results = engine.run(cfg, repo_root, only or None)
    except (config_module.ConfigError, ReadinessError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from exc

    for result in results:
        typer.echo(f"{result.name} -> {result.src}")
    typer.echo(f"captured {len(results)} shot(s)")
