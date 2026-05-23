#!/usr/bin/env bash
# PreToolUse(Bash) hook — block `git push` if sentrux rules are violated.
#
# Reason: agents may push without running `/sentrux-check` first, missing
# architectural regressions (cycles, layer violations). This hook is the
# last line of defence before code leaves the local machine.
#
# Behaviour:
#   - Matcher in settings.json: "Bash" (parse command from $CLAUDE_TOOL_INPUT inside)
#   - Only intercepts commands matching `^git[[:space:]]+push\b`.
#   - If `sentrux` binary not installed → pass-through (do not block).
#   - If `sentrux check_rules` exits non-zero → block with instruction.
#
# Exit codes:
#   0 — allow (push proceeds)
#   2 — block (PreToolUse contract, agent sees stderr message)
#
# Override:
#   - Remove sentrux:check_rules from rules.toml to make it permissive
#   - Disable this hook in .claude/settings.json if false-positives become common

source "$(dirname "$0")/../_lib/python-bin.sh"

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | $PY -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)

# Only check git push invocations
if ! echo "$COMMAND" | grep -qE '^[[:space:]]*git[[:space:]]+push\b'; then
    exit 0
fi

# Pass-through if sentrux not installed (optional MCP — do not punish projects without it)
if ! command -v sentrux >/dev/null 2>&1; then
    exit 0
fi

# Run check_rules; capture output for blocked-case message
SENTRUX_OUTPUT=$(sentrux check_rules 2>&1)
SENTRUX_EXIT=$?

if [ $SENTRUX_EXIT -ne 0 ]; then
    cat >&2 <<EOF
Blocked: 'git push' refused — sentrux:check_rules reported violations.

$SENTRUX_OUTPUT

Fix the violations or run /sentrux-check locally to investigate, then retry the push.
If this is a false positive: edit .sentrux/rules.toml or disable this hook in
.claude/settings.json (hooks.PreToolUse → quality/sentrux-precheck.sh).
EOF
    exit 2
fi

exit 0
