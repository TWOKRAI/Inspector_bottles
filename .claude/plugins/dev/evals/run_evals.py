#!/usr/bin/env python3
"""run_evals.py — golden-task eval harness for the dev-plugin code REVIEWER.

Grades the reviewer agent's OUTPUT (findings set + verdict) against a corpus of
golden cases sourced from real review failures. The deterministic floor is fully
stdlib/offline and needs no API key; the LLM-judge and live `claude -p` invocation
are scaffolded behind ``--judge`` / ``--invoke`` (lazy-imported, deferred — see
README). The default path imports nothing outside the standard library.

Pattern: Anthropic "Demystifying evals for AI agents" (grade the result not the
trajectory; reference solution per case proves catchability; pass^k headline for a
consistency-critical reviewer; ambiguous judge scores → human-review queue).

Modes:
  run_evals.py                        # suite run: grade each case's committed output
  run_evals.py --validate-cases       # per-PR offline gate: schema + self-consistency
  run_evals.py --output FILE --case ID   # grade one captured reviewer output
  run_evals.py --invoke               # (deferred) live `claude -p` per case, k trials
  run_evals.py --judge                # (deferred) add per-dimension LLM-judge scores

Exit codes: 0 = all cases pass / valid, 1 = failures, 2 = warnings under --strict.

Stdlib-only (default path). Python 3.11+. Cross-platform (Windows / WSL / Linux).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from grader_stats import Decoy, Finding, GradeResult, grade_findings, wilson_interval

# --- canonical vocabulary (mirrors reviewer.md) -----------------------------

# The reviewer's closed finding-category enum (reviewer.md "Response format").
REVIEWER_CATEGORIES: frozenset[str] = frozenset(
    {"spec", "architecture", "ipc", "security", "ui", "quality", "tests"}
)

# Case taxonomy: what dimension of reviewer behaviour each golden case probes.
CASE_CATEGORIES: frozenset[str] = frozenset(
    {
        "missed_bug",
        "false_positive_resistance",
        "severity_grading",
        "clean_diff",
        "escalation",
    }
)

VERDICTS: frozenset[str] = frozenset({"APPROVED", "CHANGES_REQUESTED", "ESCALATION"})

# Severity scale, canonical in reviewer.md "Severity scale" — kept here so the
# grader and the spec agree on one source of truth.
SEVERITY_BY_CATEGORY: dict[str, str] = {
    "security": "blocker",
    "spec": "blocker",
    "architecture": "major",
    "ipc": "major",
    "ui": "major",
    "tests": "major",
    "quality": "minor",
}

# Finding line, lifted from reviewer.md:211
#   `N. [path/file.py:42] [category] — Problem: <desc>. Fix: <solution>`
# Tolerant on the dash (em / en / hyphen) for prose drift.
_FINDING_RE = re.compile(
    r"^\s*\d+\.\s*\[(?P<file>[^\]:]+):(?P<line>\d+)\]\s*"
    r"\[(?P<category>[^\]]+)\]\s*[—–-]+\s*(?P<rest>.*)$"
)

# Boundary-discipline violations: the reviewer must not write code or do git ops.
_GIT_OP_RE = re.compile(r"^\s*git\s+(commit|push|add|reset|checkout|merge|rebase)\b")
_DIFF_FENCE_RE = re.compile(r"^```+\s*(diff|patch)\b")


# --- data model -------------------------------------------------------------


@dataclass
class Case:
    """One golden task: spec + on-disk fixtures + ground truth."""

    id: str
    category: str
    description: str
    source: str
    prompt: str
    expected_verdict: str
    diff_path: Path
    reference_review_path: Path
    must_find: list[Finding]
    must_not_flag: list[Decoy]
    difficulty: str
    tags: list[str]
    raw: dict[str, Any]


@dataclass
class ParsedReview:
    """A reviewer output decomposed into its gradeable parts."""

    verdict: str
    findings: list[Finding]
    format_issues: list[str] = field(default_factory=list)
    boundary_ok: bool = True

    @property
    def format_ok(self) -> bool:
        return not self.format_issues


@dataclass
class CaseOutcome:
    """The grade for one reviewer output against one case."""

    case_id: str
    expected_verdict: str
    actual_verdict: str
    verdict_ok: bool
    grade: GradeResult
    format_ok: bool
    boundary_ok: bool
    passed: bool
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "expected_verdict": self.expected_verdict,
            "actual_verdict": self.actual_verdict,
            "verdict_ok": self.verdict_ok,
            "recall": round(self.grade.recall, 4),
            "precision": round(self.grade.precision, 4),
            "f1": round(self.grade.f1, 4),
            "missed": [f"{f.file}:{f.line} [{f.category}]" for f in self.grade.missed],
            "false_positives": [
                f"{f.file}:{f.line} [{f.category}]" for f in self.grade.false_positives
            ],
            "format_ok": self.format_ok,
            "boundary_ok": self.boundary_ok,
            "passed": self.passed,
            "notes": self.notes,
        }


# --- parsing ----------------------------------------------------------------


def parse_review(text: str) -> ParsedReview:
    """Decompose a reviewer output into verdict + findings + format/boundary flags.

    Grades the RESULT only — no assertion about tool order or file-read sequence.
    """
    lines = text.splitlines()

    if any("ESCALATION TO TEAMLEAD" in line for line in lines):
        verdict = "ESCALATION"
    elif any("CHANGES REQUESTED" in line for line in lines):
        verdict = "CHANGES_REQUESTED"
    elif any(re.match(r"^\s*APPROVED\s*$", line) for line in lines):
        verdict = "APPROVED"
    else:
        verdict = "UNKNOWN"

    findings: list[Finding] = []
    format_issues: list[str] = []
    for raw_line in lines:
        m = _FINDING_RE.match(raw_line)
        if not m:
            continue
        category = m.group("category").strip()
        rest = m.group("rest")
        if category.casefold() not in REVIEWER_CATEGORIES:
            format_issues.append(f"unknown category [{category}] in: {raw_line.strip()}")
        if "Problem:" not in rest or "Fix:" not in rest:
            format_issues.append(
                f"finding missing Problem:/Fix: in: {raw_line.strip()}"
            )
        findings.append(
            Finding(
                file=m.group("file").strip(),
                line=int(m.group("line")),
                category=category.casefold(),
            )
        )

    if verdict == "CHANGES_REQUESTED" and not findings:
        format_issues.append("CHANGES REQUESTED with no parseable findings")

    boundary_ok = not any(
        _GIT_OP_RE.match(line) or _DIFF_FENCE_RE.match(line) for line in lines
    )

    return ParsedReview(
        verdict=verdict,
        findings=findings,
        format_issues=format_issues,
        boundary_ok=boundary_ok,
    )


# --- case loading -----------------------------------------------------------


def _finding_from(obj: dict[str, Any]) -> Finding:
    return Finding(
        file=str(obj["file"]),
        line=int(obj["line"]),
        category=str(obj["category"]).casefold(),
        severity=obj.get("severity"),
    )


def _decoy_from(obj: dict[str, Any]) -> Decoy:
    line = obj.get("line")
    return Decoy(
        file=str(obj["file"]),
        line=None if line is None else int(line),
        reason=str(obj.get("reason", "")),
    )


def load_case(case_path: Path) -> Case:
    """Load and shallow-validate one cr-NN.json into a Case (fixtures resolved)."""
    raw: dict[str, Any] = json.loads(case_path.read_text(encoding="utf-8"))
    base = case_path.parent.parent  # cases/ -> reviewer/
    gt: dict[str, Any] = raw.get("ground_truth", {})
    return Case(
        id=str(raw["id"]),
        category=str(raw["category"]),
        description=str(raw.get("description", "")),
        source=str(raw.get("source", "")),
        prompt=str(raw.get("prompt", "")),
        expected_verdict=str(raw["expected_verdict"]),
        diff_path=(base / str(raw["diff_path"])).resolve(),
        reference_review_path=(base / str(raw["reference_review_path"])).resolve(),
        must_find=[_finding_from(f) for f in gt.get("must_find", [])],
        must_not_flag=[_decoy_from(d) for d in gt.get("must_not_flag", [])],
        difficulty=str(raw.get("difficulty", "")),
        tags=[str(t) for t in raw.get("tags", [])],
        raw=raw,
    )


def discover_cases(cases_dir: Path) -> list[Case]:
    return [load_case(p) for p in sorted(cases_dir.glob("cr-*.json"))]


# --- grading ----------------------------------------------------------------


def grade_case(case: Case, review_text: str, line_window: int = 3) -> CaseOutcome:
    """Apply the deterministic floor to one reviewer output against one case."""
    parsed = parse_review(review_text)
    grade = grade_findings(
        parsed.findings, case.must_find, case.must_not_flag, line_window
    )
    verdict_ok = parsed.verdict == case.expected_verdict

    notes: list[str] = []
    if grade.missed:
        notes.append(f"FALSE NEGATIVE: {len(grade.missed)} planted defect(s) missed")
    if grade.false_positives:
        notes.append(
            f"FALSE POSITIVE: flagged {len(grade.false_positives)} must_not_flag decoy(s)"
        )
    if not verdict_ok:
        notes.append(
            f"VERDICT: expected {case.expected_verdict}, got {parsed.verdict}"
        )
    notes.extend(parsed.format_issues)
    if not parsed.boundary_ok:
        notes.append("BOUNDARY: output contains a code patch or git operation")

    # Deterministic floor: caught every planted defect, flagged no decoy, right
    # verdict, well-formed, stayed in bounds.
    passed = (
        grade.floor_clean
        and verdict_ok
        and parsed.format_ok
        and parsed.boundary_ok
    )

    return CaseOutcome(
        case_id=case.id,
        expected_verdict=case.expected_verdict,
        actual_verdict=parsed.verdict,
        verdict_ok=verdict_ok,
        grade=grade,
        format_ok=parsed.format_ok,
        boundary_ok=parsed.boundary_ok,
        passed=passed,
        notes=notes,
    )


# --- case validation (per-PR offline gate) ----------------------------------


def validate_cases(cases_dir: Path) -> list[str]:
    """Schema + self-consistency check; returns a list of error strings (empty = ok).

    Self-consistency = each case's reference_review.md, graded against the case,
    must score a perfect floor (recall 1.0, zero decoy hits, verdict match). This
    enforces the Anthropic invariant: the reference solution proves the planted bug
    is catchable AND that the graders fire on a known-good output.
    """
    errors: list[str] = []
    seen_ids: set[str] = set()
    cases = discover_cases(cases_dir)
    if not cases:
        return [f"no cr-*.json cases found under {cases_dir}"]

    for case in cases:
        cid = case.id
        if not re.fullmatch(r"cr-\d{3}", cid):
            errors.append(f"{cid}: id must match cr-NNN")
        if cid in seen_ids:
            errors.append(f"{cid}: duplicate id")
        seen_ids.add(cid)
        if case.category not in CASE_CATEGORIES:
            errors.append(f"{cid}: category {case.category!r} not in {sorted(CASE_CATEGORIES)}")
        if case.expected_verdict not in VERDICTS:
            errors.append(f"{cid}: expected_verdict {case.expected_verdict!r} invalid")
        if not case.diff_path.is_file():
            errors.append(f"{cid}: diff_path missing: {case.diff_path}")
        if not case.reference_review_path.is_file():
            errors.append(f"{cid}: reference_review_path missing")
            continue
        for f in case.must_find:
            if f.category not in REVIEWER_CATEGORIES:
                errors.append(f"{cid}: must_find category {f.category!r} not in reviewer enum")
            if f.severity is not None and f.severity not in {"blocker", "major", "minor"}:
                errors.append(f"{cid}: must_find severity {f.severity!r} invalid")

        # self-consistency: grade the reference review
        ref_text = case.reference_review_path.read_text(encoding="utf-8")
        outcome = grade_case(case, ref_text)
        if not outcome.passed:
            errors.append(
                f"{cid}: reference review does NOT pass its own floor "
                f"({'; '.join(outcome.notes) or 'unknown'}) — case is mis-specified"
            )
    return errors


# --- suite run --------------------------------------------------------------


def review_text_for(case: Case) -> tuple[str, str]:
    """Return (review_text, source-label) for a case in offline mode.

    Prefers a committed captured reviewer output (fixtures/<id>/captured_review.md);
    falls back to the reference review (a self-check, expected to pass perfectly).
    """
    captured = case.reference_review_path.parent / "captured_review.md"
    if captured.is_file():
        return captured.read_text(encoding="utf-8"), "captured"
    return case.reference_review_path.read_text(encoding="utf-8"), "reference"


def run_suite(cases_dir: Path) -> list[tuple[CaseOutcome, str]]:
    results: list[tuple[CaseOutcome, str]] = []
    for case in discover_cases(cases_dir):
        text, source = review_text_for(case)
        results.append((grade_case(case, text), source))
    return results


# --- output -----------------------------------------------------------------


def _emit(outcomes: list[tuple[CaseOutcome, str]], quiet: bool) -> None:
    for outcome, source in outcomes:
        tag = "[OK]" if outcome.passed else "[FAIL]"
        if quiet and outcome.passed:
            continue
        print(
            f"{tag} {outcome.case_id} ({source}): recall={outcome.grade.recall:.2f} "
            f"precision={outcome.grade.precision:.2f} verdict={outcome.actual_verdict}"
        )
        if not outcome.passed:
            for note in outcome.notes:
                print(f"       - {note}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--cases-dir",
        default=None,
        help="Directory of cr-*.json cases (default: reviewer/cases next to script)",
    )
    parser.add_argument(
        "--validate-cases",
        action="store_true",
        help="Offline schema + self-consistency check (per-PR gate, no API key).",
    )
    parser.add_argument("--output", default=None, help="Grade one captured output file.")
    parser.add_argument("--case", default=None, help="Case id for --output (e.g. cr-001).")
    parser.add_argument("--out", default=None, help="Write results JSON to this dir.")
    parser.add_argument("--quiet", action="store_true", help="Print only failures.")
    parser.add_argument(
        "--strict", action="store_true", help="Treat warnings as exit 2."
    )
    parser.add_argument(
        "--invoke",
        action="store_true",
        help="(deferred) live-invoke the reviewer via `claude -p` — not wired in v1.",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="(deferred) add per-dimension LLM-judge scores — not wired in v1.",
    )
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    cases_dir = (
        Path(args.cases_dir)
        if args.cases_dir
        else script_dir / "reviewer" / "cases"
    )
    if not cases_dir.is_dir():
        print(f"[FAIL] cases dir not found: {cases_dir}", file=sys.stderr)
        return 1

    if args.invoke or args.judge:
        print(
            "[FAIL] --invoke / --judge are deferred (Phase 3.c follow-up): the live "
            "reviewer invocation and LLM-judge are not wired in the offline-floor v1. "
            "See evals/README.md.",
            file=sys.stderr,
        )
        return 1

    if args.validate_cases:
        errors = validate_cases(cases_dir)
        if errors:
            for e in errors:
                print(f"[FAIL] {e}")
            print(f"\n[FAIL] {len(errors)} case validation error(s).")
            return 1
        n = len(discover_cases(cases_dir))
        if not args.quiet:
            print(f"[OK] {n} golden case(s) valid and self-consistent.")
        return 0

    if args.output:
        if not args.case:
            print("[FAIL] --output requires --case <id>", file=sys.stderr)
            return 1
        case_path = cases_dir / f"{args.case}.json"
        if not case_path.is_file():
            print(f"[FAIL] case not found: {case_path}", file=sys.stderr)
            return 1
        case = load_case(case_path)
        text = Path(args.output).read_text(encoding="utf-8")
        outcomes = [(grade_case(case, text), "output")]
    else:
        outcomes = run_suite(cases_dir)

    _emit(outcomes, args.quiet)

    passed = sum(1 for o, _ in outcomes if o.passed)
    total = len(outcomes)
    lo, hi = wilson_interval(passed, total)

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "passed": passed,
            "total": total,
            "pass_rate": round(passed / total, 4) if total else 0.0,
            "wilson_95": [round(lo, 4), round(hi, 4)],
            "cases": [o.to_dict() for o, _ in outcomes],
        }
        (out_dir / "scores.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    if not args.quiet:
        print(
            f"\n[INFO] {passed}/{total} passed "
            f"(Wilson 95% CI {lo:.2f}-{hi:.2f})."
        )

    if passed < total:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
