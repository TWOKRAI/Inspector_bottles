"""
lint_namespacing.py — Anti-regression lint for flat command names in plugin content.

Purpose:
    Scan ``.claude/plugins/**/{agents,commands,modes}/**/*.md`` and report any
    legacy flat slash-commands that must be replaced with their namespaced form
    (e.g. ``/plan`` → ``/dev:plan``).

Public API:
    scan_directory(root: Path) -> list[Violation]
    main() -> None  (CLI entry point, exits with code 0 or 1)

Stability: lite

Source-of-truth for the flat-name set is the table in
``docs/plugin-namespacing.md`` §3 «flat → namespaced».
This set is intentionally hard-coded here rather than parsed from the doc
because parsing Markdown tables is fragile; the doc itself is the authoritative
human reference while this module is the machine-checkable guard.

Inline-ignore:
    A line containing ``<!-- lint-namespacing: ignore -->`` is silently skipped,
    to allow legitimate citations of legacy names inside plugin docs.

Scope:
    Files under an ``agents/``, ``commands/``, ``modes/``, ``skills/``, or
    ``templates/`` subdir, plus the four root docs (CLAUDE/STACK/BOOTSTRAP/
    COMMIT_GUIDE). Fenced code blocks (``` / ~~~) are skipped so path-like
    examples (gitignore patterns, REST routes) do not false-positive.
    Free-form README/SETUP_GUIDE and hook .sh scripts are out of scope.

Exit codes:
    0 — no violations found
    1 — one or more violations found (printed to stdout)
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Source-of-truth flat-name set (refs: docs/plugin-namespacing.md §3)
# Each entry maps flat-name -> suggested namespaced replacement.
# ---------------------------------------------------------------------------

FLAT_TO_NAMESPACED: dict[str, str] = {
    # Plugin: dev
    "plan": "/dev:plan",
    "implement": "/dev:implement",
    "ship": "/dev:ship",
    "review": "/dev:review",
    "test": "/dev:test",
    "debug": "/dev:debug",
    "pipeline": "/dev:pipeline",
    "plan-status": "/dev:plan-status",
    "adr": "/dev:adr",
    "spec": "/dev:spec:spec",
    "spec-sync": "/dev:spec:spec-sync",
    # Plugin: core (memory sub-group)
    "memory:init": "/core:memory:init",
    "memory:search": "/core:memory:search",
    "memory:status": "/core:memory:status",
    "memory:remember": "/core:memory:remember",
    # Plugin: core (quality sub-group)
    "doctor": "/core:quality:doctor",
    "arch-review": "/core:quality:arch-review",
    "lint-agents": "/core:quality:lint-agents",
    "lint-settings": "/core:quality:lint-settings",
    "code-stats": "/core:quality:code-stats",
    "code-stats-tokei": "/core:quality:code-stats-tokei",
    "test-ratio": "/core:quality:test-ratio",
    "secrets-audit": "/core:quality:secrets-audit",
    "link-check": "/core:quality:link-check",
    "claude-md-audit": "/core:quality:claude-md-audit",
    "changelog-gen": "/core:quality:changelog-gen",
    "sync-context": "/core:quality:sync-context",
    # Plugin: core (team sub-group)
    "handoff": "/core:team:handoff",
    "wrap-up": "/core:team:wrap-up",
    "hire": "/core:team:hire",
    "docs": "/core:team:docs",
    "team": "/core:team:team",
    # Plugin: core (docs sub-group)
    "ru-mirror": "/core:docs:ru-mirror",
    # Plugin: core (analysis / infra)
    "todo-inventory": "/core:analysis:todo-inventory",
    "cold-start": "/core:infra:cold-start",
    "clean-cache": "/core:infra:clean-cache",
    "diagrams": "/core:infra:diagrams",
    "fw-test": "/core:infra:fw-test",
    "run-proto": "/core:infra:run-proto",
    # Plugin: core (plugin sub-group)
    "plugin:list": "/core:plugin:list",
    "plugin:install": "/core:plugin:install",
    "plugin:update": "/core:plugin:update",
    "plugin:remove": "/core:plugin:remove",
    "plugin:enable": "/core:plugin:enable",
    "plugin:disable": "/core:plugin:disable",
    "plugin:sync": "/core:plugin:sync",
    "plugin:doctor": "/core:plugin:doctor",
    "plugin:info": "/core:plugin:info",
    "plugin:pin": "/core:plugin:pin",
    # Plugin: knowledge
    "curate": "/knowledge:curate",
    "research": "/knowledge:research",
    "synthesize": "/knowledge:synthesize",
    "transcribe": "/knowledge:transcribe",
    "translate": "/knowledge:translate",
    "library": "/knowledge:library",
    "search": "/knowledge:search",
    "compress": "/knowledge:compress",
    "digest": "/knowledge:digest",
    # Plugin: mcp-sentrux
    "sentrux-check": "/mcp-sentrux:sentrux-check",
    "sentrux-baseline": "/mcp-sentrux:sentrux-baseline",
    "sentrux-diff": "/mcp-sentrux:sentrux-diff",
    "sentrux-dsm": "/mcp-sentrux:sentrux-dsm",
    "sentrux-evolution": "/mcp-sentrux:sentrux-evolution",
    "sentrux-gaps": "/mcp-sentrux:sentrux-gaps",
    "sentrux-health": "/mcp-sentrux:sentrux-health",
    "sentrux-rules": "/mcp-sentrux:sentrux-rules",
    "install-pre-push": "/mcp-sentrux:install-pre-push",
    # Plugin: mcp-qex
    "qex-status": "/mcp-qex:qex-status",
    "qex-reindex": "/mcp-qex:qex-reindex",
    "qex-rebuild": "/mcp-qex:qex-rebuild",
    # Plugin: security (seed-max-improvement Phase 1)
    "scan": "/security:scan",
    "cve": "/security:cve",
    "sbom": "/security:sbom",
}

# ---------------------------------------------------------------------------
# Compile regex patterns once at module load
# ---------------------------------------------------------------------------

# Pattern design:
#   Negative lookbehind: NOT preceded by colon, word-char, slash, dot, or
#   closing angle-bracket.
#   - Colon: excludes namespaced forms like /dev:plan
#   - Word-char / slash / dot: excludes file paths like plans/<slug>/plan.md
#   - Angle-bracket '>': excludes template placeholders like <app>/docs/
#   Note: backtick is intentionally NOT excluded — slash-commands are
#   commonly written inside backticks as ``/plan``.
#
#   Negative lookahead: NOT followed by hyphen, word-char, dot, or slash.
#   - hyphen/word-char/dot: prevents short names (plan, spec, docs, team)
#     matching as a prefix of /plan-status or /plan.md.
#   - slash: a real slash-command is never followed by '/'; a trailing slash
#     means it is a path segment (e.g. gitignore pattern `!/docs/`), not a cmd.

_LOOKBEHIND = r"(?<![:\w/.>])"
_LOOKAHEAD = r"(?![-\w./])"

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        flat,
        re.compile(_LOOKBEHIND + r"/" + re.escape(flat) + _LOOKAHEAD),
    )
    for flat in FLAT_TO_NAMESPACED
]

# Subdirectories within a plugin that are in scope for scanning.
_SCANNED_SUBDIRS = frozenset(("agents", "commands", "modes", "skills", "templates"))

# Top-level docs scanned regardless of subdir (shipped + factory root files).
_ROOT_DOCS = frozenset(("CLAUDE.md", "STACK.md", "BOOTSTRAP.md", "COMMIT_GUIDE.md"))

# Fenced-code markers — Cyrillic-free path examples (gitignore, REST routes)
# inside these would otherwise false-positive, so we skip fenced regions.
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True)
class Violation:
    """A single detected flat-command occurrence."""

    file: Path
    line: int
    flat_cmd: str
    suggestion: str


def _in_scope(path: Path) -> bool:
    """True for a scanned subdir (agents/commands/modes/skills/templates) or a root doc."""
    if path.name in _ROOT_DOCS:
        return True
    return any(part in _SCANNED_SUBDIRS for part in path.parts)


def scan_directory(root: Path) -> list[Violation]:
    """
    Scan in-scope ``*.md`` files under *root* (see module docstring for scope).

    Pre:  root is an existing directory.
    Post: returns a (possibly empty) list of Violation objects, one per
          offending line per flat-command match (excluding ignored lines and
          lines inside fenced code blocks).

    Each line containing ``<!-- lint-namespacing: ignore -->`` is skipped.
    """
    violations: list[Violation] = []
    for md in sorted(root.rglob("*.md")):
        if not _in_scope(md):
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        in_fence = False
        for line_no, line in enumerate(text.splitlines(), start=1):
            if _FENCE_RE.match(line):
                in_fence = not in_fence
                continue
            if in_fence or "lint-namespacing: ignore" in line:
                continue
            for flat, pattern in _PATTERNS:
                if pattern.search(line):
                    violations.append(
                        Violation(
                            file=md,
                            line=line_no,
                            flat_cmd=flat,
                            suggestion=FLAT_TO_NAMESPACED[flat],
                        )
                    )
                    # Only report the first matching flat-name per line to
                    # avoid duplicate output for lines with multiple hits.
                    break
    return violations


def _build_default_roots() -> list[Path]:
    """Resolve default scan roots: plugins installed under .claude/plugins/."""
    base = Path(".claude/plugins")
    return [base] if base.is_dir() else []


def main() -> None:
    """CLI entry point.

    Usage::

        python lint_namespacing.py [--root PATH] [--root PATH ...]

    Exits 0 if clean, 1 if violations found.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Detect legacy flat slash-commands in plugin content.\n"
            "Source-of-truth: docs/plugin-namespacing.md §3"
        )
    )
    parser.add_argument(
        "--root",
        dest="roots",
        metavar="PATH",
        action="append",
        help=(
            "Root directory to scan (may be given multiple times). "
            "Defaults to .claude/plugins/."
        ),
    )
    args = parser.parse_args()

    roots: list[Path]
    if args.roots:
        roots = [Path(r) for r in args.roots]
    else:
        roots = _build_default_roots()

    if not roots:
        print("lint_namespacing: no scan roots found — nothing to check.")
        sys.exit(0)

    all_violations: list[Violation] = []
    for root in roots:
        all_violations.extend(scan_directory(root))

    if not all_violations:
        print("lint_namespacing: OK — no flat-command violations found.")
        sys.exit(0)

    print(f"lint_namespacing: FAIL — {len(all_violations)} violation(s) found:\n")
    for v in all_violations:
        # Normalise path separators for readability on all platforms
        file_str = str(v.file).replace("\\", "/")
        print(f"  {file_str}:{v.line}: /{v.flat_cmd} → {v.suggestion}")

    print(
        "\nFix: replace each flat command with its namespaced form "
        "(see docs/plugin-namespacing.md §3).\n"
        "To suppress a legitimate citation add "
        "<!-- lint-namespacing: ignore --> on that line."
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
