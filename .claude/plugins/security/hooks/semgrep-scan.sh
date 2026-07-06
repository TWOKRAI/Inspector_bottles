#!/bin/bash
# PostToolUse (OPT-IN): run Semgrep SAST on a just-edited file.
# NOT registered in plugin.json by default — per-edit Semgrep is slow/noisy.
# Wire it manually in .claude/settings.json (PostToolUse, matcher "Edit|Write")
# when you want per-edit SAST. Always exits 0 — advisory, never blocks the edit.

# Resolve Python interpreter (python3 on Linux/macOS, python on Windows).
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
read -r TOOL_NAME FILE_PATH < <($PY -c "import sys,json
d=json.load(sys.stdin)
print(d.get('tool_name',''), d.get('tool_input',{}).get('file_path',''))" <<< "$INPUT" 2>/dev/null)

# Only Edit and Write.
if [[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]]; then
    exit 0
fi

# Only source files Semgrep understands (skip docs/config noise).
case "$FILE_PATH" in
    *.py|*.js|*.jsx|*.ts|*.tsx|*.go|*.rb|*.java|*.php|*.c|*.cpp|*.cs|*.rs) ;;
    *) exit 0 ;;
esac

# File must exist.
if [[ -z "$FILE_PATH" || ! -f "$FILE_PATH" ]]; then
    exit 0
fi

# Skip silently if semgrep is not installed (inert-without-the-tool contract).
if ! command -v semgrep &>/dev/null; then
    exit 0
fi

# Advisory scan of the single edited file — never blocks (hook exits 0 below).
# semgrep's default is exit-0-even-with-findings, so pass NO --error flag: the old
# `--error=false` is invalid Click syntax (a boolean flag takes no value) → semgrep
# exits 2 (usage error) BEFORE scanning, and 2>/dev/null swallowed it, so the hook
# silently did nothing. Surface findings via PostToolUse `additionalContext` JSON:
# per code.claude.com/docs/en/hooks a hook that exits 0 only reaches the agent through
# additionalContext JSON on stdout — plain stdout/stderr on exit 0 go to the debug
# log, not the transcript. semgrep's own progress/errors → /dev/null.
FINDINGS=$(semgrep --config auto --quiet --metrics=off "$FILE_PATH" 2>/dev/null)
if [ -n "$FINDINGS" ]; then
    $PY -c "import json, sys
body = sys.stdin.read()
print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': 'Semgrep SAST findings (advisory, non-blocking):\n' + body}}))" <<< "$FINDINGS"
fi

exit 0
