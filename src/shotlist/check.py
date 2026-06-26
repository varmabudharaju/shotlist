"""Compare a fresh capture against a committed baseline manifest (drift check).

The committed ``manifest.json`` records a ``sha256`` per shot, so a re-capture can
be checked against it without any image-diffing dependency. Structural changes
(a shot added or removed) always count as drift; content changes are only flagged
for *deterministic* shots — a real Terminal screenshot can't be compared, so it is
skipped rather than reported as a spurious change.
"""

from dataclasses import dataclass
from typing import Literal

from shotlist.report import Manifest

Status = Literal["unchanged", "changed", "added", "removed", "skipped"]


@dataclass(frozen=True)
class ShotDiff:
    """How one shot compares between the baseline and the fresh capture."""

    name: str
    status: Status
    reason: str = ""


@dataclass(frozen=True)
class CheckResult:
    """The outcome of comparing a capture against its baseline."""

    diffs: list[ShotDiff]

    @property
    def drifted(self) -> bool:
        """True when any shot changed, was added, or was removed."""
        return any(d.status in ("changed", "added", "removed") for d in self.diffs)


def compare_manifests(baseline: Manifest, current: Manifest) -> CheckResult:
    """Compare ``current`` against ``baseline`` per shot, keyed by name."""
    base_by_name = {shot["name"]: shot for shot in baseline["shots"]}
    current_names = {shot["name"] for shot in current["shots"]}
    diffs: list[ShotDiff] = []

    for shot in current["shots"]:
        name = shot["name"]
        if name not in base_by_name:
            diffs.append(ShotDiff(name, "added"))
        elif not shot["deterministic"]:
            diffs.append(ShotDiff(name, "skipped", "not reproducible (native)"))
        elif base_by_name[name]["sha256"] != shot["sha256"]:
            diffs.append(ShotDiff(name, "changed"))
        else:
            diffs.append(ShotDiff(name, "unchanged"))

    for shot in baseline["shots"]:
        if shot["name"] not in current_names:
            if shot["deterministic"]:
                diffs.append(ShotDiff(shot["name"], "removed"))
            else:
                # `check` only recaptures deterministic shots, so a native shot
                # missing from the current set was never re-shot — not removed.
                diffs.append(ShotDiff(shot["name"], "skipped", "not reproducible (native)"))

    return CheckResult(diffs=diffs)
