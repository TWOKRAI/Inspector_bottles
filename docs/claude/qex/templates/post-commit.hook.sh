#!/usr/bin/env bash
# ============================================================================
# qex auto-reindex — git post-commit hook
# ============================================================================
#
# Назначение:
#   Автоматически переиндексирует qex после каждого коммита, чтобы
#   семантический поиск не отставал от текущего состояния кода.
#
# Установка:
#   1. Скопируй этот файл в .git/hooks/post-commit проекта:
#        cp docs/claude/qex/templates/post-commit.hook.sh .git/hooks/post-commit
#   2. Сделай его исполняемым:
#        chmod +x .git/hooks/post-commit
#   3. Проверь, что запускается:
#        git commit --allow-empty -m "test qex hook"
#
# Как работает:
#   - Запускается ПОСЛЕ каждого git commit.
#   - Вызывает qex через MCP stdio напрямую (индексирует в фоне, не блокирует).
#   - Работает инкрементально: qex сравнивает snapshot и переиндексирует
#     только изменённые файлы. Обычно < 5 секунд.
#
# Требования:
#   - qex-mcp-v2 доступен в PATH или указан явно через QEX_BIN ниже.
#   - Qdrant и Ollama запущены (если нет — hook просто ничего не сделает).
#
# Отключение:
#   chmod -x .git/hooks/post-commit
#   или удалить файл .git/hooks/post-commit
#
# ============================================================================

set -euo pipefail

# --- Настройки (отредактируй под свой проект) ---
QEX_BIN="${QEX_BIN:-$HOME/.local/bin/qex-mcp-v2}"
PROJECT_ROOT="$(git rev-parse --show-toplevel)"
LOG_FILE="$PROJECT_ROOT/.qex-reindex.log"

# --- Быстрая проверка зависимостей (без ошибок, если чего-то нет) ---
if [ ! -x "$QEX_BIN" ]; then
  echo "[qex-hook] qex-mcp-v2 not found at $QEX_BIN, skipping reindex" >&2
  exit 0
fi

if ! curl -s --max-time 1 http://localhost:6333/healthz > /dev/null 2>&1; then
  echo "[qex-hook] Qdrant not reachable, skipping reindex" >&2
  exit 0
fi

if ! curl -s --max-time 1 http://localhost:11434/ > /dev/null 2>&1; then
  echo "[qex-hook] Ollama not reachable, skipping reindex" >&2
  exit 0
fi

# --- Запуск инкрементальной переиндексации в фоне ---
#
# ВНИМАНИЕ: Этот hook вызывает qex как stdio-MCP-сервер через JSON-RPC.
# Если у тебя qex запускается через Claude Code и уже держит блокировку на
# индексе, фоновая индексация может конфликтовать. В таком случае отключи hook
# и запускай mcp__qex__index_codebase вручную через Claude Code.
#
# Альтернатива (проще): просто оставь заметку "reindex after commit" и делай
# это вручную раз в N коммитов.

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Triggering qex incremental reindex for $PROJECT_ROOT"

  # Простейший JSON-RPC запрос к qex через stdio.
  # Если твоя версия qex-mcp-v2 не поддерживает такой прямой вызов,
  # закомментируй блок ниже и используй Claude Code вручную.
  printf '%s\n' \
    '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"index_codebase","arguments":{"path":"'"$PROJECT_ROOT"'"}}}' \
    | "$QEX_BIN" 2>&1 || echo "qex stdio call failed (likely: server held by Claude Code)"

} >> "$LOG_FILE" 2>&1 &

disown || true
exit 0
