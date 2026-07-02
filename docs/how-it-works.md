# How shotlist works

`shotlist` turns one committed YAML file into a reproducible screenshot set. This
page walks the whole machine end to end — what runs, in what order, and why the
same config keeps producing the same pixels. If you only remember one thing:
**there is no magic at capture time.** The engine is a plain, deterministic
program; every arrow below is ordinary code you can read in
[`src/shotlist/`](../src/shotlist/). Diagrams are committed PNGs (rendered from
the Mermaid source tucked under each one).

## The big picture

One run: load the config, boot your app (if any), wait until it is *actually*
ready, route every shot to the right backend, write numbered PNGs plus the run
artifacts, and tear everything down — even on failure.

<img src="diagrams/run-pipeline.png" alt="Flow: .shotlist.yaml is loaded and validated; if an app is configured it boots in its own process group and a readiness probe gates capture; the engine routes each shot by kind, writes outputs, and always tears everything down"/>

<details>
<summary>Diagram source (Mermaid)</summary>

```mermaid
flowchart TD
    Y[".shotlist.yaml<br/>(committed)"] --> L["load + validate<br/>config.py"]
    L --> A{"app:<br/>configured?"}
    A -- yes --> B["boot app in its own<br/>process group<br/>lifecycle.py"]
    B --> R["readiness probe<br/>HTTP / TCP port / log line"]
    A -- no --> E
    R --> E["engine routes each shot<br/>by kind<br/>engine.py"]
    E --> O["outputs<br/>output.py + report.py"]
    O --> T["teardown: browser closed,<br/>app process group killed<br/>(always, even on crash)"]
```

</details>

Three properties make this dependable:

- **Fail loudly, never half-shoot.** The readiness probe polls an HTTP URL, a TCP
  port, or a log line until your app answers — a half-booted app fails the run
  with the app's own output attached, instead of producing a blank screenshot.
- **No orphans.** The app runs in its own process group; `run` kills the whole
  group on exit, crash, or Ctrl-C. A shotlist run never leaves a dev server behind.
- **No AI in the loop.** Claude (optionally) *authors* the YAML once by reading
  your repo. After that, capture is a deterministic program you can re-run in CI
  forever, for free.

## One engine, four kinds of shot

The engine looks at each shot's `kind` (and, for CLI shots, its `style`) and
routes it to one of three backends. Chromium is launched once, and only if some
shot actually needs it.

<img src="diagrams/shot-routing.png" width="100%" alt="Decision tree: each shot routes by kind — web to Playwright, cli to the rendered terminal card or a real Terminal.app window depending on style, session to one persistent Terminal — all producing PNG bytes for the Writer"/>

<details>
<summary>Diagram source (Mermaid)</summary>

```mermaid
flowchart TD
    E["engine.py<br/>for each shot"] --> K{"kind?"}
    K -- web --> W["backends/web.py<br/>navigate, run steps,<br/>mask + animations off,<br/>screenshot"]
    K -- "cli" --> S{"style?<br/>(default: native on macOS,<br/>rendered elsewhere)"}
    S -- rendered --> RC["backends/cli.py<br/>run under a PTY, scrub,<br/>ANSI to HTML, render a<br/>terminal card in Chromium"]
    S -- native --> N["backends/native_terminal.py<br/>drive a real Terminal.app<br/>window via AppleScript,<br/>screencapture by window id"]
    K -- session --> SS["backends/native_terminal.py<br/>ONE persistent Terminal window,<br/>run each step, screenshot after<br/>each, shell state carries over"]
    W --> P["PNG bytes"]
    RC --> P
    N --> P
    SS --> P
    P --> WR["output.Writer<br/>NN-name.png"]
```

</details>

Why two CLI styles exist:

| | `rendered` | `native` |
| --- | --- | --- |
| What you get | a styled terminal *card* drawn by Chromium | a real screenshot of Terminal.app |
| Works on | any OS, headless CI | macOS with Screen-Recording permission |
| Reproducible byte-for-byte | **yes** — this is what `check` gates on | no (real windows never are) |

A `session` is the native backend running a *script* of commands in one window —
`cd`, environment variables, and backgrounded processes survive from step to
step, and every step yields its own numbered screenshot.

## What one `run` actually does

The same flow as a sequence — useful when you want to know *when* things happen
(and what gets cleaned up when something fails):

<img src="diagrams/run-sequence.png" width="100%" alt="Sequence: shotlist run loads the config, spawns your app, polls readiness, launches Chromium once, captures every shot, splices README and evidence, writes manifest and gallery, then closes the browser and kills the app process group"/>

<details>
<summary>Diagram source (Mermaid)</summary>

```mermaid
sequenceDiagram
    participant U as you / CI
    participant C as cli.py
    participant A as your app
    participant X as Chromium
    participant W as Writer + report

    U->>C: shotlist run
    C->>C: load + validate .shotlist.yaml
    C->>A: spawn (own process group)
    C->>A: poll readiness (HTTP / port / log)
    A-->>C: ready
    C->>X: launch once (only if a shot needs it)
    loop every selected shot
        C->>X: capture web page / terminal card
        Note over C: native + session shots use<br/>Terminal.app instead of Chromium
        C->>W: write NN-name.png
    end
    C->>W: splice README + evidence doc
    C->>W: write manifest.json + index.html
    C->>X: close browser (finally)
    C->>A: kill process group (finally)
```

</details>

## What lands on disk

Every run leaves a self-describing bundle next to your PNGs:

```text
docs/screenshots/
├── 01-dashboard.png          # numbered, slugified, stable order
├── 02-cli-help.png
├── index.html                # the proof report — a shareable gallery
└── manifest.json             # machine-readable record of the run
```

