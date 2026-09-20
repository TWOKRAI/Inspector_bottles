"""red_gate.py — deterministic RED-gate checker for S3 pipeline stage.

Parses pytest stdout to verify that a test is in genuine RED state.

Pre: report_file exists and contains pytest stdout/stderr capture
Post: exit 0 iff at least one test FAILED with NotImplementedError or AssertionError;
      exit 1 otherwise (all passed, or setup error like ImportError/SyntaxError)
Stability: lite

NOTE: This is a deterministic parser. LLM-based ai-judge agent — Phase 2.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Patterns used to classify pytest output
# ---------------------------------------------------------------------------

# Matches the pytest summary line, e.g. "1 failed, 2 passed in 0.05s"
_FAILED_PATTERN: re.Pattern[str] = re.compile(r"\d+\s+failed", re.IGNORECASE)

# Signals a genuine RED test (test intent expressed, not setup error)
_PASS_ERRORS: tuple[str, ...] = ("NotImplementedError", "AssertionError")

# Signals broken setup — gate should BLOCK
_BLOCK_ERRORS: tuple[str, ...] = ("ImportError", "SyntaxError")


def _classify(text: str) -> tuple[str, str]:
    """Classify pytest output text into PASS or BLOCK with a reason string.

    Returns:
        ("PASS", "") if at least one FAILED with NotImplementedError or AssertionError.
        ("BLOCK", reason) otherwise.

    The caller is responsible for non-empty text guard.
    """
    has_failed = bool(_FAILED_PATTERN.search(text))

    if not has_failed:
        # All tests passed (no FAILED line) — the test is not genuinely RED.
        return ("BLOCK", "No FAILED tests found — test is not in RED state")

    # At least one test FAILED. Check error types.
    has_pass_error = any(err in text for err in _PASS_ERRORS)
    has_block_error = any(err in text for err in _BLOCK_ERRORS)

    if has_pass_error:
        # NotImplementedError or AssertionError confirms genuine RED — PASS.
        return ("PASS", "")

    if has_block_error:
        found = [err for err in _BLOCK_ERRORS if err in text]
        reason = f"Setup error(s) detected: {', '.join(found)}"
        return ("BLOCK", reason)

    # FAILED but no recognised error type — treat as BLOCK (unclear state).
    return ("BLOCK", "FAILED but no NotImplementedError/AssertionError detected")


def run(report_path: Path) -> int:
    """Parse *report_path* and print VERDICT to stdout.

    Returns:
        0 — PASS (test is in genuine RED state)
        1 — BLOCK (test is not RED, or setup is broken)
    """
    if not report_path.exists():
        print(f"VERDICT: BLOCK\nReason: Report file not found: {report_path}")
        return 1

    text = report_path.read_text(encoding="utf-8", errors="replace").strip()

    if not text:
        print("VERDICT: BLOCK\nReason: Empty report")
        return 1

    verdict, reason = _classify(text)

    if verdict == "PASS":
        print("VERDICT: PASS")
        return 0

    print(f"VERDICT: BLOCK\nReason: {reason}")
    return 1


def main() -> None:
    """CLI entry point.

    Usage::

        python scripts/red_gate.py --report /tmp/red_out.txt

    Exits 0 (PASS) or 1 (BLOCK).
    """
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic RED-gate checker for S3 pipeline stage.\n"
            "Parses pytest stdout saved to a file and decides PASS or BLOCK.\n"
            "Exit 0 = PASS (genuine RED); Exit 1 = BLOCK."
        )
    )
    parser.add_argument(
        "--report",
        metavar="FILE",
        required=True,
        help="Path to file containing pytest stdout/stderr capture.",
    )
    args = parser.parse_args()

    sys.exit(run(Path(args.report)))


if __name__ == "__main__":
    main()
