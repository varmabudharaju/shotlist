import io
from collections.abc import Callable

import pytest
from PIL import Image
from pydantic import ValidationError

from shotlist.check import (
    CheckResult,
    ShotDiff,
    compare_environments,
    compare_manifests,
)
from shotlist.config import CheckSpec, Config
from shotlist.report import Manifest, ShotEntry


def _entry(
    name: str,
    sha: str,
    *,
    deterministic: bool = True,
    index: int = 1,
    kind: str = "web",
) -> ShotEntry:
    return {
        "index": index,
        "name": name,
        "kind": kind,
        "alt": "",
        "file": f"{index:02d}-{name}.png",
        "bytes": 1,
        "sha256": sha,
        "deterministic": deterministic,
    }


def _manifest(shots: list[ShotEntry]) -> Manifest:
    return {
        "schema_version": "1",
        "generated_at": "t",
        "config": "c",
        "shot_count": len(shots),
        "shots": shots,
    }


def test_identical_manifests_have_no_drift() -> None:
    m = _manifest([_entry("home", "aaa")])

    result = compare_manifests(m, m)

    assert isinstance(result, CheckResult)
    assert result.drifted is False
    assert result.diffs == [ShotDiff(name="home", status="unchanged")]


def test_changed_hash_is_drift() -> None:
    base = _manifest([_entry("home", "aaa")])
    current = _manifest([_entry("home", "bbb")])

    result = compare_manifests(base, current)

    assert result.drifted is True
    assert result.diffs[0].status == "changed"


def test_added_shot_is_drift() -> None:
    base = _manifest([_entry("home", "aaa", index=1)])
    current = _manifest([_entry("home", "aaa", index=1), _entry("about", "ccc", index=2)])

    result = compare_manifests(base, current)

    assert result.drifted is True
    assert {d.name: d.status for d in result.diffs} == {"home": "unchanged", "about": "added"}


def test_removed_shot_is_drift() -> None:
    base = _manifest([_entry("home", "aaa", index=1), _entry("about", "ccc", index=2)])
    current = _manifest([_entry("home", "aaa", index=1)])

    result = compare_manifests(base, current)

    assert result.drifted is True
    assert {d.name: d.status for d in result.diffs} == {"home": "unchanged", "about": "removed"}


def test_nondeterministic_shot_is_skipped_not_drift() -> None:
    # Same shot in both, different bytes — but native, so it can't be compared.
    base = _manifest([_entry("term", "aaa", deterministic=False)])
    current = _manifest([_entry("term", "bbb", deterministic=False)])

    result = compare_manifests(base, current)

    assert result.drifted is False
    assert result.diffs[0].status == "skipped"


def test_baseline_only_nondeterministic_is_skipped_not_removed() -> None:
    # `check` only recaptures deterministic shots, so a native shot present only
    # in the baseline is skipped — not reported as removed.
    base = _manifest(
        [_entry("home", "aaa", index=1), _entry("term", "bbb", deterministic=False, index=2)]
    )
    current = _manifest([_entry("home", "aaa", index=1)])

    result = compare_manifests(base, current)

    assert result.drifted is False
    assert {d.name: d.status for d in result.diffs} == {"home": "unchanged", "term": "skipped"}


# --- tolerance -------------------------------------------------------------