- `manifest.json` records, per shot: the file, its `sha256`, whether it is
  `deterministic`, and the `source` (URL or command) that produced it — plus a
  run-level `environment` block (shotlist / python / platform / playwright /
  chromium versions) and the `git_sha`. This is the baseline `check` compares
  against, and an audit trail for "where did this image come from?".
- `output.readme` splices `<img>` snippets into your README between
  `<!-- shotlist:start/end -->` markers, idempotently.
- `output.evidence` writes a captioned Markdown test-evidence doc the same way.

## Drift checking — the `check` loop

`shotlist check` is the regression gate: re-capture the deterministic shots into
a temp directory (never touching your committed files) and compare against the
committed manifest. The comparison is cheap-first: an equal hash short-circuits;
only a hash mismatch pays for pixel decoding.

<img src="diagrams/check-decision.png" alt="Decision tree: equal sha256 short-circuits to unchanged; otherwise a pixel diff runs — size changes are always drift, a changed-pixel ratio within tolerance is unchanged, anything above is changed, exits 1 and renders the check report"/>

<details>
<summary>Diagram source (Mermaid)</summary>

```mermaid
flowchart TD
    S["for each deterministic shot<br/>(web, cli rendered — native is skipped)"] --> H{"sha256 equals<br/>baseline?"}
    H -- yes --> U["unchanged"]
    H -- no --> D["pixel diff<br/>diff.py"]
    D --> Z{"size changed?"}
    Z -- yes --> CH["changed"]
    Z -- no --> Rt{"changed-pixel ratio<br/>&le; check.max_diff_pixel_ratio?"}
    Rt -- yes --> UT["unchanged<br/>(within tolerance)"]
    Rt -- no --> CH
    CH --> RPT["NAME.diff.png +<br/>check-report.html<br/>(with --diff DIR)"]
    CH --> X1["exit 1 — CI goes red"]
    U --> X0["exit 0"]
    UT --> X0
```

</details>

And the human workflow around it:

<img src="diagrams/drift-workflow.png" width="100%" alt="Loop: run creates the baseline, PNGs and manifest are committed, CI checks every PR; no drift merges, drift opens check-report.html — intended changes are re-blessed with --update, regressions get fixed and re-checked"/>

<details>
<summary>Diagram source (Mermaid)</summary>

```mermaid
flowchart LR
    R1["shotlist run<br/>(baseline)"] --> CM["commit PNGs +<br/>manifest.json"]
    CM --> CI["CI: shotlist check<br/>on every PR"]
    CI -- "no drift" --> G["merge"]
    CI -- drift --> V["open check-report.html<br/>baseline / current / diff"]
    V -- intended --> UP["shotlist check --update<br/>(or --update --only NAME)"]
    UP --> CM
    V -- a real regression --> FX["fix the UI,<br/>re-run check"]
    FX --> CI
```

</details>

Two refinements keep this honest rather than noisy:

- **Tolerance.** `check.max_diff_pixel_ratio: 0.001` lets sub-pixel jitter pass
  while still reporting the measured drift; the default `0.0` is exact-match.
- **Environment warnings.** If the baseline was captured with a different
  Chromium/Playwright/OS than the machine checking, `check` says so
  (`drift may be environmental`) instead of letting you chase a phantom UI bug.

## Why the same config produces the same pixels

Determinism is layered — each layer removes one source of noise:

| Layer | Noise it removes |
| --- | --- |
| Readiness probe | half-booted apps, race-dependent first paints |
| Fixed viewport + full-page/element capture | window-size dependence |
| `animations: disabled` (always, for web shots) | mid-animation frames |
| `mask: [selector, ...]` | timestamps, avatars, live data in web pages |
| `scrub: [{pattern, replace}]` | durations, PIDs, paths in CLI output |
| Embedded JetBrains Mono in rendered cards | OS font-fallback differences — macOS and Linux CI produce **byte-identical** cards |
| PTY with pinned `TERM`/`COLUMNS` | color and wrapping differences between shells |

Native Terminal shots sit deliberately outside this stack: they are *authentic*
(your font, your theme) and therefore excluded from drift checking rather than
pretending to reproduce.

## Module map

| Module | Owns |
| --- | --- |
| [`config.py`](../src/shotlist/config.py) | the YAML schema — strict pydantic models, typo-rejecting |
| [`lifecycle.py`](../src/shotlist/lifecycle.py) | app boot, readiness probes, process-group teardown |
| [`engine.py`](../src/shotlist/engine.py) | orchestration: routing shots, one Chromium, guaranteed cleanup |
| [`backends/web.py`](../src/shotlist/backends/web.py) | Playwright navigation, steps, masking, screenshots |
| [`backends/cli.py`](../src/shotlist/backends/cli.py) | PTY execution, scrubbing, ANSI capture |
| [`render.py`](../src/shotlist/render.py) | the terminal-card HTML template + embedded font |
| [`backends/native_terminal.py`](../src/shotlist/backends/native_terminal.py) | real Terminal.app windows and persistent sessions |
| [`output.py`](../src/shotlist/output.py) | file naming, README/evidence splicing |
| [`report.py`](../src/shotlist/report.py) | `manifest.json`, `index.html`, environment stamping |
| [`check.py`](../src/shotlist/check.py) + [`diff.py`](../src/shotlist/diff.py) | drift comparison and visual diffs |
| [`cli.py`](../src/shotlist/cli.py) | the `init` / `validate` / `run` / `check` commands |

For the design rationale and the decisions behind these boundaries, see
[`design.md`](design.md); for CI usage and the GitHub Action, see
[`pipeline.md`](pipeline.md).
