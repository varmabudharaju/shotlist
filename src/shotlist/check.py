"""Compare a fresh capture against a committed baseline manifest (drift check).

The committed ``manifest.json`` records a ``sha256`` per shot, so a re-capture can
be checked against it cheaply: an identical hash is an instant "unchanged" with no
image decoding at all. When the hash *differs* the change may still be noise —
sub-pixel anti-aliasing, a blinking cursor — so, when a tolerance is configured,
we fall back to a pixel diff and only report drift once the fraction of changed
pixels exceeds the budget. Structural changes (a shot added or removed) always
count as drift; content changes are only flagged for *deterministic* shots.

This module stays pure: it never touches the filesystem. The caller passes a
``load_pair`` callback that yields the baseline and current PNG bytes for a shot,
so all IO lives in the CLI where the temp-capture directory is managed.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from shotlist.diff import diff_images
from shotlist.report import Manifest

Status = Literal["unchanged", "changed", "added", "removed", "skipped"]

# name -> (baseline_png_bytes, current_png_bytes) for the tolerance fallback.
PairLoader = Callable[[str], tuple[bytes, bytes]]

# The keys of Contract-A's ``environment`` block, in a stable display order.
ENVIRONMENT_KEYS = ("shotlist", "python", "platform", "playwright", "chromium")


@dataclass(frozen=True)
class ShotDiff:
    """How one shot compares between the baseline and the fresh capture.

    ``changed_pixel_ratio`` is the fraction of pixels that differ, populated only
    when a pixel diff was actually run (tolerance path) — it is ``None`` for the
    sha256 fast path, structural changes, size mismatches, and skipped shots.
    """

    name: str
    status: Status
    reason: str = ""
    changed_pixel_ratio: float | None = None


@dataclass(frozen=True)
class CheckResult:
    """The outcome of comparing a capture against its baseline."""

    diffs: list[ShotDiff]

    @property
    def drifted(self) -> bool:
        """True when any shot changed, was added, or was removed."""
        return any(d.status in ("changed", "added", "removed") for d in self.diffs)


def _pct(ratio: float) -> str:
    """Format a 0..1 ratio as a percentage with two decimals (``0.32%``)."""
    return f"{ratio * 100:.2f}%"


def _reconcile_change(
    name: str,
    max_diff_pixel_ratio: float,
    load_pair: PairLoader | None,
) -> ShotDiff:
    """Decide whether a hash mismatch is real drift or noise within tolerance.

    With no tolerance budget (or no loader to fetch the pixels) any hash mismatch
    is drift — the historical exact-match behaviour. Otherwise the two PNGs are
    diffed: a size change is always drift; a pixel change is drift only when it
    exceeds the budget, and is reported with human-readable stats either way.
    """
    if max_diff_pixel_ratio <= 0.0 or load_pair is None:
        return ShotDiff(name, "changed")

    baseline_png, current_png = load_pair(name)
    diff = diff_images(baseline_png, current_png)
    if diff.size_mismatch:
        bw, bh = diff.base_size
        cw, ch = diff.current_size
        return ShotDiff(name, "changed", f"size {bw}x{bh} -> {cw}x{ch}")

    ratio = diff.changed_ratio
    if ratio <= max_diff_pixel_ratio:
        reason = f"within tolerance ({_pct(ratio)} <= {_pct(max_diff_pixel_ratio)})"
        return ShotDiff(name, "unchanged", reason, changed_pixel_ratio=ratio)
    return ShotDiff(name, "changed", f"{_pct(ratio)} pixels differ", changed_pixel_ratio=ratio)


def compare_manifests(
    baseline: Manifest,
    current: Manifest,
    *,
    max_diff_pixel_ratio: float = 0.0,
    load_pair: PairLoader | None = None,
) -> CheckResult:
    """Compare ``current`` against ``baseline`` per shot, keyed by name.

    ``max_diff_pixel_ratio`` is the fraction of pixels that may differ before a
    deterministic shot counts as drift; ``0.0`` (the default) keeps the exact
    sha256 behaviour and never loads a pixel. When it is positive, ``load_pair``
    must be supplied so a hash mismatch can be re-judged against the budget.
    """
    base_by_name = {shot["name"]: shot for shot in baseline["shots"]}
    current_names = {shot["name"] for shot in current["shots"]}
    diffs: list[ShotDiff] = []

    for shot in current["shots"]:
        name = shot["name"]
        if name not in base_by_name:
            diffs.append(ShotDiff(name, "added"))
        elif not shot["deterministic"]:
            diffs.append(ShotDiff(name, "skipped", "not reproducible (native)"))
        elif base_by_name[name]["sha256"] == shot["sha256"]:
            diffs.append(ShotDiff(name, "unchanged"))
        else:
            diffs.append(_reconcile_change(name, max_diff_pixel_ratio, load_pair))

    for shot in baseline["shots"]:
        if shot["name"] not in current_names:
            if shot["deterministic"]:
                diffs.append(ShotDiff(shot["name"], "removed"))
            else:
                # `check` only recaptures deterministic shots, so a native shot
                # missing from the current set was never re-shot — not removed.
                diffs.append(ShotDiff(shot["name"], "skipped", "not reproducible (native)"))

    return CheckResult(diffs=diffs)


def compare_environments(
    baseline_env: Mapping[str, object] | None,
    current_env: Mapping[str, object],
) -> list[tuple[str, str, str]]:
    """Return ``(key, baseline_value, current_value)`` for each drifted env key.

    Contract A's ``environment`` block is optional (old baselines lack it), so a
    missing or empty baseline yields no mismatches. Keys absent or ``None`` on
    *either* side are skipped — we can only compare values we actually have — so
    an un-probed ``chromium`` never produces a spurious warning.
    """
    if not baseline_env:
        return []
    mismatches: list[tuple[str, str, str]] = []
    for key in ENVIRONMENT_KEYS:
        base_val = baseline_env.get(key)
        cur_val = current_env.get(key)
        if base_val is None or cur_val is None:
            continue
        if base_val != cur_val:
            mismatches.append((key, str(base_val), str(cur_val)))
    return mismatches
