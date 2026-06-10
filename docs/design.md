# capture — design

**Date:** 2026-06-09
**Status:** approved, implementing

## Problem

Documenting a product (README, blog posts, test-evidence docs) needs screenshots
of each feature. Today that means manually launching the app, clicking to the
right state, taking a screenshot, naming it, and embedding it — every time the UI
changes. It is slow, inconsistent, and goes stale.

`capture` makes this a one-command, reproducible step: describe *how to start the
app* and *what to capture* once, in a committed shot list, and regenerate the
whole screenshot set on demand.

## Goals

- Capture polished feature screenshots for **web apps** and **CLI tools** (desktop later).
- **Reproducible**: same config + same app state → same screenshots. Re-runnable in CI.
- **Robust**: never screenshot a half-booted app; never leak child processes.
- **No paid/cloud resources, no special OS permissions.**
- Output mirrors a clean README convention (see pgsemantic): numbered, named PNGs
  under `docs/screenshots/` plus ready-to-paste `<img>` snippets with alt text.
- Double as **test-evidence capture** for test-case documents.

## Non-goals (YAGNI)

- No PyPI publishing (installable from source).
- No hosted/SaaS component.
- No desktop-GUI backend in v1 (designed so it can be added).

## Key idea: the declarative shot list

A repo commits a `.capture.yaml`. A deterministic engine reads it, boots the app,
captures every shot, tears down, and writes outputs. No AI is needed at runtime —
Claude's role is only to *generate* the shot list for a new repo by inspecting it.

```yaml
output:
  dir: docs/screenshots
  version: v1            # optional subfolder; omit for flat
  readme: README.md      # optional auto-insert target

app:                     # optional; omit for static sites / pure CLI shots
  command: "npm run dev"
  cwd: .
  ready:
    url: http://localhost:5173   # poll until HTTP 200 (or: port / log_line)
    timeout: 30

shots:
  - name: dashboard
    kind: web
    url: http://localhost:5173/dashboard
    viewport: { width: 1280, height: 800 }
    full_page: true
    alt: "Dashboard showing 2 tables, 8003 embeddings, 100% coverage"
    steps:                         # optional interactions before capture
      - { click: "text=Sign in" }
      - { fill: ["#email", "demo@example.com"] }
      - { wait_for: "#chart" }

  - name: search-help
    kind: cli
    command: "mytool search --help"
    alt: "search subcommand help output"
```

## Architecture

One rendering engine (Playwright/Chromium), two backends, glued by an engine.

```
.capture.yaml ──► config.load() ──► Engine.run()
                                      │
                  ┌───────────────────┼────────────────────┐
                  ▼                   ▼                    ▼
           lifecycle.AppProcess   backends.web         backends.cli
           (start / ready /       (Playwright nav,     (run cmd → ANSI →
            teardown)              interact, shot)      styled HTML → shot)
                                      │                    │
                                      └─────────┬──────────┘
                                                ▼
                                        output.Writer
                                   (NN-name.png + <img> snippets,
                                    optional README auto-insert)
```

### Modules (`src/capture/`)

- **config.py** — Pydantic models (`Config`, `AppSpec`, `ReadySpec`, `Shot`,
  `WebShot`, `CliShot`, `SessionShot`/`SessionStep`, `OutputSpec`) + `load(path)`
  with clear validation errors. A `session` shot expands to one image per step.
- **lifecycle.py** — `AppProcess`: spawn in its own process group, poll readiness
  (HTTP / TCP port / log line) with timeout, terminate the whole group on exit
  (context manager — no orphans). No-op when `app` is absent.
- **backends/web.py** — `capture_web(page, shot) -> bytes`: navigate, run `steps`,
  screenshot full-page or element.
- **backends/cli.py** — `capture_cli(page, shot, cwd) -> bytes` (the `rendered`
  style): run the command (pty for color), convert ANSI→HTML (`ansi2html`), render
  in a terminal-window template, screenshot the rendered HTML with the same Chromium.
- **backends/native_terminal.py** — `capture_terminal(command, cwd, cols, rows) ->
  bytes` (the `native` style, macOS default): drive the real Terminal.app via
  AppleScript and `screencapture` the actual window — an authentic screenshot.
  Needs Screen-Recording permission. Engine picks `native` on macOS, `rendered`
  elsewhere, unless the shot sets `style:` explicitly.
- **render.py** — terminal-window HTML template + ANSI→HTML helper.
- **output.py** — `Writer`: filename `NN-name.png`, write under
  `dir/[version]/`, build `<img width="100%" alt="...">` snippets, optionally
  splice them into the README between `<!-- capture:start -->`/`<!-- capture:end -->`.
- **engine.py** — orchestrates: load config → (start app) → one Chromium →
  iterate shots routing by `kind` → write → teardown. Returns a result manifest.
- **cli.py** — Typer app: `init`, `validate`, `run [--only NAME] [--version V]`.

### Why robust / permission-free

Both backends render through Playwright/Chromium, so there is **no macOS
Screen-Recording dependency** and **no external binaries** (the flakiest parts of
naive screenshotting). The readiness probe prevents capturing a half-booted app.
`AppProcess` uses a process group + context manager so a crash or Ctrl-C never
leaves an orphaned dev server.

## Testing strategy

- **config**: valid/invalid YAML, defaults, discriminated `kind`.
- **lifecycle**: dummy HTTP server — readiness success, timeout, clean teardown
  (assert the child is dead afterwards).
- **web**: a bundled static HTML page; assert non-empty PNG, element vs full-page.
- **cli**: a dummy script emitting ANSI; assert ANSI→HTML and a non-empty PNG.
- **output**: filename/numbering, README marker splice (idempotent).
- **cli (Typer)**: `CliRunner` for `init`/`validate`/`run` end-to-end on a fixture repo.

Playwright Chromium is installed in CI and locally on first use.

## Claude integration (shipped, optional)

`integrations/claude/`:
- **`/capture` skill** — inspects a repo (routes, `--help`, README), writes a
  `.capture.yaml`, runs `capture run`, offers README insertion.
- **auto-snapshot hook** — optional `PostToolUse` hook snippet that drops a raw
  full-screen snapshot when a dev server starts (honest "dumb snapshot"; the
  curated set always comes from `capture run`).
- install docs to `~/.claude`.

## Output convention (mirrors pgsemantic)

```
docs/screenshots/v1/01-dashboard.png
docs/screenshots/v1/02-search.png
```
```html
<img src="docs/screenshots/v1/01-dashboard.png" width="100%" alt="Dashboard showing ..."/>
```
