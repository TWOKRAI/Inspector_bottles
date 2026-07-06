#!/usr/bin/env bash
# PreToolUse(Bash) hook — block `git push` if sentrux rules are violated.
#
# Reason: agents may push without running `/mcp-sentrux:sentrux-check` first, missing
# architectural regressions (cycles, layer violations). This hook is the
# last line of defence before code leaves the local machine.
#
# Behaviour:
#   - Matcher in settings.json: "Bash" (parse command from $CLAUDE_TOOL_INPUT inside)
#   - Only intercepts commands matching `^git[[:space:]]+push\b`.
#   - If `sentrux` binary not installed → pass-through (do not block).
#   - If `sentrux check` exits non-zero → block with instruction.
#
# Exit codes:
#   0 — allow (push proceeds)
#   2 — block (PreToolUse contract, agent sees stderr message)
#
# Override:
#   - Loosen or remove the offending rule in .sentrux/rules.toml (permissive)
#   - Disable this hook in .claude/settings.json if false-positives become common

# Resolve python-bin.sh across both template layouts (kept byte-identical by
# mirror_template.py): the plugin tree co-locates _lib/ next to the hook; the
# legacy horizontal tree keeps _lib/ one level up (sibling of the category dir).
_HOOK_DIR="$(dirname "$0")"
if [ -f "$_HOOK_DIR/_lib/python-bin.sh" ]; then
    source "$_HOOK_DIR/_lib/python-bin.sh"
else
    source "$_HOOK_DIR/../_lib/python-bin.sh"
fi

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

# Run `sentrux check` (rule validation against .sentrux/rules.toml, exit 0/1 —
# the CI-friendly CLI verb; capture output for the blocked-case message).
#
# NOTE: must be `check`, NOT `check_rules`. `check_rules` is the MCP *tool* name
# (mcp__sentrux__check_rules); as a CLI arg it is not a subcommand, so sentrux
# misparses it as a positional path target and runs a full deep scan → hangs on
# every push. The rest of the seed uses `sentrux check "$(git rev-parse …)"`.
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")

# Pass-through when there is no ruleset to enforce. `sentrux check` exits 1 on a
# missing .sentrux/rules.toml ("No .sentrux/rules.toml found") — that is "no
# rules", NOT a violation. Without this guard the block-on-nonzero below would
# false-positive EVERY push in any project that enabled mcp-sentrux but has not
# deployed a rules.toml (non-python bootstrap, manual enable, or rules removed).
# Mirrors the CI template's `hashFiles('.sentrux/rules.toml') != ''` guard.
if [ ! -f "$REPO_ROOT/.sentrux/rules.toml" ]; then
    exit 0
fi

SENTRUX_OUTPUT=$(sentrux check "$REPO_ROOT" 2>&1)
SENTRUX_EXIT=$?

if [ $SENTRUX_EXIT -ne 0 ]; then
    cat >&2 <<EOF
Blocked: 'git push' refused — sentrux check reported rule violations.

$SENTRUX_OUTPUT

Fix the violations or run /mcp-sentrux:sentrux-check locally to investigate, then retry the push.
If this is a false positive: edit .sentrux/rules.toml or disable this hook in
.claude/settings.json (hooks.PreToolUse → quality/sentrux-precheck.sh).
EOF
    exit 2
fi

exit 0
