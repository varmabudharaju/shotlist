from pathlib import Path

import pytest

from shotlist.config import CliShot, Config, ConfigError, SessionShot, WebShot, load


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / ".shotlist.yaml"
    p.write_text(text)
    return p


def test_load_minimal_web(tmp_path: Path) -> None:
    cfg = load(
        write(
            tmp_path,
            """
            shots:
              - name: home
                kind: web
                url: http://localhost:3000
            """,
        )
    )
    assert isinstance(cfg, Config)
    assert len(cfg.shots) == 1
    shot = cfg.shots[0]
    assert isinstance(shot, WebShot)
    assert shot.url == "http://localhost:3000"
    # defaults
    assert shot.full_page is True
    assert shot.viewport.width == 1280
    assert cfg.output.dir == "docs/screenshots"
    assert cfg.output.version is None
    assert cfg.app is None


def test_load_cli_shot(tmp_path: Path) -> None:
    cfg = load(
        write(
            tmp_path,
            """
            shots:
              - name: help
                kind: cli
                command: "mytool --help"
                alt: "help output"
            """,
        )
    )
    shot = cfg.shots[0]
    assert isinstance(shot, CliShot)
    assert shot.command == "mytool --help"
    assert shot.alt == "help output"


def test_discriminator_selects_type(tmp_path: Path) -> None:
    cfg = load(
        write(
            tmp_path,
            """
            shots:
              - { name: a, kind: web, url: http://x }
              - { name: b, kind: cli, command: "echo hi" }
            """,
        )
    )
    assert isinstance(cfg.shots[0], WebShot)
    assert isinstance(cfg.shots[1], CliShot)


def test_unknown_kind_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load(write(tmp_path, "shots:\n  - { name: a, kind: desktop, url: http://x }\n"))


def test_duplicate_names_raise(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="duplicate"):
        load(
            write(
                tmp_path,
                """
                shots:
                  - { name: dup, kind: web, url: http://x }
                  - { name: dup, kind: cli, command: "echo hi" }
                """,
            )
        )


