#!/bin/bash
# FROZEN 2026-10-04: removed from plugin.json and settings.json; do not wire it back. Measured in
# plans/2026-10-03_commit-mechanism/tasks/1.4.md. On Windows the `read -r TOOL FILE < <($PY ...)` parse keeps a
# trailing \r in FILE, so the `*.py` test fails and the hook exits before it does any work. Alive, it only runs
# py_compile (it checks no imports) and prints plain text to stdout, which the agent never sees; it duplicates the
# ruff `invalid-syntax` report of autoformat-python.sh, except under .claude/, robot/ and docs/claude/frozen/, where
# pre-commit `debug-statements` catches the syntax error at commit. It costs 0.2-0.33 s on every edit of any file.
# PostToolUse hook: проверка синтаксиса Python после Edit/Write
# Неблокирующий (exit 0 всегда)

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
# Один python-вызов вместо двух — на Windows экономит ~300-500мс на каждый Edit/Write
read -r TOOL_NAME FILE_PATH < <($PY -c "import sys,json
d=json.load(sys.stdin)
print(d.get('tool_name',''), d.get('tool_input',{}).get('file_path',''))" <<< "$INPUT" 2>/dev/null)

# Только для Edit/Write
case "$TOOL_NAME" in
    Edit|Write) ;;
    *) exit 0 ;;
esac

# Только .py файлы
[[ "$FILE_PATH" != *.py ]] && exit 0
[[ ! -f "$FILE_PATH" ]] && exit 0

# For py_compile, prefer the project's venv (resolves project deps), fall back
# to the resolved $PY from python-bin.sh.
PYTHON=""
if [[ -f ".venv/bin/python" ]]; then
    PYTHON=".venv/bin/python"
elif [[ -f ".venv/Scripts/python.exe" ]]; then
    PYTHON=".venv/Scripts/python.exe"
else
    PYTHON="$PY"
fi

# Проверка синтаксиса через py_compile
RESULT=$($PYTHON -m py_compile "$FILE_PATH" 2>&1)
if [[ $? -ne 0 ]]; then
    echo "WARNING: syntax error in $FILE_PATH:"
    echo "$RESULT"
fi

exit 0
