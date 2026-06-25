from capture.check import CheckResult, ShotDiff, compare_manifests
from capture.report import Manifest, ShotEntry


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