def test_empty_shots_raise(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load(write(tmp_path, "shots: []\n"))


def test_ready_requires_a_target(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="ready"):
        load(
            write(
                tmp_path,
                """
                app:
                  command: "npm run dev"
                  ready:
                    timeout: 5
                shots:
                  - { name: a, kind: web, url: http://x }
                """,
            )
        )


def test_ready_url_parses(tmp_path: Path) -> None:
    cfg = load(
        write(
            tmp_path,
            """
            app:
              command: "npm run dev"
              ready:
                url: http://localhost:5173
                timeout: 12
            shots:
              - { name: a, kind: web, url: http://x }
            """,
        )
    )
    assert cfg.app is not None
    assert cfg.app.ready is not None
    assert cfg.app.ready.url == "http://localhost:5173"
    assert cfg.app.ready.timeout == 12


def test_step_requires_exactly_one_action(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load(
            write(
                tmp_path,
                """
                shots:
                  - name: a
                    kind: web
                    url: http://x
                    steps:
                      - { click: "#go", fill: ["#a", "b"] }
                """,
            )
        )


def test_fill_step_needs_two_values(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load(
            write(
                tmp_path,
                """
                shots:
                  - name: a
                    kind: web
                    url: http://x
                    steps:
                      - { fill: ["#only-one"] }
                """,
            )
        )


def test_valid_steps_parse(tmp_path: Path) -> None:
    cfg = load(
        write(
            tmp_path,
            """
            shots:
              - name: a
                kind: web
                url: http://x
                steps:
                  - { click: "text=Sign in" }
                  - { fill: ["#email", "demo@example.com"] }
                  - { wait_for: "#chart" }
                  - { wait_ms: 200 }
            """,
        )
    )
    assert isinstance(cfg.shots[0], WebShot)
    assert len(cfg.shots[0].steps) == 4
    assert cfg.shots[0].steps[0].click == "text=Sign in"
    assert cfg.shots[0].steps[1].fill == ["#email", "demo@example.com"]


def test_cli_shot_style_and_rows(tmp_path: Path) -> None:
    cfg = load(
        write(
            tmp_path,
            """
            shots:
              - name: a
                kind: cli
                command: "echo hi"
                rows: 24
                style: native
            """,
        )
    )
    shot = cfg.shots[0]
    assert isinstance(shot, CliShot)
    assert shot.rows == 24
    assert shot.style == "native"


def test_cli_shot_style_defaults_to_none(tmp_path: Path) -> None:
    cfg = load(write(tmp_path, 'shots:\n  - { name: a, kind: cli, command: "echo hi" }\n'))
    shot = cfg.shots[0]
    assert isinstance(shot, CliShot)
    assert shot.style is None
    assert shot.rows == 30


def test_cli_shot_invalid_style_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load(
            write(
                tmp_path,
                'shots:\n  - { name: a, kind: cli, command: "echo hi", style: fancy }\n',
            )
        )


def test_session_shot_parses(tmp_path: Path) -> None:
    cfg = load(
        write(
            tmp_path,
            """
            shots:
              - name: flow
                kind: session
                cwd: .
                cols: 90
                rows: 22
                steps:
                  - name: status
                    command: "git status"
                    alt: "status"
                  - name: staged
                    command: "git add -A"
                    wait_ms: 200
            """,
        )
    )
    shot = cfg.shots[0]
    assert isinstance(shot, SessionShot)
    assert shot.clear_between is True
    assert len(shot.steps) == 2
    assert shot.steps[0].name == "status"
    assert shot.steps[1].wait_ms == 200


def test_session_requires_at_least_one_step(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load(write(tmp_path, "shots:\n  - { name: flow, kind: session, steps: [] }\n"))


def test_session_step_name_collision_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="collide"):
        load(
            write(
                tmp_path,
                """
                shots:
                  - name: a
                    kind: cli
                    command: "echo hi"
                  - name: sess
                    kind: session
                    steps:
                      - { name: a, command: "echo x" }
                """,
            )
        )


def test_web_and_cli_shots_default_retries_to_zero(tmp_path: Path) -> None:
    cfg = load(
        write(
            tmp_path,
            """
            shots:
              - { name: home, kind: web, url: http://x }
              - { name: help, kind: cli, command: "echo hi" }
            """,
        )
    )
    web, cli = cfg.shots
    assert isinstance(web, WebShot)
    assert isinstance(cli, CliShot)
    assert web.retries == 0
    assert cli.retries == 0


def test_retries_field_parses_on_web_and_cli(tmp_path: Path) -> None:
    cfg = load(
        write(
            tmp_path,
            """
            shots:
              - { name: home, kind: web, url: http://x, retries: 3 }
              - { name: help, kind: cli, command: "echo hi", retries: 1 }
            """,
        )
    )
    web, cli = cfg.shots
    assert isinstance(web, WebShot)
    assert isinstance(cli, CliShot)
    assert web.retries == 3
    assert cli.retries == 1


def test_retries_rejects_values_out_of_range(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load(write(tmp_path, "shots:\n  - { name: a, kind: web, url: http://x, retries: 6 }\n"))
    with pytest.raises(ConfigError):
        load(write(tmp_path, "shots:\n  - { name: a, kind: web, url: http://x, retries: -1 }\n"))


def test_session_shot_rejects_retries_field(tmp_path: Path) -> None:
    # Stateful native sessions aren't safely re-runnable, so `retries` is not a
    # SessionShot field; the strict model must reject it.
    with pytest.raises(ConfigError):
        load(
            write(
                tmp_path,
                """
                shots:
                  - name: flow
                    kind: session
                    retries: 2
                    steps:
                      - { name: a, command: "echo x" }
                """,
            )
        )


def test_invalid_yaml_raises_configerror(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load(write(tmp_path, "shots: [unclosed\n"))


def test_missing_file_raises_configerror(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load(tmp_path / "does-not-exist.yaml")
