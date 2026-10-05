#!/usr/bin/env bash
# PostToolUse (Edit|Write): format a Python file right after the agent wrote it,
# the way the pre-commit ruff hooks will see it at commit time (Task 1.2).
#
# Order is the pre-commit order, every call with --force-exclude (as ruff-pre-commit
# passes it, so `extend-exclude = [".claude/"]` is honoured for an explicit file):
#   1. ruff check --fix --unfixable F401   (pre-commit `ruff --fix`)
#   2. ruff format                         (pre-commit `ruff-format`)
#   3. ruff check --no-fix --output-format concise   (what is still left)
# What is left after step 3 (rc 1) goes to the agent as JSON
# `hookSpecificOutput.additionalContext` on stdout - the only channel the agent
# sees on exit 0 (stderr is debug-log only). Any other rc: silence.
#
# F401 (unused import) is deliberately NOT auto-fixed: the hook fires after every
# Edit/Write, and an import added before its first use was silently stripped -
# two broken break-injections and one broken commit (29e349a, system-to-eight
# Task 2.7 step 0). It still shows up in the leftover list, which is correct:
# pre-commit would strip it and fail the commit.
#
# Division of labour: embedded Python parses the payload, checks the path and
# builds the JSON; bash finds ruff and calls it. (Windows Python prints CRLF, so
# the old `read -r TOOL FILE < <($PY ...)` left a trailing "\r" in FILE, the
# `*.py` test failed and the hook never reached ruff. Now Python prints only the
# path and bash strips "\r".)
#
# Exit code ALWAYS 0 - never blocks work.

# Cheap cut before ANY Python launch (Task 1.5): the hook fires on every Edit/Write, and
# both python-bin.sh (`python3 -c "import sys"`) and the payload parser start Python -
# ~280 ms on a .md edit. A .py path in the JSON payload always ends in `.py"`; a payload
# without that substring cannot name a .py file. A false pass (`.py"` elsewhere in the
# payload) is harmless: the full check below still runs.
INPUT="$(cat)"
case "$INPUT" in
    *'.py"'*) ;;
    *) exit 0 ;;
esac

# Resolve python-bin.sh across both template layouts (kept byte-identical by
# mirror_template.py): the plugin tree co-locates _lib/ next to the hook; the
# legacy horizontal tree keeps _lib/ one level up (sibling of the category dir).
_HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$_HOOK_DIR/_lib/python-bin.sh" ]; then
    _PY_BIN_SH="$_HOOK_DIR/_lib/python-bin.sh"
else
    _PY_BIN_SH="$_HOOK_DIR/../_lib/python-bin.sh"
fi
# Subshell: python-bin.sh `exit 1`s without an interpreter - that must not surface
# as a "hook error".
PY="$(source "$_PY_BIN_SH" 2>/dev/null && printf '%s' "$PY")" || exit 0
[ -n "${PY:-}" ] || exit 0

PROJECT="${CLAUDE_PROJECT_DIR:-$PWD}"

# --- 1. payload -> path of the file to process (or nothing) ----------------------------------
read -r -d '' PARSE_PY <<'PYEOF'
import json
import os
import sys

try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if not isinstance(payload, dict):
    sys.exit(0)
tool_input = payload.get('tool_input')
path = tool_input.get('file_path') if isinstance(tool_input, dict) else None
if payload.get('tool_name') not in ('Edit', 'Write'):
    sys.exit(0)
if not isinstance(path, str) or not path.endswith('.py') or not os.path.isfile(path):
    sys.exit(0)

# TWIN: the root rule below is a copy of `_repo_root` in
# .claude/plugins/core/hooks/autofix_text.py - a lang-python -> core dependency is
# worse than a copy. Change both together.
project_real = os.path.normcase(os.path.realpath(os.environ['PROJECT']))
real = os.path.normcase(os.path.realpath(path))
current = os.path.dirname(real)
root = None
while True:
    if os.path.exists(os.path.join(current, '.git')):
        if current == project_real or current.startswith(project_real + os.sep):
            root = current
        break
    parent = os.path.dirname(current)
    if parent == current:
        break
    current = parent
if root is None:
    sys.exit(0)
rel = os.path.relpath(real, root).replace(os.sep, '/')
if rel.startswith(('robot/', 'docs/claude/frozen/')):
    sys.exit(0)
sys.stdout.write(path)
PYEOF

FILE="$(printf '%s' "$INPUT" | PROJECT="$PROJECT" PYTHONIOENCODING=utf-8 $PY -c "$PARSE_PY" 2>/dev/null | tr -d '\r')"
[ -n "$FILE" ] || exit 0

# --- 2. find ruff: repo venv (also from a worktree) > project venv > PATH --------------------
RUFF=""
COMMON="$(git -C "$PROJECT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
if [ -n "$COMMON" ] && [ "$(basename "$COMMON")" = ".git" ]; then
    MAIN_ROOT="$(dirname "$COMMON")"
    for candidate in "$MAIN_ROOT/.venv/Scripts/ruff.exe" "$MAIN_ROOT/.venv/bin/ruff"; do
        if [ -f "$candidate" ]; then RUFF="$candidate"; break; fi
    done
fi
if [ -z "$RUFF" ]; then
    for candidate in "$PROJECT/.venv/Scripts/ruff.exe" "$PROJECT/.venv/bin/ruff"; do
        if [ -f "$candidate" ]; then RUFF="$candidate"; break; fi
    done
fi
if [ -z "$RUFF" ]; then
    RUFF="$(command -v ruff 2>/dev/null)"
fi
[ -n "$RUFF" ] || exit 0

# --- 3. the three ruff calls -----------------------------------------------------------------
"$RUFF" check "$FILE" --fix --unfixable F401 --force-exclude >/dev/null 2>&1
"$RUFF" format "$FILE" --force-exclude >/dev/null 2>&1
LEFT="$("$RUFF" check "$FILE" --no-fix --force-exclude --output-format concise --quiet 2>/dev/null)"
LEFT_RC=$?

# --- 4. leftover -> additionalContext (only on rc 1) -----------------------------------------
[ "$LEFT_RC" -eq 1 ] || exit 0

read -r -d '' REPORT_PY <<'PYEOF'
import json
import sys

file_path = sys.argv[1]
lines = [line.rstrip('\r') for line in sys.stdin.read().split('\n') if line.strip()]
if not lines:
    sys.exit(0)
head = f'autoformat-python: {len(lines)} ruff issue(s) left in {file_path} — not auto-fixed, pre-commit will reject:'
context = '\n'.join([head] + lines[:10])
output = {'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': context}}
sys.stdout.write(json.dumps(output, ensure_ascii=True))
PYEOF

printf '%s' "$LEFT" | PYTHONIOENCODING=utf-8 $PY -c "$REPORT_PY" "$FILE" 2>/dev/null
exit 0
