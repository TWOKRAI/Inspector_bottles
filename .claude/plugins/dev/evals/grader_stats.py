#!/usr/bin/env python3
"""grader_stats.py — deterministic grading primitives for the reviewer eval.

Pure scoring helpers, shared by ``run_evals.py``. No I/O, no model calls — given a
parsed set of reviewer findings and a case's ground truth, compute the objective
"eval floor": recall of planted defects, precision against labelled decoys, F1, and
a Wilson score confidence interval for aggregating pass-rates across cases/trials.

Design notes (plan 2026-06-23_dev-plugin-upgrade, Task 3.c):
  - Grade the OUTCOME (the findings set + verdict), never the trajectory.
  - recall is the most-penalised axis: a missed planted defect is the worst failure.
  - precision is measured ONLY against labelled ``must_not_flag`` decoys, not against
    "any extra finding" — a reviewer may legitimately surface a real issue we did not
    plant, and that must not count as a false positive.
  - Wilson interval (not normal-approx) gives an honest CI on small n without scipy.

Stdlib-only. Python 3.11+. Cross-platform (Windows / WSL / Linux).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# z for a two-sided 95% confidence interval (standard normal quantile at 0.975).
_Z_95 = 1.959963984540054


@dataclass(frozen=True)
class Finding:
    """One reviewer finding or one ground-truth defect.

    ``file`` is matched by basename so a reviewer reporting ``db/users.py`` matches a
    ground-truth ``users.py``. ``category`` is one of the reviewer's closed 7-enum.
    ``line`` is the source line; matching tolerates a small window (reviewers and
    diffs disagree by a line or two). ``severity`` is optional (blocker/major/minor).
    """

    file: str
    line: int
    category: str
    severity: str | None = None


def _basename(path: str) -> str:
    """Last path segment, separator-agnostic and lowercased for tolerant matching."""
    norm = path.replace("\\", "/").rstrip("/")
    return norm.rsplit("/", 1)[-1].casefold()


def findings_match(reported: Finding, expected: Finding, line_window: int = 3) -> bool:
    """True if *reported* covers *expected*: same category, same file, near line."""
    if reported.category.casefold() != expected.category.casefold():
        return False
    if _basename(reported.file) != _basename(expected.file):
        return False
    return abs(reported.line - expected.line) <= line_window


@dataclass(frozen=True)
class Decoy:
    """A ``must_not_flag`` entry: a file (and optionally line) that is correct code.

    Flagging it is a false positive. ``line`` is None when the whole file is a decoy.
    """

    file: str
    line: int | None = None
    reason: str = ""


def decoy_hit(reported: Finding, decoy: Decoy, line_window: int = 3) -> bool:
    """True if *reported* flags the intentional/correct pattern described by *decoy*."""
    if _basename(reported.file) != _basename(decoy.file):
        return False
    if decoy.line is None:
        return True
    return abs(reported.line - decoy.line) <= line_window


@dataclass
class GradeResult:
    """Deterministic-floor scores for one reviewer output against one case."""

    recall: float
    precision: float
    f1: float
    matched: list[Finding] = field(default_factory=list)
    missed: list[Finding] = field(default_factory=list)
    false_positives: list[Finding] = field(default_factory=list)

    @property
    def floor_clean(self) -> bool:
        """The findings-level floor: caught every planted defect, flagged no decoy."""
        return not self.missed and not self.false_positives


def grade_findings(
    reported: list[Finding],
    must_find: list[Finding],
    must_not_flag: list[Decoy],
    line_window: int = 3,
) -> GradeResult:
    """Score reported findings against a case's ground truth.

    recall    = planted defects matched / total planted defects (1.0 if none planted).
    precision = matched-true / (matched-true + decoy hits); 1.0 when both are 0.
    f1        = harmonic mean of the two.
    """
    matched: list[Finding] = []
    missed: list[Finding] = []
    for expected in must_find:
        if any(findings_match(r, expected, line_window) for r in reported):
            matched.append(expected)
        else:
            missed.append(expected)

    false_positives = [
        r
        for r in reported
        if any(decoy_hit(r, d, line_window) for d in must_not_flag)
    ]

    recall = 1.0 if not must_find else len(matched) / len(must_find)

    true_pos = sum(
        1 for r in reported if any(findings_match(r, e, line_window) for e in must_find)
    )
    fp = len(false_positives)
    precision = 1.0 if (true_pos + fp) == 0 else true_pos / (true_pos + fp)

    f1 = (
        0.0
        if (precision + recall) == 0
        else 2 * precision * recall / (precision + recall)
    )

    return GradeResult(
        recall=recall,
        precision=precision,
        f1=f1,
        matched=matched,
        missed=missed,
        false_positives=false_positives,
    )


def wilson_interval(
    successes: int, trials: int, z: float = _Z_95
) -> tuple[float, float]:
    """Two-sided Wilson score confidence interval for a binomial proportion.

    Honest on small n where the normal approximation is wrong. Returns (0.0, 1.0)
    for zero trials (no information). Bounds are clamped to [0, 1].
    """
    if trials <= 0:
        return (0.0, 1.0)
    p = successes / trials
    z2 = z * z
    denom = 1.0 + z2 / trials
    centre = (p + z2 / (2.0 * trials)) / denom
    half = (z / denom) * math.sqrt(p * (1.0 - p) / trials + z2 / (4.0 * trials * trials))
    lo = max(0.0, centre - half)
    hi = min(1.0, centre + half)
    return (lo, hi)
