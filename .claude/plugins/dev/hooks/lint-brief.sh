#!/usr/bin/env bash
# lint-brief.sh (Task 3.1) — PreToolUse: checks a WRITER subagent's brief before it is
# spawned and denies the spawn when the brief lacks a design, a bounded file list,
# predicted reds or a report contract. The most expensive recorded failure class of the
# previous plan (Task 4.1, five runs measured, Д45): two briefs without a design burned
# 181k / 175k tokens and shipped zero code; a brief naming 13 files burned its whole
# budget reading. This hook turns the prose rule in dev/templates/executor-brief.md
# into a mechanical check.
#
# Same idiom as core/hooks/agent-context-ceiling.sh: read stdin once, a cheap `case`
# pre-filter before Python starts, resolve the interpreter, read ini keys from
# `.claude/modes/_stack.md`, fail open on any error. The dev plugin has no hooks/_lib of
# its own yet and this task's file list adds none, so python-bin.sh / stack-ini.sh are
# sourced from the core plugin via a relative path -- the same cross-plugin reuse
# agent-teams/hooks/team-teammate-idle-gate.sh already relies on. The Python side is
# embedded via heredoc (same idiom as that file), not a separate _lib module.
#
# Event: PreToolUse, matcher "Agent|Task" (the spawn tool's name was renamed across
# Claude Code versions -- both accepted). Role filter (brief_lint_roles ini key,
# default developer/teamlead/tester/junior/debugger): only a WRITER spawn is linted --
# reviewer, investigator, Explore, general-purpose etc. pass silently. brief_lint=off
# (ini) allows everything without reading the prompt. A `BRIEF-OVERRIDE: <reason>` line
# anywhere in the prompt allows silently and prints nothing -- the lead is never locked
# out.
#
# Checks on tool_input.prompt: DESIGN block >= 3 non-empty lines; FILES block's
# numbered/bulleted entry count <= brief_max_files (default 6); REDS block's entry
# count <= 10, or its first non-empty line starts with "n/a"; REPORT label present. A
# violation denies via the SAME JSON PreToolUse decision shape
# agent_context_ceiling.py's hard-budget deny uses (permissionDecision /
# permissionDecisionReason on hookSpecificOutput) -- exit code stays 0, the JSON on
# stdout carries the decision. stdout is parsed as JSON by Claude Code: nothing else
# ever goes there.
#
# Any internal error (bad JSON, no python, missing/malformed fields) -> allow: exit 0,
# no output.

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT="$(cat)"

# Cheap pre-filter: only a spawn tool call carries a brief worth linting -- every other
# tool call exits before Python starts (perf floor for the ignored-tool path).
case "$INPUT" in
  *'"Agent"'*|*'"Task"'*) ;;
  *) exit 0 ;;
esac

PYLIB="$HOOK_DIR/../../core/hooks/_lib/python-bin.sh"
# shellcheck source=/dev/null
[ -f "$PYLIB" ] && source "$PYLIB" 2>/dev/null
[ -n "${PY:-}" ] || exit 0

INILIB="$HOOK_DIR/../../core/hooks/_lib/stack-ini.sh"
# shellcheck source=/dev/null
[ -f "$INILIB" ] && source "$INILIB" 2>/dev/null
STACK_MD="${CLAUDE_PROJECT_DIR:-.}/.claude/modes/_stack.md"

if command -v stack_ini_get >/dev/null 2>&1; then
  BRIEF_LINT="$(stack_ini_get brief_lint on "$STACK_MD")"
  BRIEF_MAX_FILES="$(stack_ini_get brief_max_files 6 "$STACK_MD")"
  BRIEF_LINT_ROLES="$(stack_ini_get brief_lint_roles "developer, teamlead, tester, junior, debugger" "$STACK_MD")"
else
  BRIEF_LINT=on
  BRIEF_MAX_FILES=6
  BRIEF_LINT_ROLES="developer, teamlead, tester, junior, debugger"
