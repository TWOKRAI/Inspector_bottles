#!/usr/bin/env bash
# Idempotent setup для qex embedding-модели: форсирует 100% GPU.
#
# Что и зачем:
#   ollama по умолчанию читает num_ctx из OLLAMA_CONTEXT_LENGTH env. Если он не
#   установлен (или установлен слишком большим), embedding-модель раздувается
#   через KV cache, не помещается в VRAM ноутбучных GPU и offload'ится в CPU.
#   Результат — таймауты на индексации больших репо через qex MCP.
#
# Решение:
#   Создаём Modelfile-вариант базовой модели с явным num_ctx и num_gpu=999.
#   Подменяем оригинальный tag (qwen3-embedding:4b / 8b) этой копией. После
#   этого qex-launcher без правки кода грузит модель на 100% GPU.
#
# Per-platform:
#   Windows (RTX 3050 Laptop, 4 GB VRAM)  → qwen3-embedding:4b, num_ctx=2048
#   macOS   (Apple Silicon, unified)       → qwen3-embedding:8b, num_ctx=4096
#
# Usage: bash setup-embedding-model.sh
# Re-run: безопасно — повторные запуски только пересоздают вариант, не ломают.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATES_DIR="$SCRIPT_DIR/templates"

case "$(uname -s)" in
    Darwin*) PLATFORM="mac" ;;
    Linux*|MINGW*|MSYS*|CYGWIN*) PLATFORM="win" ;;
    *) PLATFORM="win" ;;
esac

if [ "$PLATFORM" = "mac" ]; then
    BASE="qwen3-embedding:8b"
    MODELFILE="$TEMPLATES_DIR/qwen3-embedding-8b-mac.Modelfile"
    VARIANT="qwen3-embedding:8b-qex"
else
    BASE="qwen3-embedding:4b"
    MODELFILE="$TEMPLATES_DIR/qwen3-embedding-4b-win.Modelfile"
    VARIANT="qwen3-embedding:4b-qex"
fi

if ! command -v ollama > /dev/null 2>&1; then
    echo "✗ ollama не найдена в PATH. Установи Ollama и перезапусти скрипт."
    exit 1
fi

if ! curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✗ ollama сервер не отвечает на :11434. Запусти 'ollama serve' или Ollama Desktop."
    exit 1
fi

if ! ollama list 2>/dev/null | grep -q "^${BASE%:*}\s.*${BASE#*:}"; then
    echo "→ pulling $BASE (первый запуск, может занять время)..."
    ollama pull "$BASE"
fi

echo "→ создаю GPU-оптимизированный вариант $VARIANT из $MODELFILE"
ollama create "$VARIANT" -f "$MODELFILE"

echo "→ подменяю $BASE на $VARIANT (qex-launcher без правки кода использует обновлённый tag)"
ollama stop "$BASE" 2>/dev/null || true
ollama rm "$BASE" 2>/dev/null || true
ollama cp "$VARIANT" "$BASE"

echo "→ verify: загрузка $BASE с прогревом"
curl -s http://localhost:11434/api/embeddings \
    -d "{\"model\":\"$BASE\",\"prompt\":\"warm-up\"}" > /dev/null
echo
ollama ps
echo
echo "✓ done. PROCESSOR должен быть '100% GPU'. Если 'CPU' — проверь VRAM (nvidia-smi)."
