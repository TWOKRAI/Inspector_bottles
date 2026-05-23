#!/usr/bin/env python3
"""Commit message validator (portable, seed-shipped).

Checks:
1. Subject in Conventional Commits format: `<type>(<scope>): <subject>`
2. Blank line between subject and body.
3. Required trailers: `Why:` and `Layer:` (with allowed values).
4. Optional trailers (if present) — valid format: `Risk:`, `Reversible:`, `Tested:`, `Refs:`, `Rejected:`.

Layer values are loaded from .claude/commit-layers.txt (one layer per line,
'#' for comments). Fallback to a generic default if the file is absent —
this keeps the validator usable in a brand-new project before customization.

Usage:
    python scripts/validate_commit/validate_commit.py <path-to-commit-msg-file>
    git log -1 --format=%B | python scripts/validate_commit/validate_commit.py -

Used as git commit-msg hook (see scripts/validate_commit/install_hook.sh).
Exit 0 — OK, exit 1 — validation failed.

Skipped: merge commits (Merge ..., merge: ...), reverts, fixup!/squash!/amend!.
"""

from __future__ import annotations

import re
import subprocess
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

# Generic defaults. Override by writing layers (one per line) to
# .claude/commit-layers.txt at the project root.
DEFAULT_LAYERS = {
    "app",
    "lib",
    "tests",
    "docs",
    "scripts",
    "infra",
    "build",
    "ci",
    "mixed",
}

LAYERS_CONFIG_REL = ".claude/commit-layers.txt"

# Branches matching `<conv-type>/<slug>` are treated as plan-driven; if a plan
# exists at plans/<slug>.md (or plans/<slug>/plan.md), the commit MUST include
# `Refs: plans/<slug>...`. See .claude/commands/dev/plan.md for the workflow.
BRANCH_SLUG_RE = re.compile(r"^(?:feat|fix|refactor|docs|test|chore|perf|build|ci|style|revert)/(?P<slug>.+)$")

ALLOWED_RISK = {"low", "medium", "high"}
ALLOWED_REVERSIBLE = {"yes", "no", "migration-needed"}

SUBJECT_RE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[a-z0-9_\-/,\s]+)\))?(?P<breaking>!)?: (?P<subject>.+)$")
TRAILER_RE = re.compile(r"^([A-Z][A-Za-z\-]*): (.+)$")

REQUIRED_BASE_TRAILERS = {"Why"}
KNOWN_TRAILERS = REQUIRED_BASE_TRAILERS | {
    "Layer",
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


def find_repo_root() -> Path | None:
    """First ancestor of CWD that contains .git."""
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def current_branch(repo_root: Path) -> str | None:
    """Current branch name via symbolic-ref. None for detached HEAD or errors."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "symbolic-ref", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def plan_for_branch(repo_root: Path, branch: str) -> str | None:
    """Relative path to the plan file for this branch's slug, or None.

    Branch must match `<conv-type>/<slug>`; plan must exist at one of:
      plans/<slug>.md
      plans/<slug>/plan.md
    """
    m = BRANCH_SLUG_RE.match(branch)
    if not m:
        return None
    slug = m.group("slug")
    for rel in (f"plans/{slug}.md", f"plans/{slug}/plan.md"):
        if (repo_root / rel).exists():
            return rel
    return None


def load_allowed_layers() -> set[str] | None:
    """Read layer whitelist from .claude/commit-layers.txt.

    Returns:
        - set of layer names if config exists with at least one non-comment line
        - empty set if config exists but is empty / comments-only → `Layer:` is OPTIONAL
        - set of DEFAULT_LAYERS if config is absent → `Layer:` is required, generic values

    Searches upwards from CWD for the project root (first ancestor containing .git).
    """
    cwd = Path.cwd().resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            config = parent / LAYERS_CONFIG_REL
            if config.exists():
                lines = config.read_text(encoding="utf-8").splitlines()
                layers = {line.strip() for line in lines if line.strip() and not line.strip().startswith("#")}
                return layers  # may be empty → Layer trailer optional
            break
    return set(DEFAULT_LAYERS)


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


def validate(
    text: str,
    allowed_layers: set[str] | None = None,
    plan_path: str | None | object = ...,  # sentinel to allow None as "no plan"
) -> ValidationResult:
    result = ValidationResult()
    text = text.strip()

    if not text:
        result.errors.append("Empty commit message")
        return result

    first_line = text.splitlines()[0]
    if any(first_line.startswith(p) for p in SKIP_PREFIXES):
        return result  # merge/revert/fixup — skip validation

    layers = allowed_layers if allowed_layers is not None else load_allowed_layers()
    layer_required = bool(layers)
    required = REQUIRED_BASE_TRAILERS | ({"Layer"} if layer_required else set())

    # Resolve plan for current branch (if not explicitly provided).
    if plan_path is ...:
        repo = find_repo_root()
        branch = current_branch(repo) if repo else None
        plan_path = plan_for_branch(repo, branch) if (repo and branch) else None

    subject, _body, trailers = parse_message(text)

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
    missing = required - set(trailers.keys())
    if missing:
        hint = "    Why: one line about motivation"
        if "Layer" in missing:
            hint += f"\n    Layer: {' | '.join(sorted(layers))}"
        result.errors.append(
            f"Missing required trailers: {sorted(missing)}.\n  Add at end of message (after blank line):\n{hint}"
        )

    # 4. Trailer value validation
    if "Layer" in trailers and layer_required:
        for val in trailers["Layer"]:
            given = {x.strip() for x in val.split(",") if x.strip()}
            unknown = given - layers
            if unknown:
                result.errors.append(
                    f"Layer: unknown values {sorted(unknown)}. Allowed: {sorted(layers)}\n"
                    f"  (configure via {LAYERS_CONFIG_REL})"
                )

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

    # 6. Plan-driven workflow: if branch has a plan, require matching Refs trailer.
    if plan_path:
        refs = trailers.get("Refs", [])
        # Plan path without extension: `plans/<slug>` (works for both
        # `plans/<slug>.md` and `plans/<slug>/plan.md` / `phase-N.md`).
        plan_prefix = plan_path.rsplit("/plan.md", 1)[0].rsplit(".md", 1)[0]
        if not any(plan_prefix in val for val in refs):
            result.errors.append(
                f"Branch has a plan ({plan_path}) but commit is missing matching "
                f"`Refs:` trailer.\n"
                f"  Add: Refs: {plan_path}\n"
                f"  (or for multi-phase plans, ref the specific phase file)"
            )

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
        sys.stderr.write("\nGuide: .claude/COMMIT_GUIDE.md\nBypass (merge/rebase only): git commit --no-verify\n")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
