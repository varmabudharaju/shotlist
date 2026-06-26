#!/usr/bin/env sh
# auto-snapshot.sh — optional Claude Code hook helper.
#
# Takes a RAW full-screen snapshot of the current macOS display. This is a dumb,
# uncurated grab meant only for quick visual evidence (e.g. "a dev server just
# started, grab whatever is on screen"). It is NOT a curated shot: the polished,
# reproducible README screenshot set always comes from `shotlist run`.
#
# Usage: auto-snapshot.sh [output-dir]
#   output-dir defaults to docs/screenshots/_auto
#
# Requires macOS Screen Recording permission for the calling process, since it
# uses the OS-level `screencapture`. (`shotlist run` itself does NOT need this —
# it renders via Chromium.)
set -eu

dir="${1:-docs/screenshots/_auto}"
mkdir -p "$dir"

# -x: do not play the camera sound.
screencapture -x "$dir/snapshot-$(date +%Y%m%d-%H%M%S).png"
