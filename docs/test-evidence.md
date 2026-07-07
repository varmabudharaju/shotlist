# shotlist CLI — test evidence

_Generated 2026-07-01T23:07:56Z._

<!-- shotlist:start -->
### The Shotlist Cli

<img src="docs/screenshots/01-the-shotlist-cli.png" width="100%" alt="shotlist --help showing the init, validate, run, and check commands"/>

shotlist --help showing the init, validate, run, and check commands

`.venv/bin/shotlist --help`

### Run Options

<img src="docs/screenshots/02-run-options.png" width="100%" alt="shotlist run options: --config, --only, and --version"/>

shotlist run options: --config, --only, and --version

`.venv/bin/shotlist run --help`

### Session Export

<img src="docs/screenshots/03-session-export.png" width="100%" alt="Step 1: set a variable in the session shell"/>

Step 1: set a variable in the session shell

`export GREETING='state carries across steps'`

### Session Echo

<img src="docs/screenshots/04-session-echo.png" width="100%" alt="Step 2: a later command sees it — one persistent shell"/>

Step 2: a later command sees it — one persistent shell

`echo $GREETING`

<!-- shotlist:end -->
