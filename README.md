# capture

[![CI](https://github.com/varmabudharaju/capture/actions/workflows/ci.yml/badge.svg)](https://github.com/varmabudharaju/capture/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Screenshots for your docs — as code.** One committed shot list captures your
web pages, your *real* terminal windows, and stateful CLI sessions — and
regenerates them all with a single command.

<img src="https://raw.githubusercontent.com/varmabudharaju/capture/main/docs/demo.gif" width="100%" alt="The old way: dragging Screen Shot 2026-... files into ever-more-cursed filenames, then shipping a UI tweak that makes them all stale. The capture way: one `capture run`."/>

## Contents

- [The problem](#the-problem)
- [Quickstart](#quickstart)
- [One shot list, four kinds of shot](#one-shot-list-four-kinds-of-shot)
- [Use cases](#use-cases)
- [Proof reports & pipelines](#proof-reports--pipelines)
- [Why capture, and not the others](#why-capture-and-not-the-others)
- [How it works](#how-it-works)
- [Use with Claude](#use-with-claude)
- [Commands](#commands)
- [Develop](#develop)

## The problem

Documenting a feature means launching the app, clicking to the right state,
screenshotting, naming the file, and embedding it — **every time the UI changes.**
The screenshots drift out of date the moment you ship, and nobody notices until
they're embarrassingly wrong.

`capture` makes them **reproducible**: describe *how to start your app* and *what
to shoot* once, in a committed `.capture.yaml`, then regenerate the whole set on
demand — locally or in CI. Same config + same app state → same screenshots.

## Quickstart

```bash
pip install shotlist             # installs the `capture` command
playwright install chromium      # one-time browser download

capture init        # writes a starter .capture.yaml
capture run         # boots your app, captures every shot, tears it all down
```

## One shot list, four kinds of shot

```yaml
output:
  dir: docs/screenshots
  readme: README.md            # optional: splice <img> snippets straight into the README

app:                           # optional — omit for static sites or pure-CLI shots
  command: "npm run dev"
  ready: { url: http://localhost:5173, timeout: 30 }   # never shoot a half-booted app

shots:
  - { name: dashboard, kind: web, url: http://localhost:5173/dashboard, full_page: true, alt: "Dashboard" }
  - { name: cli-help,  kind: cli, command: "mytool --help", alt: "Top-level help" }
```

| Kind | Captures | How |
| --- | --- | --- |
| **`web`** | a browser page — with optional click/fill/wait steps first | Playwright / Chromium |
| **`cli` · `native`** *(macOS default)* | a **real screenshot of your Terminal.app window** — your font, your theme | AppleScript + `screencapture` |
| **`cli` · `rendered`** *(any OS, CI-safe)* | the command's output drawn as a styled terminal card | PTY → ANSI→HTML → Chromium |
| **`session`** | a **stateful, multi-command flow** in one persistent terminal — one shot per step | one Terminal window, captured after each step |

A `session` is how you screenshot a flow whose later steps depend on earlier ones —
the shell state (cwd, env, background processes) carries across. Background a
long-running process with `&` and a small `wait_ms`, keep capturing, and the
session tears it down on close.

## Use cases

`capture` fits anywhere a screenshot would otherwise go stale:

- **README & docs screenshots** — the core: regenerate the whole set on every UI change.
- **Test-evidence / proof** — capture a feature flow step by step (a `session`) and share the generated `index.html` as proof it works.
- **CI drift-checking** — `capture check` fails the build when a screenshot changes unexpectedly (with a visual `--diff`).
- **Blog posts & tutorials** — polished web *and* CLI shots from one config.
- **Onboarding & demo galleries** — versioned sets you keep across releases.
- **Long-running processes** — background a dev server with `&` + `wait_ms` and shoot it live.

Each one has a complete, copy-paste `.capture.yaml` in the recipes cookbook,
**[`docs/recipes.md`](docs/recipes.md)**.

## Proof reports & pipelines

Every `capture run` also writes, next to the PNGs:

- **`index.html`** — a self-contained gallery you can open and share as a **proof report**;
- **`manifest.json`** — a machine-readable record of the run (a pipeline artifact).

<img src="https://raw.githubusercontent.com/varmabudharaju/capture/main/docs/proof-report.png" width="100%" alt="The generated index.html gallery: a header with the shot count and timestamp, then a card per shot showing the screenshot, its name, a kind badge, and its alt text."/>

Attach `manifest.json` to a CI job, or open `index.html` as test-evidence. Gate CI
with **`capture check`** — it re-captures and fails when a screenshot drifts from
the committed baseline (`capture check --update` to accept intended changes; add
`--diff DIR` to render baseline·current·diff images) — or drop in the bundled
**GitHub Action**. Turn the report off with `--no-report` (or `output.report:
false`). Details in **[`docs/pipeline.md`](docs/pipeline.md)**.

## Why capture, and not the others

The pieces exist in isolation; `capture` is the one tool that does all of it under
a single committed config.

| | web pages | real terminal | CLI sessions | README auto-embed | reproducible / CI |
| --- | :---: | :---: | :---: | :---: | :---: |
| **capture** | ✅ | ✅ | ✅ | ✅ | ✅ |
| shot-scraper | ✅ | ❌ | ❌ | ❌ | ✅ |
| freeze / carbon | ❌ | synthetic | ❌ | ❌ | ✅ |
| Percy / Chromatic | ✅ | ❌ | ❌ | ❌ | ✅ (cloud, paid) |
| doing it by hand | 😖 | 😖 | 😖 | ❌ | ❌ |

No cloud, no paid services, no special OS permissions for web/rendered shots.
(Native Terminal capture needs macOS Screen-Recording permission; everything else
needs nothing.)

## How it works

```
.capture.yaml ─► load + validate ─► [ boot app, wait until ready ] ─► one engine
                                                                        routes each
                                                                        shot by kind:
        web ───────► Playwright / Chromium
        cli·native ► a real Terminal.app window
        cli·render ► PTY → ANSI→HTML → Chromium
        session ───► one persistent Terminal, a shot per step
                                                                      ─► NN-name.png
                                                                         + README splice
```

The clever part is what *isn't* here: **no AI runs at capture time.** Claude's only
job is to *author* the `.capture.yaml` once by reading your repo; after that the
engine is a plain, deterministic program — fast, free, and re-runnable in CI with
no model in the loop. See the full design in [`docs/design.md`](docs/design.md).

**Robust by design.** The readiness probe (HTTP / TCP port / log line) means you
never screenshot a half-booted app, and the app is launched in its own process
group and torn down — even on a crash or Ctrl-C — so a capture run never leaves an
orphaned dev server behind.

## Capture, captured by capture

This repo dogfoods itself: the shots below are produced by running `capture run`
on its own [`.capture.yaml`](.capture.yaml) and spliced in automatically.

<!-- capture:start -->
### The capture CLI

<img src="https://raw.githubusercontent.com/varmabudharaju/capture/main/docs/screenshots/01-the-capture-cli.png" width="100%" alt="capture --help showing the init, validate, and run commands"/>

### Run options

<img src="https://raw.githubusercontent.com/varmabudharaju/capture/main/docs/screenshots/02-run-options.png" width="100%" alt="capture run options: --config, --only, and --version"/>

<!-- capture:end -->

## Use with Claude

`capture` ships an optional Claude integration in [`integrations/claude/`](integrations/claude/):

- a **`/capture` skill** that inspects your repo (routes, `--help`, README), writes
  the `.capture.yaml` for you, and runs it;
- an optional **auto-snapshot hook** that drops a raw snapshot when a dev server
  starts (the honest "dumb snapshot"; the curated set always comes from `capture run`).

## Commands

| Command | What it does |
| --- | --- |
| `capture init` | Scaffold a starter `.capture.yaml` |
| `capture validate` | Check the shot list is well-formed |
| `capture run` | Capture every shot and write outputs |
| `capture run --only dashboard` | Capture a single shot by name |
| `capture run --version v2` | Write into a versioned subfolder |
| `capture check` | Fail if a screenshot drifted from the committed baseline |
| `capture check --update` | Re-shoot and accept the current screenshots as the baseline |
| `capture check --diff DIR` | Also render baseline·current·diff images for changed shots |

## Develop

```bash
git clone https://github.com/varmabudharaju/capture && cd capture
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
pytest                       # the suite is fully offline
```

CI runs ruff, mypy, and pytest on Python 3.11 and 3.12. A separate
**`verify-action`** workflow dogfoods the bundled GitHub Action on every PR —
running `capture run` then `capture check` on a Linux runner — so a regression in
the action is caught before it ships. Releases publish to PyPI automatically via
Trusted Publishing.

The hero GIF is itself reproducible — [`demo.tape`](demo.tape) + `vhs demo.tape`.

## License

MIT © Varma Budharaju
