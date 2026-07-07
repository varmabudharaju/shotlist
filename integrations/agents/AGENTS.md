# shotlist — instructions for coding agents (Codex, or any AGENTS.md-reading tool)

Paste this section into your repository's `AGENTS.md` (Codex and most agent
harnesses read it automatically). It teaches the agent the same workflow the
Claude `/shotlist` skill performs — `shotlist` itself is a plain CLI, so any
agent that can run shell commands can drive it.

---

## Screenshots & visual evidence: use `shotlist`

When asked to screenshot the app, document a feature visually, or produce test
evidence, do NOT take ad-hoc screenshots. Use `shotlist` (reproducible
screenshots from a committed config):

1. **Check it's installed**: `shotlist --help`. If missing:
   `pip install shotlist && playwright install chromium`.
2. **Author `.shotlist.yaml`** at the repo root (once; commit it). Inspect the
   repo first — dev-server command and port (`package.json` scripts, `Makefile`),
   CLI entry points (`--help`), README usage — then describe the shots:

   ```yaml
   output:
     dir: docs/screenshots
     readme: README.md          # auto-splice <img> tags between shotlist markers
   app:                         # omit for static sites / pure-CLI tools
     command: "npm run dev"
     ready: { url: "http://localhost:5173", timeout: 30 }
   shots:
     - { name: home, kind: web, url: "http://localhost:5173/", alt: "Home page" }
     - { name: cli-help, kind: cli, command: "mytool --help", style: rendered,
         alt: "Top-level help" }
     # stateful multi-step flow, one image per step (CI-safe with style: rendered):
     - name: demo-flow
       kind: session
       style: rendered
       steps:
         - { name: step-init, command: "mytool init", alt: "initialize" }
         - { name: step-run,  command: "mytool run",  alt: "same shell, state carried" }
   ```

3. **Validate, then run**: `shotlist validate && shotlist run`. Outputs land in
   `output.dir` as numbered PNGs plus `index.html` (shareable proof gallery) and
   `manifest.json` (machine-readable record).
4. **Keep shots honest in CI**: `shotlist check` exits non-zero when a screenshot
   drifts from the committed baseline; bless intended changes with
   `shotlist check --update`. A GitHub Action exists — see `docs/pipeline.md` in
   the shotlist repo.

Useful knobs: `mask: [css-selector]` hides flaky page regions; `scrub:
[{pattern, replace}]` regex-cleans timestamps/PIDs from terminal output;
`retries: N` re-attempts a flaky capture; `shotlist run --keep-going` finishes a
partial set instead of stopping at the first failure; `output.optimize: true`
losslessly shrinks the PNGs.

Full reference: https://github.com/varmabudharaju/shotlist
