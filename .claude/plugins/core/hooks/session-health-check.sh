#!/usr/bin/env bash
# SessionStart hook — проверка здоровья окружения при старте сессии
# Предупреждает если Ollama не запущена (qex не будет работать)

# Проверка Ollama
if ! curl -s --max-time 2 http://localhost:11434/ 2>/dev/null | grep -q "running"; then
  echo "⚠ Ollama is not running. qex/semantic search is unavailable. Start it: ollama serve"
fi

exit 0
