#!/usr/bin/env bash
# Stage a throwaway playground for the demo GIF (docs/demo.gif).
#
# This is *sourced*, not executed, by demo.tape — so the cd/exports below
# persist into the recorded shell. It builds a temp dir with a "Desktop" full
# of cursed screenshot filenames (for the before bit) and a tiny rendered-style
# shot list (so the real `shotlist run` in the GIF needs no Terminal.app and
# would even work in CI). Re-render the GIF anytime with:  vhs demo.tape
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLAY="$(mktemp -d)"
mkdir -p "$PLAY/Desktop" "$PLAY/docs"

# The "screenshots I just took", straight off the desktop.
for t in "3.47.11 PM" "3.52.02 PM" "3.58.40 PM" "4.02.59 PM"; do
  : > "$PLAY/Desktop/Screen Shot 2026-06-24 at $t.png"
done

# A tiny rendered-style shot list: headless Chromium, no Terminal.app popups,
# so `shotlist run` runs cleanly inside the recording.
cat > "$PLAY/.shotlist.yaml" <<YAML
output:
  dir: docs/screenshots
shots:
  - name: cli-help
    kind: cli
    command: "$REPO/.venv/bin/shotlist --help"
    style: rendered
    cols: 84
    alt: "shotlist --help"
  - name: run-help
    kind: cli
    command: "$REPO/.venv/bin/shotlist run --help"
    style: rendered
    cols: 84
    alt: "shotlist run --help"
YAML

export PATH="$REPO/.venv/bin:$PATH"
unset PROMPT_COMMAND
export PS1='$ '
cd "$PLAY"
clear
