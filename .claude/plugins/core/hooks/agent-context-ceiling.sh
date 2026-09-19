#!/usr/bin/env bash
# agent-context-ceiling.sh (Task 2.6, Д46) — PreToolUse, matcher "*": subagent context budget.
#
# The decision lives in _lib/agent_context_ceiling.py: soft = start + agent_context_budget
# (default 100000) -> decision checkpoint via additionalContext (Д48: commit, then finish a
# small remainder or hand off a large one), repeated every +50000;
# hard = start + agent_context_hard_budget (default off) -> deny all but Bash
# whose every segment is cd or git add|commit|status|diff|log|show,
# SubagentHandback, SendMessage and Write docs/handoffs/*.md.
# Per agent at run time: <project>/.claude/logs/agents/<agent_id>.budget ("soft=250000 hard=off"),
# <project> = $CLAUDE_PROJECT_DIR, else the payload cwd (_stack.md: else the process cwd). No Python -> exit 0, silent.
# Main thread (no agent_id) exits before Python starts. Any error -> allow, exit 0.

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT="$(cat)"
case "$INPUT" in *'"agent_id"'*) ;; *) exit 0 ;; esac

PY="$(source "$HOOK_DIR/_lib/python-bin.sh" 2>/dev/null && printf '%s' "$PY")" || exit 0
source "$HOOK_DIR/_lib/stack-ini.sh"
[ -n "${PY:-}" ] || exit 0
STACK_MD="${CLAUDE_PROJECT_DIR:-.}/.claude/modes/_stack.md"

printf '%s' "$INPUT" |
  AGENT_CONTEXT_BUDGET="$(stack_ini_get agent_context_budget "" "$STACK_MD")" \
  AGENT_CONTEXT_HARD_BUDGET="$(stack_ini_get agent_context_hard_budget "" "$STACK_MD")" \
  "$PY" "$HOOK_DIR/_lib/agent_context_ceiling.py" 2>/dev/null
exit 0
