#!/usr/bin/env bash
# Установка sentrux pre-push hook.
#
# Использование:
#   bash scripts/install_pre_push_hook.sh
#
# Hook блокирует `git push` при:
#   1) нарушении правил из .sentrux/rules.toml (sentrux check)
#   2) структурной регрессии относительно baseline (sentrux gate)
#
# Обновить baseline после намеренного улучшения:
#   sentrux gate --save
#
# Обойти (только в крайних случаях):
#   git push --no-verify

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
SRC="$REPO_ROOT/scripts/hooks/pre-push"
DST="$REPO_ROOT/.git/hooks/pre-push"

if [ ! -f "$SRC" ]; then
    echo "error: $SRC не найден" >&2
    exit 1
fi

cp "$SRC" "$DST"
chmod +x "$DST"
echo "✓ Установлен pre-push hook: $DST"
echo ""
echo "Проверь работу:"
echo "  bash $DST"
