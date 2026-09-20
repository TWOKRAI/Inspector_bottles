#!/usr/bin/env python3
"""lint_language.py — guard the single-language (English) invariant in plugin content.

Why: bundled plugin prompts are authored in English (reasoning quality +
marketplace readiness; the per-project *answer* language is chosen separately
via the Language policy section in modes/_stack.md). Once a file is migrated to
English we must not let Cyrillic creep back in. This linter is the ratchet.

Zone table (ordered, first match wins — see ZONES below): every scanned path is
matched, in table order, against a Zone's ``prefix`` — path segments relative
to the TEMPLATE ROOT (see "Template root" below), each segment compared with
``fnmatch.fnmatchcase`` (``*`` and ``mcp-*`` work; ``*`` never crosses a ``/``,
because matching is segment-by-segment on ``Path.parts``, never on a joined
string). A prefix whose last segment ends with ``.md`` is an EXACT-FILE zone —
it matches only a file at exactly that path (``rel.parts == prefix``, length
included). Any other prefix is a DIRECTORY zone — it matches any ``*.md`` file
anywhere below that directory (``rel.parts`` starts with ``prefix``,
segment-wise, plus at least one more segment).

    knowledge              plugins/knowledge/**                          skip  (never)
    B0-stack-md            plugins/core/modes/_stack.md      [exact]     error (done)
    agents                 plugins/*/agents/**                           error (done)
    modes                  plugins/*/modes/**                            error (done)
    skills                 plugins/*/skills/**                           warn  (tbd)
    B0-claude-md           CLAUDE.md                         [exact]     error (done)
    B0-claude-md-template  plugins/core/templates/claude-md.template.md
                                                               [exact]     error (done)
    B1-dev-commands        plugins/dev/commands/**                       error (done)
    B2-core-commands       plugins/core/commands/**                      error (done)
    B2-commit-guide        COMMIT_GUIDE.md                   [exact]     error (done)
    B3-mcp-commands        plugins/mcp-*/commands/**                     error (done)
    B3-readme              plugins/mcp-*/README.md           [exact]     error (done)
    B3-readme-agent-teams  plugins/agent-teams/README.md     [exact]     error (done)
    owner-readme           plugins/*/README.md               [exact]     skip  (never)
    owner-plan-template    plugins/core/templates/PLAN.template.md
                                                               [exact]     skip  (never)
    owner-plans-readme     plugins/core/templates/plans-readme.template.md
                                                               [exact]     skip  (never)
    owner-agent-template   plugins/core/templates/agent.template.md
                                                               [exact]     skip  (never)
    B4-core-templates      plugins/core/templates/**                     error (done)
    B4-stack               STACK.md                          [exact]     error (done)
    B4-bootstrap           BOOTSTRAP.md                       [exact]     error (done)
    other-commands         plugins/*/commands/**                         warn  (tbd)
    other-templates        plugins/*/templates/**                        warn  (tbd)

A path matching no zone is out of scope (not scanned at all).

The criterion is the READER, not the file type (owner, 2026-09-16): text the model
reads is English; text only the owner reads stays Russian. A plugin README is
model-read when something in the seed sends the model to it — MCP READMEs (the
CLAUDE.md routing block says to read one before the first tool call) and the
agent-teams README (linked from /dev:team). Every other plugin README is an
owner-facing overview: zone "owner-readme", skipped. When a new README becomes
model-read, give it an exact-file zone above "owner-readme". The plan and plans-ledger
templates are owner-facing too (owner, 2026-09-16: plans are the owner's control surface,
Д42) — exact-file skip zones above "B4-core-templates".

Flip procedure: once a batch's EN translation lands, in its batch task change
that zone's (or those zones') ``severity`` from "warn" to "error" in the ZONES
tuple below — nothing else in this file changes. ``flips_in`` is documentation
only (printed in summaries); it does not drive behavior.

Template root: ``scan_directory(root)`` resolves the template root as *root*
itself when ``root/plugins`` is a directory (a seed-tree run, e.g. pointed at
``src/claude_kit_claude/template``); otherwise as ``root.parent`` when *root*
is itself named ``plugins`` (a consumer run pointed at ``.claude/plugins`` —
the doctor.sh default); otherwise *root* unchanged. The walk is always
``root.rglob("*.md")`` — it never looks above *root* — so a consumer run
scoped to ``.claude/plugins`` can never report the project's own top-level
``.claude/CLAUDE.md`` (project-owned, may legitimately stay non-English),
while a seed run scoped to the template root does cover top-level files like
``CLAUDE.md``, ``COMMIT_GUIDE.md``, ``STACK.md``, ``BOOTSTRAP.md``.

``_``-prefixed files (templates/skeletons, e.g. ``_WORKTREE_PATTERN.md``) are
skipped — but only inside a DIRECTORY zone. An EXACT-FILE zone is checked
first and overrides the skip, which is how ``plugins/core/modes/_stack.md``
— itself a ``_``-prefixed file — is scanned as zone "B0-stack-md" while
``plugins/core/agents/_WORKTREE_PATTERN.md`` stays skipped. The agent-hire
scaffold moved out of ``agents/`` to ``plugins/core/templates/agent.template.md``
(Task 3.3) — no longer ``_``-prefixed, so it keeps its "skipped" status via
the dedicated exact-file zone "owner-agent-template" instead.

Also excluded, regardless of zone:
  * fenced code blocks (``` / ~~~) — Cyrillic in code/output examples is fine.
  * a line carrying `<!-- lint-language: allow -->`.
  * a file carrying `<!-- lint-language: allow-file -->` anywhere.

Exit codes:
  0 — no errors (warnings allowed)
  1 — at least one ERROR (Cyrillic in an "error"-severity zone)
  2 — only WARNINGs, and --strict was given

Usage:
  python scripts/lint_language.py                 # auto-discover .claude/plugins
  python scripts/lint_language.py --strict        # warnings also fail (exit 2)
  python scripts/lint_language.py --list          # list every warn occurrence
  python scripts/lint_language.py path/to/root    # explicit root(s)
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePath

# Cyrillic block U+0400-U+04FF (covers Russian fully). Matches plan's [Ѐ-ӿ].
CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")

# Fence open/close marker (``` or ~~~), allowing leading whitespace and a lang tag.
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True)
class Zone:
    """One entry of the ordered zone table (see module docstring)."""

    name: str
    prefix: tuple[str, ...]
    severity: str  # "error" | "warn" | "skip"
    flips_in: str  # plan task id, "done", or "never" — documentation only


# Ordered, first-match-wins. Do NOT sort this table — order encodes priority.
# E.g. B3-readme / B0-claude-md-template must be checked before the catch-all
# other-commands/other-templates entries, since those exact-file zones sit
# inside directories the catch-alls would otherwise also match.
ZONES: tuple[Zone, ...] = (
    Zone("knowledge", ("plugins", "knowledge"), "skip", "never"),
    Zone("B0-stack-md", ("plugins", "core", "modes", "_stack.md"), "error", "done"),
    Zone("agents", ("plugins", "*", "agents"), "error", "done"),
    Zone("modes", ("plugins", "*", "modes"), "error", "done"),
    Zone("skills", ("plugins", "*", "skills"), "warn", "tbd"),
    Zone("B0-claude-md", ("CLAUDE.md",), "error", "done"),
    Zone(
        "B0-claude-md-template",
        ("plugins", "core", "templates", "claude-md.template.md"),
        "error",
        "done",
    ),
    Zone("B1-dev-commands", ("plugins", "dev", "commands"), "error", "done"),
    Zone("B2-core-commands", ("plugins", "core", "commands"), "error", "done"),
    Zone("B2-commit-guide", ("COMMIT_GUIDE.md",), "error", "done"),
    Zone("B3-mcp-commands", ("plugins", "mcp-*", "commands"), "error", "done"),
    Zone("B3-readme", ("plugins", "mcp-*", "README.md"), "error", "done"),
    Zone(
        "B3-readme-agent-teams",
        ("plugins", "agent-teams", "README.md"),
        "error",
        "done",
    ),
    Zone("owner-readme", ("plugins", "*", "README.md"), "skip", "never"),
    Zone(
        "owner-plan-template",
        ("plugins", "core", "templates", "PLAN.template.md"),
        "skip",
        "never",
    ),
    Zone(
        "owner-plans-readme",
        ("plugins", "core", "templates", "plans-readme.template.md"),
        "skip",
        "never",
    ),
    Zone(
        "owner-agent-template",
        ("plugins", "core", "templates", "agent.template.md"),
        "skip",
        "never",
    ),
    Zone("B4-core-templates", ("plugins", "core", "templates"), "error", "done"),
    Zone("B4-stack", ("STACK.md",), "error", "done"),
    Zone("B4-bootstrap", ("BOOTSTRAP.md",), "error", "done"),
    Zone("other-commands", ("plugins", "*", "commands"), "warn", "tbd"),
    Zone("other-templates", ("plugins", "*", "templates"), "warn", "tbd"),
)

_ALLOW_LINE = "lint-language: allow"
_ALLOW_FILE = "lint-language: allow-file"


@dataclass(frozen=True)
class Issue:
    """One Cyrillic occurrence outside an allowed context."""

    file: Path
    line: int
    severity: str  # "error" | "warn"
    zone: str
    snippet: str


def _is_exact_file_zone(zone: Zone) -> bool:
    """A zone whose prefix names one specific file rather than a directory."""
    return zone.prefix[-1].endswith(".md")


def _zone_for(rel: PurePath) -> Zone | None:
    """Return the first Zone in ZONES whose prefix matches *rel*, or None.

    *rel* is a path relative to the template root (see module docstring).
    """
    parts = rel.parts
    for zone in ZONES:
        prefix = zone.prefix
        if len(parts) < len(prefix):
            continue
        head = parts[: len(prefix)]
        if not all(
            fnmatch.fnmatchcase(seg, pat) for seg, pat in zip(head, prefix, strict=True)
        ):
            continue
        if _is_exact_file_zone(zone):
            if len(parts) == len(prefix):
                return zone
        elif len(parts) > len(prefix):
            return zone
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


def _template_root(root: Path) -> Path:
    """Resolve the template root that relative paths in *root* are computed from.

    See "Template root" in the module docstring for the three cases.
    """
    if (root / "plugins").is_dir():
        return root
    if root.name == "plugins":
        return root.parent
    return root


def scan_directory(root: Path) -> list[Issue]:
    """Scan all in-scope ``*.md`` under *root* for stray Cyrillic.

    Pre:  root is an existing directory.
    Post: returns a (possibly empty) list of Issue, one per offending line.
    Never walks above *root* — see "Template root" in the module docstring.
    """
    template_root = _template_root(root)
    issues: list[Issue] = []
    for md in sorted(root.rglob("*.md")):
        rel = md.relative_to(template_root)
        zone = _zone_for(rel)
        if zone is None or zone.severity == "skip":
            continue
        if not _is_exact_file_zone(zone) and md.name.startswith("_"):
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
                    Issue(
                        file=md,
                        line=line_no,
                        severity=zone.severity,
                        zone=zone.name,
                        snippet=snippet,
                    )
                )
    return issues


def _build_default_roots() -> list[Path]:
    """Resolve default scan roots: the project's composed plugin tree."""
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
    error_zone_names = ", ".join(z.name for z in ZONES if z.severity == "error")

    for i in errors:
        file_str = str(i.file).replace("\\", "/")
        print(
            f"[FAIL] {file_str}:{i.line}: Cyrillic in ERROR zone {i.zone} "
            f"— {i.snippet!r}"
        )

    if warns:
        zone_order = {z.name: idx for idx, z in enumerate(ZONES)}
        by_zone: dict[str, list[Issue]] = {}
        for i in warns:
            by_zone.setdefault(i.zone, []).append(i)
        for zone_name in sorted(by_zone, key=lambda n: zone_order.get(n, len(ZONES))):
            zone_issues = by_zone[zone_name]
            flips_in = next(z.flips_in for z in ZONES if z.name == zone_name)
            n_files = len({i.file for i in zone_issues})
            print(
                f"[WARN] zone {zone_name}: {len(zone_issues)} line(s) in {n_files} "
                f"file(s) — flips to ERROR in Task {flips_in}"
            )
            if args.list:
                for i in zone_issues:
                    file_str = str(i.file).replace("\\", "/")
                    print(f"    {file_str}:{i.line}: {i.snippet!r}")

    if errors:
        print(
            f"\n[FAIL] lint_language: {len(errors)} error(s) — Cyrillic in an ERROR "
            f"zone ({error_zone_names}). Translate or mark "
            "<!-- lint-language: allow -->."
        )
        return 1
    n_warn_zones = len({i.zone for i in warns})
    if warns and args.strict:
        print(
            f"\n[WARN] lint_language: 0 errors, {len(warns)} warning(s) in "
            f"{n_warn_zones} zone(s) (strict mode)."
        )
        return 2
    print(
        f"\n[OK] lint_language: 0 errors in ERROR zones ({error_zone_names}); "
        f"{len(warns)} warn(s) in {n_warn_zones} zone(s) pending translation."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
