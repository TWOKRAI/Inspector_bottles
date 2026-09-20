"""integration_gate.py — deterministic S7 integration-gate checker.

Parses the machine-readable JSON block from integration.md produced by integrator agent.

Pre: report_file is a valid integration.md with fenced JSON block
Post: exit 0 iff mcp_available=false (advisory) OR
      (cycles_new=[], coverage_delta>=-5.0, godnode_growth_pct<=20);
      exit 1 otherwise (BLOCK)
Stability: lite

NOTE: This is a deterministic parser. LLM-based ai-judge agent — Phase 2.
"""

import argparse
import json
import re
import sys


def parse_json_block(report_text: str) -> dict:
    """Extract and parse the fenced ```json block from integration.md.

    Raises ValueError if the block is missing or contains invalid JSON.
    """
    # Match the first ```json ... ``` fenced block
    pattern = re.compile(r"```json\s*(.*?)```", re.DOTALL)
    match = pattern.search(report_text)
    if match is None:
        raise ValueError("malformed report: JSON block missing or invalid")
    raw_json = match.group(1).strip()
    try:
        return json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError("malformed report: JSON block missing or invalid") from exc


def evaluate(data: dict) -> list[str]:
    """Return a list of BLOCK reasons (empty list means PASS).

    Advisory pass: when mcp_available is False, return [] regardless of other fields.
    """
    # Advisory mode — no MCP data available, cannot enforce
    if not data.get("mcp_available", True):
        return []

    reasons: list[str] = []

    cycles_new = data.get("cycles_new", [])
    if len(cycles_new) > 0:
        reasons.append(f"new dependency cycles introduced: {cycles_new}")

    coverage_delta = data.get("coverage_delta", 0.0)
    if coverage_delta < -5.0:
        reasons.append(
            f"coverage dropped by {abs(coverage_delta):.2f}% (threshold: 5%)"
        )

    godnode_growth_pct = data.get("godnode_growth_pct", 0)
    if godnode_growth_pct > 20:
        reasons.append(
            f"god-node fan-in growth {godnode_growth_pct}% exceeds 20% threshold"
        )

    return reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic S7 integration gate — parses JSON block from integration.md."
    )
    parser.add_argument(
        "--report",
        required=True,
        metavar="FILE",
        help="Path to integration.md produced by the integrator agent.",
    )
    args = parser.parse_args(argv)

    try:
        with open(args.report, encoding="utf-8") as fh:
            report_text = fh.read()
    except OSError as exc:
        print(f"error: cannot read report file: {exc}", file=sys.stderr)
        return 1

    try:
        data = parse_json_block(report_text)
    except ValueError as exc:
        print(str(exc))
        return 1

    reasons = evaluate(data)
    if reasons:
        lines = ["VERDICT: BLOCK", "Reasons:"]
        for reason in reasons:
            lines.append(f"- {reason}")
        print("\n".join(lines))
        return 1

    print("VERDICT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
