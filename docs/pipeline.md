# Pipeline & proof reports

Every `shotlist run` writes two extra files into the output directory, right next
to the PNGs:

- **`index.html`** — a self-contained gallery (a *proof report*): open it in a
  browser, share it, or attach it to a test-case doc.
- **`manifest.json`** — a machine-readable record of the run, for pipelines.

![The generated gallery](proof-report.png)

Both reference the images by bare filename, so the output directory is portable —
copy `docs/screenshots/` anywhere and the gallery still renders.

## The manifest

```json
{
  "schema_version": "1",
  "generated_at": "2026-06-25T23:27:13Z",
  "config": ".shotlist.yaml",
  "shot_count": 2,
  "shots": [
    { "index": 1, "name": "cli-help", "kind": "cli", "alt": "capture top-level help",
      "file": "01-cli-help.png", "bytes": 35864 }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `schema_version` | Manifest format version — bumped only on a breaking change. |
| `generated_at` | UTC timestamp of the run (ISO-8601). |
| `config` | The shot list the run used (the `--config` path). |
| `shot_count` | Number of images produced. |
| `shots[]` | Per image: `index`, `name`, `kind` (`web`/`cli`/`session`), `alt`, `file` (bare PNG filename), and `bytes`. |

## Drift checking — `shotlist check`

`shotlist check` re-captures and **fails if anything drifted** from the committed
`manifest.json`, comparing each shot by its `sha256`. Run it on every PR and a
changed screen turns the build red.

![shotlist check reporting drift](check.png)

- Only **deterministic** shots (`web`, `cli·rendered`) are compared; `native`
  Terminal screenshots can't reproduce byte-for-byte, so they're **skipped**.
- Checking is **non-destructive** — it captures into a temp dir and never touches
  your committed PNGs.
- Exit is **non-zero on drift** (changed / added / removed), zero when clean.

```bash
shotlist check                       # verify against the committed baseline
shotlist check --update              # re-shoot and accept the new screenshots
shotlist check --diff capture-diffs  # also render a visual diff of every change
```

Snapshot ergonomics: `check` to verify, `check --update` to bless an intended
change (like `jest -u`).

### Visual diffs

`--diff DIR` renders, for each changed shot, a 3-up image — **baseline · current ·
highlighted difference** — plus a `diff.html` gallery you can open or upload as a
CI artifact:

![baseline, current, and the highlighted difference](diff-example.png)

## In a pipeline

The manifest also makes a run scriptable — assert a count or attach it as a build
artifact:

```bash
shotlist run
test "$(jq .shot_count docs/screenshots/manifest.json)" -ge 5   # expect ≥ 5 shots
```

## GitHub Action

`shotlist` ships a composite action — drop it into a workflow to drift-check on
every push:

```yaml
# .github/workflows/screenshots.yml
name: screenshots
on: [push, pull_request]
jobs:
  capture:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: varmabudharaju/shotlist@v0.2.0      # `command` defaults to check
```

Pass `with: { command: run }` to regenerate instead, or
`with: { config: path/to/.shotlist.yaml }`. Bump the `@v0.1.0` tag when you upgrade.

See also [recipes #2](recipes.md#2-regenerate-docs-screenshots-in-ci).

## Turning it off

The report is on by default. Disable it per run or per repo:

```bash
shotlist run --no-report
```

```yaml
output:
  dir: docs/screenshots
  report: false
```
