---
name: capture
description: Use when the user wants screenshots of their app/CLI for docs or a README. Inspects the repo, writes a .capture.yaml shot list, runs `capture run`, and embeds the images.
---

# capture

`capture` regenerates a polished, reproducible set of screenshots from a committed
shot list (`.capture.yaml`). Web pages are real Playwright/Chromium renders. CLI
shots, by default on macOS, are **real screenshots of the actual Terminal.app
window** (`style: native`, needs Screen-Recording permission); set `style: rendered`
(the default off macOS) to draw the output as a styled terminal card via Chromium
instead — no permission needed, works in CI.

Your job in this skill is to inspect the repo, author a good `.capture.yaml`,
run `capture`, and offer to embed the images in the README. The runtime is fully
deterministic; the only "intelligence" needed is generating the shot list, which
is what you are here to do.

## Prerequisites

`capture` must be installed and Chromium must be present:

```bash
capture --help            # confirm the CLI is installed
playwright install chromium
```

If `capture` is not found, point the user at the install instructions in the
project README and stop.

## Procedure

### Step 1 — Detect the project type

Inspect the repo and decide which kinds of shots make sense. A repo can be web,
CLI, or both.

**Web** — look for any of:
- `package.json` with a `scripts.dev` entry, or a script that runs `vite`,
  `next dev`, `react-scripts start`, `astro dev`, `remix dev`, etc.
- A server entrypoint (e.g. `uvicorn`/`flask`/`fastapi`/`django` `runserver`,
  `node server.js`, a `Procfile` web process).

Determine the **dev command** and the **ready URL/port** the server listens on
(Vite defaults to `http://localhost:5173`, Next.js/CRA to `http://localhost:3000`,
uvicorn/flask commonly `http://localhost:8000`). When in doubt, read the repo's
README or the dev-server config.

**CLI** — look for any of:
- `pyproject.toml` `[project.scripts]` (or `setup.cfg`/`setup.py`
  `console_scripts` / `entry_points`).
- A `bin/` directory with an executable entry.
- A documented `npx <tool>` or global command.

Use the entry name as the command base (e.g. a `[project.scripts]` entry
`mytool = "..."` means the command is `mytool ...`).

**Read the README usage section** for both: it tells you the key features worth a
screenshot and the exact subcommands/flags to show. Aim for **one shot per
feature** — the things a reader most needs to see.

### Step 2 — Generate `.capture.yaml`

Write a `.capture.yaml` at the repo root, one shot per feature, using the schema
below. Guidance:

- For **web apps**, include the `app` block so `capture` boots the server before
  capturing and tears it down after. Set `app.ready.url` (or `port`) to the real
  listen address and give it a generous `timeout`.
- For **static sites** (no server) or **pure CLI tools**, omit the `app` block.
- Use `kind: cli` shots for command output (help text, a sample run). These never
  need the `app` block.
- Write a real, descriptive `alt` for every shot — it doubles as the embedded
  image's alt text and as documentation of what the shot proves.
- For web shots that require navigation/state (sign in, open a panel), use
  `steps` to drive the page before the screenshot.
- Give each shot a short, kebab-case `name`; names must be unique.

#### Exact `.capture.yaml` schema

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

**Field reference (must match exactly — unknown keys are rejected):**

- `output`: `dir` (default `docs/screenshots`), `version` (optional subfolder),
  `readme` (optional file to splice images into).
- `app` (optional): `command`, `cwd` (default `.`), `env` (map), `ready`.
- `app.ready`: exactly **one** of `url`, `port`, `log_line`, plus `timeout`
  (seconds, default 30).
- Web shot: `name`, `kind: web`, `url`, `viewport: { width, height }`
  (default 1280x800), `full_page` (default `true`), `selector` (capture one
  element instead of the page), `steps`, `alt`.
- `steps` actions — each step is exactly **one** of: `{ click: "<selector>" }`,
  `{ fill: ["<selector>", "<value>"] }`, `{ wait_for: "<selector>" }`,
  `{ wait_ms: <int> }`, `{ press: "<key>" }`, `{ goto: "<url>" }`.
- CLI shot: `name`, `kind: cli`, `command`, `cwd` (optional), `cols`
  (terminal width, default 100), `rows` (window height, default 30), `style`
  (`native` real Terminal screenshot, macOS default | `rendered` synthetic card),
  `alt`.

#### Short web example

```yaml
output:
  dir: docs/screenshots
  version: v1
  readme: README.md

app:
  command: "npm run dev"
  ready:
    url: http://localhost:5173
    timeout: 30

shots:
  - name: home
    kind: web
    url: http://localhost:5173/
    full_page: true
    alt: "Landing page with hero and feature grid"

  - name: dashboard
    kind: web
    url: http://localhost:5173/dashboard
    full_page: true
    alt: "Dashboard with live stats"
```

#### Short CLI example

```yaml
output:
  dir: docs/screenshots
  version: v1
  readme: README.md

# no app block — pure CLI tool

shots:
  - name: help
    kind: cli
    command: "mytool --help"
    alt: "Top-level help listing all subcommands"

  - name: search-help
    kind: cli
    command: "mytool search --help"
    alt: "search subcommand help output"
```

### Step 3 — Validate, then run

Always validate before running so config mistakes surface fast:

```bash
capture validate
capture run
```

Useful flags:
- `capture run --only <name>` — capture a single shot while iterating.
- `capture run --version <v>` — write into a specific version subfolder.

If `capture run` reports a readiness timeout, the `app.ready` target or
`timeout` is wrong — fix the URL/port or raise the timeout and re-run. If a web
shot's `steps`/`selector` fail, adjust the selectors to match the live DOM.

### Step 4 — Offer to embed the images in the README

`capture` can splice the generated `<img>` snippets into the README itself. To
enable it:

1. Set `output.readme: README.md` in `.capture.yaml` (the examples above do).
2. Add the marker pair where you want the images, then re-run `capture run`:

   ```markdown
   <!-- capture:start -->
   <!-- capture:end -->
   ```

   `capture` replaces everything between the markers with the current image set
   (idempotent — safe to re-run). The snippets look like:

   ```html
   <img src="docs/screenshots/v1/01-dashboard.png" width="100%" alt="Dashboard with live stats"/>
   ```

Offer this to the user; if they decline, leave `output.readme` unset and they
can paste the snippets from the output manifest manually.

## Notes

- `capture run` does **not** require macOS Screen-Recording permission — it
  renders via Chromium, not the OS screenshotter.
- Re-running with the same config and app state produces the same screenshots, so
  this is safe to put in CI.
- There is an optional, separate auto-snapshot hook for raw full-screen grabs
  (see `integrations/claude/hooks/`). That is a "dumb" snapshot for quick
  evidence; the curated README set always comes from `capture run`.
