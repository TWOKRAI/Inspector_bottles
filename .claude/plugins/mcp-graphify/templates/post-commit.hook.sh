#!/usr/bin/env bash
# ============================================================================
# graphify incremental update — секция для git post-commit hook
# ============================================================================
#
# Установка:
#   Если .git/hooks/post-commit ПУСТ — скопируй файл целиком:
#     cp .claude/plugins/mcp-graphify/templates/post-commit.hook.sh .git/hooks/post-commit
#     chmod +x .git/hooks/post-commit
#
#   Если там уже живёт чужой хук (например qex-reindex) — вставь блок
#   «graphify incremental update» ниже, соблюдая ЛОВУШКУ ПОРЯДКА.
#
# ⚠ ЛОВУШКА ПОРЯДКА (наступлено 2026-08-27, стоило одного молчаливого провала).
#   qex-секция при недоступной Ollama делает `exit 0` — это завершает ВЕСЬ хук,
#   а не только свою часть. Блок, дописанный НИЖЕ такого guard'а, недостижим
#   каждый раз, когда Ollama лежит: коммит проходит, лога нет, ошибки нет.
#   Поэтому graphify-блок ставить ВЫШЕ любых ранних `exit`, сразу после
#   определения PROJECT_ROOT. Проверять — прямым запуском `bash .git/hooks/post-commit`
#   и наличием .graphify-update.log, а не «коммит прошёл, значит работает».
#
# ЧЕГО ЭТОТ ХУК НЕ ДЕЛАЕТ:
#   1. Не чистит мусор. Инкремент добавляет, но не удаляет узлы исчезнувших
#      файлов и не выбрасывает то, что попало под новые правила .graphifyignore.
#      Замер 2026-08-27: в графе жили 3 файла-призрака и 51 тест вопреки ignore.
#      Снимает только полная пересборка:  graphify update . --force
#   2. Не именует новые сообщества. `update` ре-кластеризует, свежие кластеры
#      получают заглушки "Community N". Догонять:
#        graphify label . --missing-only
#      ⚠ НЕ через --backend=claude-cli без расчёта цены: это полная сессия
#      Claude Code на КАЖДЫЙ батч (~50k токенов накладных на вызов). Замер
#      2026-08-27: 53 вызова ≈ 2.5 млн входных токенов. Мельчить batch-size =
#      множить накладные. См. docs/claude/memory/
#      feedback_claude_cli_backend_costs_a_full_session.md
#
# Отключение: закомментировать блок или chmod -x .git/hooks/post-commit
#   (последнее выключит и соседние секции).
# ============================================================================

set -euo pipefail

PROJECT_ROOT="$(git rev-parse --show-toplevel)"

# --- graphify: инкрементальное обновление графа (LLM не нужен) ---------------
if command -v graphify >/dev/null 2>&1 && [ -f "$PROJECT_ROOT/graphify-out/graph.json" ]; then
  {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] graphify incremental update: $PROJECT_ROOT"
    cd "$PROJECT_ROOT" && graphify update . 2>&1 || echo "graphify update failed (не блокирует коммит)"
  } >> "$PROJECT_ROOT/.graphify-update.log" 2>&1 &
  disown || true
else
  echo "[graphify-hook] graphify или graph.json не найдены, пропускаю" >&2
fi

exit 0
