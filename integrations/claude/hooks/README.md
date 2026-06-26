# Optional auto-snapshot hook

This is an **optional** convenience hook. Be honest about what it does:

- It takes a **raw, full-screen snapshot** via the macOS `screencapture` tool
  when a dev server starts. Whatever is on your display gets grabbed — it is not
  cropped, not navigated to a specific state, and not curated.
- It is **not** a substitute for `shotlist run`. The polished, reproducible
  README/blog/test-evidence screenshot set always comes from `shotlist run`,
  which renders through Chromium and produces numbered, named, alt-tagged PNGs.

Use this hook only if you want a quick "what did the server look like the moment
it booted" artifact. Most users will skip it and rely on `shotlist run`.

## What's here

- [`auto-snapshot.sh`](auto-snapshot.sh) — POSIX `sh` helper that creates the
  output dir (default `docs/screenshots/_auto`) and writes
  `snapshot-YYYYMMDD-HHMMSS.png` into it.

## macOS permission

`screencapture` requires **Screen Recording** permission for whichever process
invokes the hook (your terminal / the Claude Code host app). Grant it under
**System Settings → Privacy & Security → Screen Recording**, then restart that
app. Without it, `screencapture` produces a blank or desktop-only image.

Note: `shotlist run` itself does **NOT** need Screen Recording permission — it
renders pages via Chromium, not the OS screenshotter. This permission is only
relevant to this optional raw-snapshot hook.

## Enabling the hook

Make the helper executable:

```bash
chmod +x integrations/claude/hooks/auto-snapshot.sh
```

Then add a `PostToolUse` hook to your Claude Code `settings.json` that matches
dev-server commands run via `Bash` and calls the helper after a short sleep (so
the server has a moment to paint its first screen). Adjust the path to
`auto-snapshot.sh` to wherever you keep this repo.

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "if echo \"$CLAUDE_TOOL_INPUT\" | grep -Eq 'npm run dev|vite|next dev|uvicorn|flask run'; then (sleep 5; sh /path/to/shotlist/integrations/claude/hooks/auto-snapshot.sh) >/dev/null 2>&1 & fi"
          }
        ]
      }
    ]
  }
}
```

What this does:

- `matcher: "Bash"` runs the hook after every `Bash` tool call.
- The `grep -Eq` guard fires only when the command that ran looks like a dev
  server: `npm run dev`, `vite`, `next dev`, `uvicorn`, or `flask run`.
- It backgrounds a `sleep 5` then runs `auto-snapshot.sh`, so the snapshot is
  taken a few seconds after the server starts (after it has had time to render)
  without blocking the tool call.

To disable, remove this block from `settings.json`.