def _png_pixels(flipped: int, size: tuple[int, int] = (10, 10)) -> bytes:
    """A black PNG with ``flipped`` white pixels — ``flipped/100`` of a 10x10."""
    image = Image.new("RGB", size, (0, 0, 0))
    for i in range(flipped):
        image.putpixel((i % size[0], i // size[0]), (255, 255, 255))
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


def _loader(
    baseline_png: bytes, current_png: bytes
) -> Callable[[str], tuple[bytes, bytes]]:
    def load(name: str) -> tuple[bytes, bytes]:
        return baseline_png, current_png

    return load


def test_small_change_within_tolerance_is_unchanged() -> None:
    base = _manifest([_entry("home", "aaa")])
    current = _manifest([_entry("home", "bbb")])  # hash differs...

    # 1 of 100 pixels differ = 1% ; budget is 2% → not drift.
    result = compare_manifests(
        base,
        current,
        max_diff_pixel_ratio=0.02,
        load_pair=_loader(_png_pixels(0), _png_pixels(1)),
    )

    diff = result.diffs[0]
    assert result.drifted is False
    assert diff.status == "unchanged"
    assert diff.changed_pixel_ratio == 0.01
    assert "within tolerance" in diff.reason


def test_change_over_tolerance_is_drift_with_stats() -> None:
    base = _manifest([_entry("home", "aaa")])
    current = _manifest([_entry("home", "bbb")])

    # 5 of 100 pixels differ = 5% ; budget is 2% → drift.
    result = compare_manifests(
        base,
        current,
        max_diff_pixel_ratio=0.02,
        load_pair=_loader(_png_pixels(0), _png_pixels(5)),
    )

    diff = result.diffs[0]
    assert result.drifted is True
    assert diff.status == "changed"
    assert diff.changed_pixel_ratio == 0.05
    assert diff.reason == "5.00% pixels differ"


def test_size_change_is_drift_with_size_reason() -> None:
    base = _manifest([_entry("home", "aaa")])
    current = _manifest([_entry("home", "bbb")])

    result = compare_manifests(
        base,
        current,
        max_diff_pixel_ratio=0.5,
        load_pair=_loader(_png_pixels(0, size=(10, 10)), _png_pixels(0, size=(20, 10))),
    )

    diff = result.diffs[0]
    assert diff.status == "changed"
    assert diff.reason == "size 10x10 -> 20x10"
    assert diff.changed_pixel_ratio is None


def test_zero_tolerance_never_loads_pixels() -> None:
    base = _manifest([_entry("home", "aaa")])
    current = _manifest([_entry("home", "bbb")])

    def _boom(name: str) -> tuple[bytes, bytes]:
        raise AssertionError("loader must not run when tolerance is 0")

    # Default budget 0.0 → any hash mismatch is drift, no image is decoded.
    result = compare_manifests(base, current, max_diff_pixel_ratio=0.0, load_pair=_boom)

    assert result.diffs[0].status == "changed"
    assert result.diffs[0].changed_pixel_ratio is None


# --- environment -----------------------------------------------------------


def test_no_baseline_environment_yields_no_mismatch() -> None:
    assert compare_environments(None, {"chromium": "131.0"}) == []
    assert compare_environments({}, {"chromium": "131.0"}) == []


def test_environment_mismatch_reports_key_old_new() -> None:
    mismatches = compare_environments({"chromium": "126.0"}, {"chromium": "131.0"})

    assert mismatches == [("chromium", "126.0", "131.0")]


def test_environment_skips_none_and_missing_keys() -> None:
    baseline = {"python": "3.11.1", "chromium": None, "playwright": "1.40"}
    current = {"python": "3.11.1", "chromium": "131.0"}  # playwright missing

    # python matches; chromium None on baseline; playwright missing on current.
    assert compare_environments(baseline, current) == []


# --- CheckSpec config parsing ---------------------------------------------

_SHOTS = [{"name": "home", "kind": "web", "url": "http://localhost/"}]


def test_check_spec_defaults_to_exact() -> None:
    assert CheckSpec().max_diff_pixel_ratio == 0.0


def test_config_defaults_to_exact_check() -> None:
    cfg = Config.model_validate({"shots": _SHOTS})

    assert cfg.check.max_diff_pixel_ratio == 0.0


def test_config_parses_check_tolerance() -> None:
    cfg = Config.model_validate({"check": {"max_diff_pixel_ratio": 0.001}, "shots": _SHOTS})

    assert cfg.check.max_diff_pixel_ratio == 0.001


def test_check_tolerance_out_of_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CheckSpec(max_diff_pixel_ratio=1.5)
    with pytest.raises(ValidationError):
        CheckSpec(max_diff_pixel_ratio=-0.1)


def test_check_spec_rejects_unknown_key() -> None:
    with pytest.raises(ValidationError):
        CheckSpec.model_validate({"max_diff_pixel_ratio": 0.1, "bogus": 1})
