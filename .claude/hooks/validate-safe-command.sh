#!/bin/bash
# Валидация безопасности bash-команд
# Выход с кодом 2 блокирует выполнение

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Расширенный список опасных паттернов (с регулярными выражениями)
DANGEROUS_PATTERNS=(
    # Удаление корневых директорий
    "rm\s+(-rf?|--recursive\s+--force)\s+/"
    "rm\s+(-rf?|--recursive\s+--force)\s+/\*"
    "rm\s+(-rf?|--recursive\s+--force)\s+~"
    "rm\s+(-rf?|--recursive\s+--force)\s+\$HOME"
    # С sudo
    "sudo\s+rm\s+(-rf?|--recursive\s+--force)"
    "sudo\s+dd\s+if=/dev/zero"
    "sudo\s+mkfs"
    "sudo\s+chmod\s+777"
    # Форматирование дисков
    "mkfs\."
    "dd\s+if=/dev/zero"
    "dd\s+of=/dev/sd"
    # Fork bomb
    ":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\};:"
    # Опасные перенаправления
    ">\s*/dev/sda"
    ">\s*/dev/hda"
    # Скачивание и выполнение скриптов
    "curl.*\|.*sh"
    "curl.*\|.*bash"
    "wget.*\|.*sh"
    "wget.*\|.*bash"
    "curl.*-o.*\.sh.*&&\s+sh"
    # Изменение прав всей системы
    "chmod\s+777\s+/"
    "chmod\s+777\s+/etc"
    "chmod\s+-\R\s+777"
    # Уничтожение данных
    "cat\s+/dev/zero\s+>"
)

for pattern in "${DANGEROUS_PATTERNS[@]}"; do
    if echo "$COMMAND" | grep -qE "$pattern"; then
        echo "Blocked: Dangerous command detected matching: $pattern" >&2
        logger -t "claude-hook" "Blocked command: $COMMAND (pattern: $pattern)"
        exit 2
    fi
done

exit 0