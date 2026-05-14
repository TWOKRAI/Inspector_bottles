#!/usr/bin/env python3
"""Commit message validator for Inspector_bottles.

Checks:
1. Subject in Conventional Commits format: `<type>(<scope>): <subject>`
2. Blank line between subject and body.
3. Required trailers: `Why:` and `Layer:` (with allowed values).
4. Optional trailers (if present) — valid format: `Risk:`, `Reversible:`, `Tested:`, `Refs:`, `Rejected:`.

Usage:
    python scripts/validate_commit/validate_commit.py <path-to-commit-msg-file>
    git log -1 --format=%B | python scripts/validate_commit/validate_commit.py -

Used as git commit-msg hook (see scripts/validate_commit/install_hook.sh).
Exit 0 — OK, exit 1 — validation failed.

Skipped: merge commits (Merge ..., merge: ...), reverts, fixup!/squash!/amend!.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ────────────────────────── Config ──────────────────────────

ALLOWED_TYPES = {
    "feat",
    "fix",
    "refactor",
    "docs",
    "test",
    "chore",
    "perf",
    "build",
    "ci",
    "style",
    "revert",
}

ALLOWED_LAYERS = {
    "framework",
    "services",
    "plugins",
    "prototype",
    "docs",
    "scripts",
    "tests",
    "infra",
    "mixed",
}

ALLOWED_RISK = {"low", "medium", "high"}
ALLOWED_REVERSIBLE = {"yes", "no", "migration-needed"}

SUBJECT_RE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[a-z0-9_\-/,\s]+)\))?(?P<breaking>!)?: (?P<subject>.+)$")
TRAILER_RE = re.compile(r"^([A-Z][A-Za-z\-]*): (.+)$")

REQUIRED_TRAILERS = {"Why", "Layer"}
KNOWN_TRAILERS = REQUIRED_TRAILERS | {
    "Refs",
    "Risk",
    "Reversible",
    "Tested",
    "Rejected",
    "Co-Authored-By",
    "Signed-off-by",
    "Reviewed-by",
}

SKIP_PREFIXES = ("Merge ", "merge: ", "Revert ", "fixup!", "squash!", "amend!")


# ────────────────────────── Structures ──────────────────────────


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# ────────────────────────── Parsing ──────────────────────────


def parse_message(text: str) -> tuple[str, list[str], dict[str, list[str]]]:
    """Return (subject, body_lines, trailers).

    Split into paragraphs by blank lines. Walk from the end — while the last
    paragraph consists entirely of trailer lines, treat it as a trailer block.
    This allows multiple trailer paragraphs (e.g., business trailers +
    separate Co-Authored-By at the bottom).

    trailers — dict[key -> list[values]] (one key can appear multiple times).
    """
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines:
        return "", [], {}

    subject = lines[0]
    rest = lines[1:]
    if rest and not rest[0].strip():
        rest = rest[1:]

    paragraphs: list[list[str]] = []
    current: list[str] = []
    for ln in rest:
        if not ln.strip():
            if current:
                paragraphs.append(current)
                current = []
        else:
            current.append(ln)
    if current:
        paragraphs.append(current)

    trailers: dict[str, list[str]] = {}
    while paragraphs:
        last = paragraphs[-1]
        if all(TRAILER_RE.match(line) for line in last):
            for line in last:
                m = TRAILER_RE.match(line)
                if m:
                    key, val = m.group(1), m.group(2).strip()
                    trailers.setdefault(key, []).append(val)
            paragraphs.pop()
        else:
            break

    body: list[str] = []
    for i, p in enumerate(paragraphs):
        if i > 0:
            body.append("")
        body.extend(p)

    return subject, body, trailers


# ────────────────────────── Validation ──────────────────────────


def validate(text: str) -> ValidationResult:
    result = ValidationResult()
    text = text.strip()

    if not text:
        result.errors.append("Empty commit message")
        return result

    first_line = text.splitlines()[0]
    if any(first_line.startswith(p) for p in SKIP_PREFIXES):
        return result  # merge/revert/fixup — skip validation

    subject, body, trailers = parse_message(text)

    # 1. Subject format
    if not subject:
        result.errors.append("Empty subject (first line)")
        return result

    m = SUBJECT_RE.match(subject)
    if not m:
        result.errors.append(
            f"Subject not in Conventional Commits format.\n"
            f"  Got: '{subject}'\n"
            f"  Expected: <type>(<scope>): <description>\n"
            f"  Example: feat(auth): add wildcard to has_permission"
        )
        return result

    t = m.group("type")
    if t not in ALLOWED_TYPES:
        result.errors.append(f"Unknown type '{t}'. Allowed: {sorted(ALLOWED_TYPES)}")

    # 2. Blank line between subject and body
    full_lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    if len(full_lines) >= 2 and full_lines[1].strip():
        result.errors.append("Missing blank line between subject and body")

    # 3. Required trailers
    missing = REQUIRED_TRAILERS - set(trailers.keys())
    if missing:
        result.errors.append(
            f"Missing required trailers: {sorted(missing)}.\n"
            f"  Add at end of message (after blank line):\n"
            f"    Why: one line about motivation\n"
            f"    Layer: framework | services | plugins | prototype | docs | scripts | tests"
        )

    # 4. Trailer value validation
    if "Layer" in trailers:
        for val in trailers["Layer"]:
            layers = {x.strip() for x in val.split(",") if x.strip()}
            unknown = layers - ALLOWED_LAYERS
            if unknown:
                result.errors.append(f"Layer: unknown values {sorted(unknown)}. Allowed: {sorted(ALLOWED_LAYERS)}")

    if "Risk" in trailers:
        for val in trailers["Risk"]:
            level = val.split("—")[0].split("-")[0].strip().lower()
            if level not in ALLOWED_RISK:
                result.warnings.append(f"Risk: '{val}'. Expected to start with low/medium/high")

    if "Reversible" in trailers:
        for val in trailers["Reversible"]:
            level = val.split("—")[0].strip().lower()
            if level not in ALLOWED_REVERSIBLE:
                result.warnings.append(f"Reversible: '{val}'. Expected: yes | no | migration-needed")

    # 5. Unknown trailers — warning (don't block, extensible)
    for key in trailers:
        if key not in KNOWN_TRAILERS:
            result.warnings.append(f"Unknown trailer '{key}:'. Known: {sorted(KNOWN_TRAILERS)}")

    if "Why" in trailers:
        for val in trailers["Why"]:
            if len(val) < 5:
                result.warnings.append(f"Why: too brief ('{val}'). Describe motivation in at least one phrase")

    return result


# ────────────────────────── CLI ──────────────────────────


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("Usage: validate_commit.py <file>\n       echo '...' | validate_commit.py -\n")
        return 2

    src = argv[1]
    text = sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")

    result = validate(text)

    if result.warnings:
        sys.stderr.write("WARNING:\n")
        for w in result.warnings:
            sys.stderr.write(f"  - {w}\n")

    if result.errors:
        sys.stderr.write("\nERROR: Commit message is invalid:\n")
        for e in result.errors:
            sys.stderr.write(f"  - {e}\n")
        sys.stderr.write(
            "\nTemplate: .gitmessage  |  Guide: docs/claude/COMMIT_GUIDE.md\n"
            "Bypass (merge/rebase only): git commit --no-verify\n"
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
