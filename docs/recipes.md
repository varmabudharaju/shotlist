# Recipes

Copy-paste `.shotlist.yaml` configs for common jobs. Each one is a complete shot
list — drop it in your repo and run `shotlist run`. (Install with
`pip install shotlist`; the command is `shotlist`.)

- [1. Test-evidence / proof of a feature](#1-test-evidence--proof-of-a-feature)
- [2. Regenerate docs screenshots in CI](#2-regenerate-docs-screenshots-in-ci)
- [3. Capture a long-running server](#3-capture-a-long-running-server)
- [4. A web flow with interactions](#4-a-web-flow-with-interactions)
- [5. Versioned visual history across releases](#5-versioned-visual-history-across-releases)
- [6. Pure-CLI tool docs](#6-pure-cli-tool-docs)
- [7. Web + CLI in one run](#7-web--cli-in-one-run)

---

## 1. Test-evidence / proof of a feature

**When you want** to *prove* a feature works — capture the real flow, step by step.
A `session` runs several commands in one persistent shell (state carries across
steps) and screenshots after each, so the sequence itself is the evidence.

```yaml
output:
  dir: docs/test-evidence
shots:
  - name: signup-flow
    kind: session
    clear_between: true        # clean screen per step; the shell keeps running
    steps:
      - { name: register, command: "mytool user add demo@example.com", alt: "user created" }
      - { name: login,    command: "mytool login demo@example.com",    alt: "logged in — same shell" }
      - { name: whoami,   command: "mytool whoami",                    alt: "session persists" }
```

→ `01-register.png`, `02-login.png`, `03-whoami.png`, plus a `manifest.json` and a
browsable `index.html` [proof report](pipeline.md) you can attach to a test-case
doc. macOS uses a real Terminal window; elsewhere set `style` per shot.

## 2. Regenerate docs screenshots in CI

**When you want** screenshots that can never go stale — regenerate them on every
push. CLI shots auto-fall back to `rendered` on Linux (no display needed); web
shots use headless Chromium.

```yaml
# .github/workflows/screenshots.yml
name: screenshots
on:
  push:
    branches: [main]
jobs:
  capture:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install shotlist && playwright install --with-deps chromium
      - run: shotlist run
      - uses: actions/upload-artifact@v4
        with:
          name: screenshots
          path: docs/screenshots        # PNGs + manifest.json + index.html
```

Upload `docs/screenshots` as a build artifact, or replace the last step with the
bundled action to **fail the build on drift**:

```yaml
      - uses: varmabudharaju/shotlist@v0.1.0   # runs `shotlist check` by default
```

See [Pipeline & proof reports](pipeline.md) for the manifest schema and
`shotlist check`.

## 3. Capture a long-running server

**When you want** to screenshot something that doesn't exit — a dev server, a
watcher. Background it with `&` and a small `wait_ms`; the session tears it down
on close. (macOS / `native`.)

```yaml
shots:
  - name: server-demo
    kind: session
    steps:
      - { name: boot, command: "python3 -m http.server 8000 &", wait_ms: 800, alt: "server up" }
      - { name: serve, command: "curl -s localhost:8000 | head", alt: "serving requests" }
```

## 4. A web flow with interactions

**When you want** a screenshot of a page that takes clicks to reach. `steps` run
in order before the shot (each step is exactly one action: `click`, `fill`,
`wait_for`, `wait_ms`, `press`, or `goto`).

```yaml
app:
  command: "npm run dev"
  ready: { url: http://localhost:5173, timeout: 30 }
shots:
  - name: dashboard
    kind: web
    url: http://localhost:5173/login
    full_page: true
    alt: "Dashboard after sign-in"
    steps:
      - { fill: ["#email", "demo@example.com"] }
      - { fill: ["#password", "hunter2"] }
      - { click: "text=Sign in" }
      - { wait_for: "#chart" }
```

Capture a single element instead of the page with `selector: "#chart"`.

## 5. Versioned visual history across releases

**When you want** to keep how the UI looked over time. `--version` drops each run
into its own subfolder, so old shots are never overwritten.

```bash
shotlist run --version v1     # at release 1  → docs/screenshots/v1/…
# ...ship some UI changes...
shotlist run --version v2     # at release 2  → docs/screenshots/v2/…
```

Commit both folders to diff how a screen changed release over release.

## 6. Pure-CLI tool docs

**When you want** polished screenshots of a command-line tool. On macOS the
default is a **real** Terminal.app window (your font, your theme); set
`style: rendered` for a synthetic card that works on any OS and in CI.

```yaml
shots:
  - name: help
    kind: cli
    command: "mytool --help"
    cols: 90
    rows: 24
    # style: native     # macOS default — a real Terminal.app screenshot
    # style: rendered   # any OS / CI — synthetic terminal card, no permissions
    alt: "top-level help output"
```

## 7. Web + CLI in one run

**When you want** both surfaces of a product documented together. One run boots
the app, captures the page and the command, and tears everything down.

```yaml
app:
  command: "npm run dev"
  ready: { url: http://localhost:5173, timeout: 30 }
shots:
  - { name: home,   kind: web, url: http://localhost:5173/, full_page: true, alt: "Home page" }
  - { name: status, kind: cli, command: "mytool status", alt: "CLI status output" }
```
