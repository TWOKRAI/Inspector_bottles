#!/bin/bash
# PreToolUse Bash hook: catches verbatim-paste of textbook-dangerous commands.
#
# IMPORTANT: This is NOT a security boundary.
# Regex-based blocklists for arbitrary shell commands are known-incomplete.
# Trivial bypasses include:
#   - bash -c "rm -rf /"           (indirection)
#   - /bin/rm -rf /                 (absolute path prefix)
#   - rm -r -f /                    (split flags)
#   - python3 -c "shutil.rmtree('/')"  (different tool)
#
# Real defense lives in .claude/settings.json `permissions.deny[]` (whole-command
# patterns) and `permissions.ask[]` (interactive confirmation). This hook adds
# a thin "did the model literally paste `rm -rf /`?" guard — useful for
# accidental hallucinations, not against a determined adversary.
#
# Keep this hook conservative: false positives are worse than false negatives
# because the real defense is elsewhere.
#
# Exit 2 = block (PreToolUse contract).

# Resolve Python interpreter (python3 on Linux/macOS, python on Windows).
source "$(dirname "$0")/../_lib/python-bin.sh"

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | $PY -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)

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
        exit 2
    fi
done

exit 0
