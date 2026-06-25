# demo.tape — the hero GIF for capture's README (renders docs/demo.gif).
# Re-render anytime with:  vhs demo.tape   (run from the repo root)
Output docs/demo.gif

Set Shell "bash"
Set FontSize 18
Set Width 1200
Set Height 280
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 18ms

# --- stage a throwaway playground, off camera ---
Hide
Type "source demo/_setup.sh" Enter
Sleep 1.5s
Show

# --- Scene 1: adding docs screenshots, the old way ---
Type "# adding a screenshot to the docs, the old way..." Enter
Sleep 600ms
Type `mv "Desktop/Screen Shot 2026-06-24 at 3.47.11 PM.png" docs/dashboard.png` Enter
Sleep 350ms
Type `mv "Desktop/Screen Shot 2026-06-24 at 3.52.02 PM.png" docs/dashboard-final.png` Enter
Sleep 350ms
Type `mv "Desktop/Screen Shot 2026-06-24 at 4.02.59 PM.png" docs/dashboard-final-FINAL-v2-USE-THIS.png` Enter
Sleep 700ms
Type "# ...then you ship one UI tweak and every screenshot is stale." Enter
Sleep 1.6s
Type "clear" Enter
Sleep 300ms

# --- Scene 2: the capture way (a real run) ---
Type "# the capture way:" Enter
Sleep 500ms
Type "capture run" Enter
Sleep 5s
Type "# one shot list. one command. never stale again." Enter
Sleep 2s
