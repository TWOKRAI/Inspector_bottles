#!/bin/bash
# Stop hook: в конце сессии добавляет краткую сводку в knowledge/wiki/daily/YYYY-MM-DD.md.
# Дешёвая версия (без LLM): timestamp + список изменённых файлов из git status + git diff stats.
#
# Это закрывает Karpathy "session-end" хук без вызова Claude Agent SDK.
# Полную семантическую компиляцию делает /compile когда пользователь готов.
#
# Тихий: exit 0 на всё, не блокирует Stop.

set -e

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DAILY_DIR="$REPO_ROOT/knowledge/wiki/daily"
DATE="$(date +%Y-%m-%d)"
TIME="$(date +%H:%M)"
DAILY_FILE="$DAILY_DIR/$DATE.md"

mkdir -p "$DAILY_DIR"

# Если файл новый — frontmatter
if [ ! -f "$DAILY_FILE" ]; then
    cat > "$DAILY_FILE" <<EOF
---
title: "Сессии $DATE"
type: daily
date: $DATE
status: raw
---

# Дневной журнал — $DATE

> Авто-сборка из git. Сжатая версия — после \`/compile\` попадёт в \`wiki/{topic}/\`.

EOF
fi

# Список изменённых файлов в этой сессии (грубо: всё что в git status)
CHANGED_FILES=$(cd "$REPO_ROOT" && git status --short 2>/dev/null | head -30 || true)
DIFF_STAT=$(cd "$REPO_ROOT" && git diff --shortstat 2>/dev/null || true)
BRANCH=$(cd "$REPO_ROOT" && git branch --show-current 2>/dev/null || echo "?")

# Если ничего не изменилось — не пишем
if [ -z "$CHANGED_FILES" ]; then
    exit 0
fi

# Append секцию "## [HH:MM] session-end"
{
    echo ""
    echo "## [$TIME] session-end | branch=$BRANCH"
    echo ""
    echo "**Изменения (\`git status\`):**"
    echo '```'
    echo "$CHANGED_FILES"
    echo '```'
    if [ -n "$DIFF_STAT" ]; then
        echo ""
        echo "**Diff stat:** $DIFF_STAT"
    fi
} >> "$DAILY_FILE"

exit 0
