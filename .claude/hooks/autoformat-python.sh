#!/bin/bash
# PostToolUse: автоформатирование Python-файлов после Edit/Write
# Запускает ruff format + ruff check --fix на изменённом файле
# Выход 0 всегда — не блокирует работу при ошибках ruff

INPUT=$(cat)
# Один python-вызов вместо двух — на Windows экономит ~300-500мс на каждый Edit/Write
read -r TOOL_NAME FILE_PATH < <(python3 -c "import sys,json
d=json.load(sys.stdin)
print(d.get('tool_name',''), d.get('tool_input',{}).get('file_path',''))" <<< "$INPUT" 2>/dev/null)

# Только Edit и Write
if [[ "$TOOL_NAME" != "Edit" && "$TOOL_NAME" != "Write" ]]; then
    exit 0
fi

# Только Python
if [[ "$FILE_PATH" != *.py ]]; then
    exit 0
fi

# Файл должен существовать
if [[ -z "$FILE_PATH" || ! -f "$FILE_PATH" ]]; then
    exit 0
fi

# Проверяем наличие ruff (поддержка venv на Windows через Git Bash)
RUFF_CMD=""
if command -v ruff &>/dev/null; then
    RUFF_CMD="ruff"
elif [[ -f "venv/Scripts/ruff.exe" ]]; then
    RUFF_CMD="venv/Scripts/ruff.exe"
elif [[ -f "venv/bin/ruff" ]]; then
    RUFF_CMD="venv/bin/ruff"
fi

if [[ -z "$RUFF_CMD" ]]; then
    exit 0
fi

# Форматирование
"$RUFF_CMD" format "$FILE_PATH" --quiet 2>/dev/null


# Автофикс линтера (только безопасные правила)
"$RUFF_CMD" check "$FILE_PATH" --fix --quiet 2>/dev/null

exit 0