fi

[ "$BRIEF_LINT" = "off" ] && exit 0

HOOK_INPUT="$INPUT" BRIEF_MAX_FILES="$BRIEF_MAX_FILES" BRIEF_LINT_ROLES="$BRIEF_LINT_ROLES" "$PY" - <<'PYEOF' 2>/dev/null
import json
import os
import re

LABEL_RE = re.compile(r"^[ \t]*([A-Z][A-Z \-/]{2,})(?:[ \t]*\(.*)?:", re.MULTILINE)
ENTRY_RE = re.compile(r"^[ \t]*(?:\d+\.|[-*])[ \t]+")
OVERRIDE_RE = re.compile(r"^[ \t]*BRIEF-OVERRIDE:[ \t]*\S+", re.MULTILINE)
BULLET_STRIP_RE = re.compile(r"^(?:\d+\.|[-*])[ \t]+")


def label_blocks(text):
    """Map each FIRST-seen label name -> its block: the lines after the label line,
    up to (not including) the next label line, or the end of the text."""
    matches = list(LABEL_RE.finditer(text))
    lines = text.splitlines()
    blocks = {}
    for idx, m in enumerate(matches):
        name = m.group(1).strip()
        if name in blocks:
            continue
        label_line_no = text.count("\n", 0, m.start())
        end_line_no = (
            text.count("\n", 0, matches[idx + 1].start())
            if idx + 1 < len(matches)
            else len(lines)
        )
        blocks[name] = lines[label_line_no + 1 : end_line_no]
    return blocks


def first_nonempty(block_lines):
    for line in block_lines:
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def strip_bullet(text):
    return BULLET_STRIP_RE.sub("", text).strip()


def main():
    try:
        payload = json.loads(os.environ.get("HOOK_INPUT") or "")
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    if payload.get("tool_name") not in ("Agent", "Task"):
        return

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    subagent_type = tool_input.get("subagent_type")

    roles = {
        r.strip()
        for r in os.environ.get("BRIEF_LINT_ROLES", "").split(",")
        if r.strip()
    }
    if subagent_type not in roles:
        return

    prompt = tool_input.get("prompt")
    if not isinstance(prompt, str):
        return

    if OVERRIDE_RE.search(prompt):
        return

    try:
        max_files = int(str(os.environ.get("BRIEF_MAX_FILES", "6")).strip())
    except (TypeError, ValueError):
        max_files = 6

    blocks = label_blocks(prompt)
    violations = []

    design = blocks.get("DESIGN")
    if design is None:
        violations.append("DESIGN block missing")
    else:
        nonempty = [ln for ln in design if ln.strip()]
        if len(nonempty) < 3:
            violations.append(
                f"DESIGN has {len(nonempty)} non-empty line(s) (need >= 3)"
            )

    files = blocks.get("FILES")
    if files is None:
        violations.append("FILES block missing")
    else:
        count = sum(1 for ln in files if ENTRY_RE.match(ln))
        if count > max_files:
            violations.append(f"FILES lists {count} paths (max {max_files})")

    reds = blocks.get("REDS")
    if reds is None:
        violations.append("REDS block missing")
    else:
        first = strip_bullet(first_nonempty(reds)).lower()
        if not first.startswith("n/a"):
            count = sum(1 for ln in reds if ENTRY_RE.match(ln))
            if count > 10:
                violations.append(f"REDS lists {count} tests (max 10, or 'n/a')")

    if "REPORT" not in blocks:
        violations.append("REPORT block missing")

    if not violations:
        return

    reason = (
        f"lint-brief: spawn of '{subagent_type}' denied - "
        + "; ".join(violations)
        + ". Fix the brief (form: .claude/plugins/dev/templates/executor-brief.md)"
        + " or add a line 'BRIEF-OVERRIDE: <reason>'."
    )
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            },
            ensure_ascii=True,
        )
    )


try:
    main()
except Exception:
    pass
PYEOF
exit 0
