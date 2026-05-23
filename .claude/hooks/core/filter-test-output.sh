#!/usr/bin/env bash
# PostToolUse(Bash) — фильтрует вывод pytest, оставляя только ошибки
# Экономит 5-10K токенов на каждый прогон с падениями

# Получаем вход от Claude Code
input="$CLAUDE_TOOL_INPUT"
output="$CLAUDE_TOOL_OUTPUT"

# Срабатывает только для pytest-команд
if ! echo "$input" | grep -qE "pytest|run_framework_tests"; then
  exit 0
fi

# Если тесты прошли — не фильтруем (короткий вывод)
if echo "$output" | grep -qE "passed|no tests ran"; then
  if ! echo "$output" | grep -qE "FAILED|ERROR|failed"; then
    exit 0
  fi
fi

# Фильтруем: оставляем FAILED, ERROR, short summary, warnings summary
echo "$output" | grep -E "(FAILED|ERROR|ERRORS|short test summary|warnings summary|=====)" | head -40

exit 0
