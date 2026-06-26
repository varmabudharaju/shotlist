# Claude Code integration

This directory ships an optional Claude Code integration for `shotlist`:

- [`skills/shotlist/SKILL.md`](skills/shotlist/SKILL.md) — the `/shotlist` skill.
  It inspects a repo (dev script / console scripts / README usage), writes a
  `.shotlist.yaml` shot list, runs `shotlist validate` then `shotlist run`, and
  offers to embed the generated images into the README.
- [`hooks/`](hooks/) — an **optional** `PostToolUse` hook that drops a raw
  full-screen snapshot when a dev server starts. This is a "dumb" snapshot for
  quick evidence; the curated README set always comes from `shotlist run`.

## Prerequisites

- `shotlist` installed and on your `PATH`:

  ```bash
  shotlist --help
  ```

  If it's missing, install it from the project root (see the top-level README):

  ```bash
  pip install -e ".[dev]"
  ```

- Chromium for Playwright (the rendering engine for both web and CLI shots):

  ```bash
  playwright install chromium
  ```

## Install the `/shotlist` skill

Copy (or symlink) the skill into your personal Claude Code skills directory so
`/shotlist` is available in **any** repo:

```bash
# Copy:
mkdir -p ~/.claude/skills
cp -R integrations/claude/skills/shotlist ~/.claude/skills/shotlist

# …or symlink (so it tracks this checkout):
mkdir -p ~/.claude/skills
ln -s "$(pwd)/integrations/claude/skills/shotlist" ~/.claude/skills/shotlist
```

Then, from any project, ask Claude for screenshots or invoke `/shotlist`. The
skill will detect the project type, author a `.shotlist.yaml`, run `shotlist`, and
offer to insert the images into your README.

## Enable the optional auto-snapshot hook

The hook is **off by default** and is independent of the skill. See
[`hooks/README.md`](hooks/README.md) for the exact `settings.json` snippet, the
macOS Screen Recording permission it needs, and how it differs from the curated
`shotlist run` output.

```bash
chmod +x integrations/claude/hooks/auto-snapshot.sh
```
