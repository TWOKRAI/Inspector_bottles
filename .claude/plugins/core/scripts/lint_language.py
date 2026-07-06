#!/usr/bin/env python3
"""lint_language.py — guard the single-language (English) invariant in plugin content.

Why: bundled plugin prompts are authored in English (reasoning quality +
marketplace readiness; the per-project *answer* language is chosen separately
via the Language policy section in modes/_stack.md). Once a file is migrated to
English we must not let Cyrillic creep back in. This linter is the ratchet.

Ratchet design (intentional, see plan phase-2.md Task 2.3):
  * ERROR zone — `agents/` and `modes/` files. These are fully EN-migrated, so
    ANY Cyrillic here is a regression → hard fail (exit 1).
  * WARN zone  — `commands/` and `skills/` bodies. Their English pass is the
    deferred Task 2.1 long-tail; they still contain Cyrillic by design. We
    surface the remaining debt as non-blocking warnings rather than hide it.
    When the long-tail EN pass lands, flip these subdirs into the ERROR zone.

Excluded entirely:
  * the `knowledge` plugin — its EN pass is deferred (plan Task 2.4); excluding
    it keeps this gate green without forcing premature work. Re-enable by
    removing it from EXCLUDED_PLUGINS once Task 2.4 runs.
  * `_`-prefixed files (templates/skeletons, e.g. agents/_template.md).
  * fenced code blocks (``` / ~~~) — Cyrillic in code/output examples is fine.
  * a line carrying `<!-- lint-language: allow -->`.
  * a file carrying `<!-- lint-language: allow-file -->` anywhere.

Scanned subtree (per plugin): agents/, commands/, modes/, skills/.

Exit codes:
  0 — no errors (warnings allowed)
  1 — at least one ERROR (Cyrillic in agents/ or modes/)
  2 — only WARNINGs, and --strict was given

Usage:
  python scripts/lint_language.py                 # auto-discover .claude/plugins/*
  python scripts/lint_language.py --strict        # warnings also fail (exit 2)
  python scripts/lint_language.py --list          # list every warn occurrence
  python scripts/lint_language.py path/to/plugins # explicit root(s)
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Cyrillic block U+0400–U+04FF (covers Russian fully). Matches plan's [Ѐ-ӿ].
CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")

# Fence open/close marker (``` or ~~~), allowing leading whitespace and a lang tag.
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

# Subdirs scanned, mapped to severity. agents/modes are EN-done (ERROR);
# commands/skills bodies are the deferred long-tail (WARN).
_ERROR_SUBDIRS = frozenset(("agents", "modes"))
_WARN_SUBDIRS = frozenset(("commands", "skills"))
_SCANNED_SUBDIRS = _ERROR_SUBDIRS | _WARN_SUBDIRS

# Plugins whose EN pass is deferred — skipped wholesale (see module docstring).
EXCLUDED_PLUGINS = frozenset(("knowledge",))

_ALLOW_LINE = "lint-language: allow"
_ALLOW_FILE = "lint-language: allow-file"


@dataclass(frozen=True)
class Issue:
    """One Cyrillic occurrence outside an allowed context."""

    file: Path
    line: int
    severity: str  # "error" | "warn"
    snippet: str


def _zone(path: Path) -> str | None:
    """Return "error", "warn", or None (out of scope) for *path*.

    None when: under an excluded plugin (the segment right after "plugins/", so a
    coincidental subdir literally named "knowledge" is NOT excluded), or not
    inside a scanned subdir.
    """
    parts = path.parts
    if "plugins" in parts:
        idx = parts.index("plugins")
        if idx + 1 < len(parts) and parts[idx + 1] in EXCLUDED_PLUGINS:
            return None
    elif any(p in EXCLUDED_PLUGINS for p in parts):
        # No "plugins" anchor (odd root) — fall back to a plain part match.
        return None
    if any(p in _ERROR_SUBDIRS for p in parts):
        return "error"
    if any(p in _WARN_SUBDIRS for p in parts):
        return "warn"
    return None


def _content_lines(text: str) -> list[str]:
    """Return lines with fenced-code-block content blanked (line numbers kept)."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append("")  # blank the fence marker line itself
            continue
        out.append("" if in_fence else line)
    return out


def scan_directory(root: Path) -> list[Issue]:
    """Scan all in-scope ``*.md`` under *root* for stray Cyrillic.

    Pre:  root is an existing directory.
    Post: returns a (possibly empty) list of Issue, one per offending line.
    """
    issues: list[Issue] = []
    for md in sorted(root.rglob("*.md")):
        if md.name.startswith("_"):
            continue
        severity = _zone(md)
        if severity is None:
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _ALLOW_FILE in text:
            continue
        for line_no, line in enumerate(_content_lines(text), start=1):
            if not line or _ALLOW_LINE in line:
                continue
            match = CYRILLIC_RE.search(line)
            if match:
                start = max(0, match.start() - 12)
                snippet = line[start : start + 48].strip()
                issues.append(
                    Issue(file=md, line=line_no, severity=severity, snippet=snippet)
                )
    return issues


def _build_default_roots() -> list[Path]:
    """Resolve default scan roots: each plugin under .claude/plugins/."""
    base = Path(".claude/plugins")
    if base.is_dir():
        return [base]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "roots",
        nargs="*",
        help="Root dir(s) to scan (default: .claude/plugins).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as blocking (exit 2 when warns and no errors).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List every warning occurrence (default: summary count only).",
    )
    args = parser.parse_args(argv)

    explicit = bool(args.roots)
    roots = [Path(r) for r in args.roots] if args.roots else _build_default_roots()
    roots = [r for r in roots if r.is_dir()]
    if not roots:
        print(
            "lint_language: no scan roots found (.claude/plugins) — pass a path.",
            file=sys.stderr,
        )
        # Explicit-but-invalid path is a misconfiguration → fail; bare
        # auto-discovery finding nothing (no plugins) is a benign no-op.
        return 1 if explicit else 0

    issues: list[Issue] = []
    for root in roots:
        issues.extend(scan_directory(root))

    errors = [i for i in issues if i.severity == "error"]
    warns = [i for i in issues if i.severity == "warn"]

    for i in errors:
        file_str = str(i.file).replace("\\", "/")
        print(f"[FAIL] {file_str}:{i.line}: Cyrillic in EN-only zone — {i.snippet!r}")

    if warns:
        warn_files = sorted({str(i.file).replace("\\", "/") for i in warns})
        print(
            f"[WARN] {len(warns)} Cyrillic line(s) in {len(warn_files)} "
            "command/skill body file(s) — deferred EN pass (plan Task 2.1 long-tail)."
        )
        if args.list:
            for i in warns:
                file_str = str(i.file).replace("\\", "/")
                print(f"  {file_str}:{i.line}: {i.snippet!r}")

    if errors:
        print(
            f"\n[FAIL] lint_language: {len(errors)} error(s) — "
            "Cyrillic crept into agents/ or modes/. Translate or mark "
            "<!-- lint-language: allow -->."
        )
        return 1
    if warns and args.strict:
        print(f"\n[WARN] lint_language: 0 errors, {len(warns)} warning(s) (strict mode).")
        return 2
    print(
        f"\n[OK] lint_language: agents/ + modes/ are EN-clean "
        f"({len(warns)} non-blocking warn(s) in deferred command/skill bodies)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
