# Changelog

All notable changes to `shotlist` are documented here. Format follows [Keep a
Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [0.3.2] — 2026-07-01

- New **[`docs/how-it-works.md`](docs/how-it-works.md)**: a full plain-language
  walkthrough with Mermaid flow diagrams — the run pipeline, shot routing, a
  step-by-step sequence of one run, the `check` drift loop and its human
  workflow, the determinism layers, and a module map. Linked from the README's
  "How it works" section.

## [0.3.1] — 2026-07-01

Docs-only patch — refreshes the README (and its PyPI mirror) with real,
regenerated illustrations of the 0.3.0 features.

- New README section "Catch drift before your users do", embedding `check`'s
  drift output with pixel stats and the badged `check-report.html` — both
  captured by shotlist itself from a genuinely drifted demo project.
- Regenerated `proof-report.png` (now showing `output.title`, kind badges, and
  per-shot `source` lines) and `diff-example.png`; added `check-report.png` to
  `docs/pipeline.md`.
- Fixed the README's coverage-gate figure (80% → 85%) and stale alt texts;
  Action examples and the `verify-release` pin now reference `@v0.3.1`.

## [0.3.0] — 2026-07-01

### Added

- `check.max_diff_pixel_ratio` config (float, `0.0`–`1.0`, default `0.0`): a
  pixel-diff tolerance budget so sub-pixel/anti-aliasing jitter no longer fails
  `shotlist check`. Below the budget a hash-mismatched shot reports `unchanged`
  with the stats in its reason; above it, `changed`.
- `shotlist check --json`: emits the drift report as JSON on stdout (all
  human-readable lines move to stderr); still exits non-zero on drift.
- `shotlist check --update --only NAME` (repeatable): re-blesses only the named
  deterministic shots in place, preserving the baseline's `NN-` file numbering
  and every manifest key the command doesn't manage.
- `check-report.html` (replaces `diff.html`): lists **every** shot with a
  status badge and reason, with an inline baseline·current·diff image for
  changed shots — not just the failures.
- Environment-mismatch warnings: `check` compares the baseline's `environment`
  block against the current machine and prints/`--json`-reports a warning per
  differing key, without failing the shot itself.
- `mask` on web shots (`mask: [css-selector, ...]`): matched regions are
  overlaid with a solid box before capture, hiding non-deterministic content
  (timestamps, avatars, live data).
- Web shots now capture with CSS animations disabled automatically — no config
  needed.
- `scrub` on CLI shots (`scrub: [{pattern, replace}]`): regex substitutions
  applied to the raw output before rendering, for stripping non-deterministic
  text (durations, timestamps, PIDs); invalid patterns are rejected at config
  load.
- Rendered CLI cards embed JetBrains Mono (SIL OFL-1.1) — byte-identical output
  regardless of the host machine's installed fonts.
- Manifest: per-shot `source` (the URL or command that produced it), a
  top-level `environment` block (`shotlist`, `python`, `platform`,
  `playwright`, `chromium`), and `git_sha` (short commit SHA, `null` when
  unavailable). New public `shotlist.report.collect_environment()` helper.
- `output.title`: sets the gallery/evidence heading and `<title>` (default
  `"shotlist"`).
- `output.evidence`: path to an idempotent, captioned Markdown test-evidence
  doc, spliced between `<!-- shotlist:start -->` / `<!-- shotlist:end -->`
  markers — its own file, separate from `output.dir`.
- GitHub Action: `package` input (default `shotlist`; pass `-e .` to exercise a
  checked-out source tree) and `diff-dir` input (default `shotlist-diffs`).
  On `check`, the action now also renders a Markdown step summary and uploads
  `<diff-dir>` plus the JSON report as a `shotlist-check-<job>` artifact, then
  exits with `check`'s own code.
- CI: a `verify-source` job in `verify-action.yml` exercises the PR's own
  `action.yml` against its own source (`package: -e .`), alongside the renamed
  `verify-release` job (still pinned `@v0.2.0`); a `macos-14` (Python 3.12)
  matrix leg in `ci.yml`; a `pytest --cov-fail-under=85` coverage gate.

### Changed

- `docs/pipeline.md`: the manifest example now includes `sha256`,
  `deterministic`, `source`, `environment`, and `git_sha`; the field table is
  updated to match.

### Fixed

- `docs/pipeline.md`: "Bump the `@v0.1.0` tag when you upgrade" corrected to
  `@v0.2.0`, matching the rest of the doc.

## [0.2.0]

Seeded from git history; brief.

- Rebrand: command, package, config, and docs renamed from `capture` to
  `shotlist`; GitHub repo renamed to match.
- Fix: the GitHub Action runs `shotlist` (not the old `capture` binary); Action
  examples pinned to `@v0.2.0`.
- Regenerate visual assets (hero GIF, screenshots) with shotlist branding.
- Add a `verify-action` CI status badge to the README.
