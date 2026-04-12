#!/bin/bash
# PostToolUse hook: проверка синтаксиса Python после Edit/Write
# Неблокирующий (exit 0 всегда)

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_name',''))" 2>/dev/null)
FILE_PATH=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); i=d.get('tool_input',{}); print(i.get('file_path',''))" 2>/dev/null)

# Только для Edit/Write
case "$TOOL_NAME" in
    Edit|Write) ;;
    *) exit 0 ;;
esac

# Только .py файлы
[[ "$FILE_PATH" != *.py ]] && exit 0
[[ ! -f "$FILE_PATH" ]] && exit 0

# Ищем python
PYTHON=""
if [[ -f ".venv/bin/python" ]]; then
    PYTHON=".venv/bin/python"
elif [[ -f ".venv/Scripts/python.exe" ]]; then
    PYTHON=".venv/Scripts/python.exe"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    exit 0
fi

# Проверка синтаксиса через py_compile
RESULT=$($PYTHON -m py_compile "$FILE_PATH" 2>&1)
if [[ $? -ne 0 ]]; then
    echo "WARNING: Синтаксическая ошибка в $FILE_PATH:"
    echo "$RESULT"
fi

exit 0
