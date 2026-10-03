#!/usr/bin/env bash
# autofix-text.sh (Task 1.2) - PostToolUse, matcher "Edit|Write": fixes trailing
# whitespace and the end-of-file newline of a non-Python text file the agent just
# wrote, with the same algorithms pre-commit runs at commit time
# (pre-commit-hooks v5.0.0: trailing-whitespace --markdown-linebreak-ext=md, then
# end-of-file-fixer). Python files belong to ruff (autoformat-python.sh).
#
# All logic lives in autofix_text.py (stdlib only): which files are skipped, the
# in-memory fix, and the single guarded write. This wrapper only finds Python.
#
# Exit code ALWAYS 0 and stdout ALWAYS empty: the harness parses a PostToolUse
# hook's stdout as JSON, and this hook has nothing to tell the agent.

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# python-bin.sh `exit 1`s when no interpreter is found - run it in a subshell so
# that never surfaces as a "hook error".
PY="$(source "$HOOK_DIR/_lib/python-bin.sh" 2>/dev/null && printf '%s' "$PY")" || exit 0
[ -n "${PY:-}" ] || exit 0

# The payload goes to autofix_text.py on stdin (it calls json.load(sys.stdin)).
# $PY unquoted on purpose: python-bin.sh may export "py -3".
CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-}" \
  PYTHONIOENCODING=utf-8 \
  $PY "$HOOK_DIR/autofix_text.py" >/dev/null 2>&1
exit 0
