#!/bin/bash
# PostToolUse(Bash) — surfaces a compact FAILED/ERROR summary for pytest runs.
#
# Input contract (Claude Code hooks): a PostToolUse hook receives its payload as
# JSON on STDIN — there are NO $CLAUDE_TOOL_INPUT / $CLAUDE_TOOL_OUTPUT env vars
# (they never existed; the old version read empty strings and did nothing).
# The command is at .tool_input.command; the Bash result at .tool_response.
#
# NOTE: a PostToolUse hook CANNOT rewrite the tool's captured stdout — the full
# pytest output still reaches the transcript. This hook's stdout is therefore
# SUPPLEMENTARY context (a distilled failure view), not a replacement. Real
# token savings come from running tests lean at the source
# (`pytest -q --tb=short`), per .claude/CLAUDE.md → "Token discipline".

# Resolve Python interpreter (python3 on Linux/macOS, python on Windows) via the
# shared helper, mirroring the other core hooks (kept byte-identical across the
# plugin / legacy layouts by mirror_template.py).
_HOOK_DIR="$(dirname "$0")"
if [ -f "$_HOOK_DIR/_lib/python-bin.sh" ]; then
    source "$_HOOK_DIR/_lib/python-bin.sh"
else
    source "$_HOOK_DIR/../_lib/python-bin.sh"
fi

INPUT=$(cat)

# Command that was run (.tool_input.command). Gate on pytest first — cheapest check.
COMMAND=$(echo "$INPUT" | $PY -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)
if ! echo "$COMMAND" | grep -qE "pytest|run_framework_tests"; then
    exit 0
fi

# Tool result (.tool_response). Bash responses vary in shape — accept a dict
# (stdout/stderr/output) or a bare string.
OUTPUT=$(echo "$INPUT" | $PY -c "import sys,json
d = json.load(sys.stdin)
r = d.get('tool_response', '')
if isinstance(r, dict):
    print((r.get('stdout') or '') + (r.get('stderr') or '') or (r.get('output') or ''))
else:
    print(r)" 2>/dev/null)

# Tests passed with no failures — nothing to distil.
if echo "$OUTPUT" | grep -qE "passed|no tests ran"; then
    if ! echo "$OUTPUT" | grep -qE "FAILED|ERROR|failed"; then
        exit 0
    fi
fi

# Distil: keep FAILED/ERROR lines, the short test summary, the warnings summary.
echo "$OUTPUT" | grep -E "(FAILED|ERROR|ERRORS|short test summary|warnings summary|=====)" | head -40

exit 0
