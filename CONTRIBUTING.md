# Contributing to capture

Thanks for your interest in improving `shotlist`. This guide covers local setup
and the checks every change must pass.

## Dev setup

`shotlist` targets Python 3.11+. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

The editable install (`-e`) means source edits take effect immediately. The
`[dev]` extra pulls in `pytest`, `ruff`, and `mypy`. Both backends render through
Playwright/Chromium, so `playwright install chromium` is required before the
tests can run — there are no other external binaries or OS permissions to set up.

## Running the checks

Run all three from the repository root (with the virtualenv activated):

```bash
ruff check src tests   # lint + import order
mypy src tests         # strict type checking
pytest                 # test suite
```

CI runs the same commands on Python 3.11 and 3.12 (see
[`.github/workflows/ci.yml`](.github/workflows/ci.yml)); a green local run
should mean a green CI run.

### Tooling notes

- **ruff** — line length 100; rule sets `E, F, I, UP, B, C4, SIM` (configured in
  `pyproject.toml`). Let `ruff check --fix` handle import sorting.
- **mypy** — runs in `strict` mode. Every function needs full type annotations,
  and every module needs a docstring.
- Use modern syntax: `X | Y` unions (not `typing.Union`), `list[...]` /
  `dict[...]` builtins, and `from __future__` is unnecessary on 3.11+.

## Development style

`shotlist` is built test-first (TDD): tests live in `tests/` alongside the module
they exercise — `test_config.py` for `config.py`, `test_lifecycle.py` for
`lifecycle.py`, `test_web.py` / `test_cli_backend.py` for the backends, and so
on. When adding a feature or fixing a bug:

1. Write a failing test that captures the desired behaviour.
2. Implement the smallest change that makes it pass.
3. Run `ruff check src tests`, `mypy src tests`, and `pytest` before opening a PR.

Keep changes focused, match the surrounding conventions (Pydantic `_Strict`
models, clear error types, module + function docstrings), and make sure the full
check suite is green.
