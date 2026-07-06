#!/usr/bin/env python3
"""lint_agents.py — minimal consistency check for .claude/plugins/*/agents/**/*.md.

Why: 10+ agent definitions across .claude/plugins/*/agents/ have a strict shape
(YAML frontmatter with name/description/model/tools + Markdown body). Manual
upkeep is fragile — renames drift, threshold rules in CLAUDE.md fall out of
sync with actual agent names. This linter catches the drift.

Checks:
  1. Frontmatter present and parseable
  2. Required keys: name, description, model
  3. `name` matches the filename (e.g. developer.md → name: developer)
  4. `model` is a known Claude model ID; WARN if known-but-not-latest-of-tier
     (enforce-latest signal — see CURRENT_MODELS)
  5. `tools` is OPTIONAL: omitting it means the agent inherits the project's full
     enabled tool set (the documented Claude Code inherit path — capability-driven
     agents, plan 2026-06-24 D1/C7). If present, it must be a non-empty list.
  6. `description` is non-empty and under 500 chars
  7. Body has at least one markdown heading (## or #)
  8. Agent names referenced in CLAUDE.md exist as agent files (plugin layout)

Exit codes:
  0 — all green
  1 — at least one ERROR (hard fail — CI should block)
  2 — only WARNINGs (soft fail — review recommended)

Usage:
  python scripts/lint_agents.py                # auto-discover .claude/plugins/*/agents/
  python scripts/lint_agents.py --strict       # warnings also fail with exit 1
  python scripts/lint_agents.py path/to/agents # explicit path
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Keep this list in sync with claude-api docs. Update when new models ship.
# BROAD type-guard: "is this a real model ID?". Older tiers stay valid here —
# a project may deliberately pin opus-4-6/4-7 for cost. Membership = no warning
# about typos; freshness is a separate signal (CURRENT_MODELS below).
KNOWN_MODELS = {
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "claude-haiku-4-5-20251001",
    "inherit",  # special — use parent agent's model
}

# Latest model per tier — the enforce-latest signal ("последние модели везде",
# plan addendum OQ-A1/OQ-A2). A known-but-not-current model (e.g. opus-4-6) is
# valid yet stale → soft WARNING here. The HARD gate that every *bundled* seed
# agent is on a CURRENT model lives in tests/test_lint_agents_models.py.
# Update both when a new model ships (source of truth: claude-api skill).
#   Opus → claude-opus-4-8 · Sonnet → claude-sonnet-5 · Haiku → claude-haiku-4-5
CURRENT_MODELS = {
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-haiku-4-5",
    "claude-haiku-4-5-20251001",  # dated alias of the current Haiku
    "inherit",
}

# `tools` is intentionally NOT required: a capability-driven agent omits it to
# inherit the project's full enabled tool set (plan 2026-06-24 D1/C7). When
# present it is still validated (must be a non-empty list — see lint_file).
REQUIRED_KEYS = ("name", "description", "model")
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)


def parse_frontmatter(text: str) -> dict[str, str] | None:
    """Tiny YAML frontmatter parser — handles flat `key: value` only.

    Sufficient for agent files; intentionally NOT a full YAML implementation
    (no nested mappings, no anchors, no multi-line strings). Returns None if
    no frontmatter block present.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    body = match.group(1)
    out: dict[str, str] = {}
    for line in body.split("\n"):
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def lint_file(path: Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for one agent .md file."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        return [f"cannot decode as UTF-8: {e}"], []

    fm = parse_frontmatter(text)
    if fm is None:
        errors.append("no YAML frontmatter (file must start with '---\\n')")
        return errors, warnings

    for key in REQUIRED_KEYS:
        if key not in fm:
            errors.append(f"missing required frontmatter key: {key!r}")
        elif not fm[key]:
            errors.append(f"empty value for required key: {key!r}")

    name = fm.get("name", "")
    if name and name != path.stem:
        errors.append(f"name {name!r} does not match filename {path.stem!r}")

    model = fm.get("model", "")
    if model and model not in KNOWN_MODELS:
        warnings.append(
            f"model {model!r} not in KNOWN_MODELS — typo, or update the linter?"
        )
    elif model and model not in CURRENT_MODELS:
        latest = ", ".join(sorted(CURRENT_MODELS - {"inherit"}))
        warnings.append(
            f"model {model!r} is valid but not latest-of-tier (current: {latest}) "
            "— bundled agents should track the latest model per tier"
        )

    # `tools` is optional (omit → inherit project tool set). But a *present*
    # key must carry a non-empty list — a bare `tools:` is a mistake, not an
    # inherit signal; omit the key entirely to inherit.
    if "tools" in fm:
        items = [t.strip() for t in fm["tools"].split(",") if t.strip()]
        if not items:
            errors.append(
                "tools key present but list is effectively empty — "
                "omit the key entirely to inherit the project tool set"
            )

    desc = fm.get("description", "")
    if desc and len(desc) > 500:
        warnings.append(f"description is {len(desc)} chars (>500) — too verbose?")

    body_start = text.find("---\n", 3)
    body = text[body_start + 4 :] if body_start > 0 else text
    if not HEADING_RE.search(body):
        warnings.append("no markdown heading in body — is this really an agent prompt?")

    return errors, warnings


def cross_check_claude_md(claude_md: Path, agent_files: dict[str, Path]) -> list[str]:
    """Names mentioned in CLAUDE.md must exist as agent files."""
    warnings: list[str] = []
    if not claude_md.exists():
        return warnings
    text = claude_md.read_text(encoding="utf-8", errors="ignore")
    candidates = set(re.findall(r"\b([a-z][a-z_-]{2,30})\b", text))
    known_roles = {
        "director",
        "manager",
        "teamlead",
        "developer",
        "debugger",
        "investigator",
        "tester",
        "reviewer",
        "docs-writer",
        "tech-writer",
        "spec-writer",
    }
    mentioned = candidates & known_roles
    missing = mentioned - set(agent_files.keys())
    for name in sorted(missing):
        warnings.append(
            f"CLAUDE.md mentions agent {name!r} but no agents/company/{name}.md found"
        )
    return warnings


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    explicit_path = next((a for a in argv[1:] if not a.startswith("--")), None)

    if explicit_path:
        roots = [Path(explicit_path)]
    else:
        # Plugin layout: agents live across plugins under
        # .claude/plugins/<id>/agents/ (no flat aggregation).
        roots = sorted(Path(".claude/plugins").glob("*/agents"))
        if not roots:
            # Legacy flat fallback.
            roots = [c for c in (Path(".claude/agents"), Path("agents")) if c.is_dir()]
        if not roots:
            print(
                "error: no agent dirs found "
                "(.claude/plugins/*/agents or .claude/agents) — pass path explicitly",
                file=sys.stderr,
            )
            return 1

    md_files = sorted(p for root in roots for p in root.rglob("*.md"))
    if not md_files:
        print(
            "warning: no .md files under " + ", ".join(str(r) for r in roots),
            file=sys.stderr,
        )
        return 0

    total_errors = 0
    total_warnings = 0
    agent_files: dict[str, Path] = {}

    for path in md_files:
        if path.name.startswith("_") or path.name.lower() == "readme.md":
            continue
        errors, warnings = lint_file(path)
        agent_files[path.stem] = path

        if errors or warnings:
            try:
                rel = path.relative_to(Path.cwd())
            except ValueError:
                rel = path
            print(f"\n{rel}:")
            for e in errors:
                print(f"  ERROR: {e}")
                total_errors += 1
            for w in warnings:
                print(f"  WARN:  {w}")
                total_warnings += 1

    for claude_md in (Path("CLAUDE.md"), Path(".claude/CLAUDE.md")):
        if claude_md.exists():
            cross_warnings = cross_check_claude_md(claude_md, agent_files)
            if cross_warnings:
                print(f"\n{claude_md}:")
                for w in cross_warnings:
                    print(f"  WARN:  {w}")
                    total_warnings += 1
            break

    print()
    print(f"Checked: {len(agent_files)} agent files")
    print(f"Errors:  {total_errors}")
    print(f"Warns:   {total_warnings}")

    if total_errors:
        return 1
    if total_warnings and strict:
        return 1
    if total_warnings:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
