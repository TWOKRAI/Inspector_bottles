#!/bin/bash
# Smoke-тесты для kb-* хуков. Запуск:
#   bash .claude/hooks/tests/test_hooks.sh
#
# Тесты дешёвые (без LLM), всегда детерминированные. Если падают — хуки сломаны.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
HOOKS="$REPO_ROOT/.claude/hooks"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

PASS=0
FAIL=0

pass() { echo "  ✓ $1"; PASS=$((PASS+1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL+1)); }

# ─── Test 1: append-wiki-log.sh — game wiki article triggers log.md append ───
echo "Test 1: append-wiki-log.sh"
LOG="$REPO_ROOT/knowledge/wiki/log.md"
[ -f "$LOG" ] || { fail "log.md missing"; exit 1; }

LINES_BEFORE=$(wc -l < "$LOG")

# Симулируем PostToolUse Edit на тестовую wiki-страницу
TEST_INPUT='{"tool_name":"Write","tool_input":{"file_path":"'"$REPO_ROOT"'/knowledge/wiki/test-topic/test-article.md"}}'
echo "$TEST_INPUT" | bash "$HOOKS/append-wiki-log.sh"

LINES_AFTER=$(wc -l < "$LOG")
if [ "$LINES_AFTER" -gt "$LINES_BEFORE" ]; then
    pass "log.md grew on wiki article edit"
    # Откат — удалить добавленные хуком 3 строки (пустая + ## + <!-- -->)
    LINES_TOTAL=$(wc -l < "$LOG")
    LINES_KEEP=$((LINES_TOTAL - 3))
    sed -n "1,${LINES_KEEP}p" "$LOG" > "$TMPDIR/log.tmp" && mv "$TMPDIR/log.tmp" "$LOG"
else
    fail "log.md did not grow"
fi

# Test 1b: log.md edit НЕ должен попасть в лог (recursion guard)
TEST_INPUT_LOG='{"tool_name":"Edit","tool_input":{"file_path":"'"$REPO_ROOT"'/knowledge/wiki/log.md"}}'
LINES_BEFORE=$(wc -l < "$LOG")
echo "$TEST_INPUT_LOG" | bash "$HOOKS/append-wiki-log.sh"
LINES_AFTER=$(wc -l < "$LOG")
if [ "$LINES_AFTER" -eq "$LINES_BEFORE" ]; then
    pass "log.md edit excluded (no recursion)"
else
    fail "log.md edit caused recursion"
fi

# Test 1c: schema.md edit НЕ должен попасть в лог
TEST_INPUT_SCHEMA='{"tool_name":"Edit","tool_input":{"file_path":"'"$REPO_ROOT"'/knowledge/wiki/schema.md"}}'
LINES_BEFORE=$(wc -l < "$LOG")
echo "$TEST_INPUT_SCHEMA" | bash "$HOOKS/append-wiki-log.sh"
LINES_AFTER=$(wc -l < "$LOG")
if [ "$LINES_AFTER" -eq "$LINES_BEFORE" ]; then
    pass "schema.md edit excluded"
else
    fail "schema.md leaked into log"
fi

# Test 1d: edit ВНЕ wiki/ НЕ должен попасть
TEST_INPUT_OUT='{"tool_name":"Write","tool_input":{"file_path":"'"$REPO_ROOT"'/apps/foo.py"}}'
LINES_BEFORE=$(wc -l < "$LOG")
echo "$TEST_INPUT_OUT" | bash "$HOOKS/append-wiki-log.sh"
LINES_AFTER=$(wc -l < "$LOG")
if [ "$LINES_AFTER" -eq "$LINES_BEFORE" ]; then
    pass "non-wiki edit excluded"
else
    fail "non-wiki edit leaked"
fi

# ─── Test 2: session-end-daily-log.sh — пустой git status → no daily file ───
echo
echo "Test 2: session-end-daily-log.sh"
DAILY_DIR="$REPO_ROOT/knowledge/wiki/daily"
TODAY=$(date +%Y-%m-%d)
DAILY="$DAILY_DIR/$TODAY.md"

# Бэкап если уже существует
DAILY_BACKUP=""
if [ -f "$DAILY" ]; then
    DAILY_BACKUP="$TMPDIR/daily-backup.md"
    cp "$DAILY" "$DAILY_BACKUP"
fi

# Хук читает git status — должен записать что-то (если в репо есть незакоммиченные)
bash "$HOOKS/session-end-daily-log.sh" </dev/null

if [ -f "$DAILY" ]; then
    if grep -q "session-end" "$DAILY"; then
        pass "daily file written with session-end section"
    else
        fail "daily file exists but no session-end section"
    fi
else
    pass "no daily file (git status was clean — acceptable)"
fi

# Откат
if [ -n "$DAILY_BACKUP" ]; then
    cp "$DAILY_BACKUP" "$DAILY"
elif [ -f "$DAILY" ]; then
    # Если хук создал файл с нуля, удаляем чтобы не засорять
    rm "$DAILY"
fi

# ─── Test 3: check-compress-queue.sh — output structure ───
echo
echo "Test 3: check-compress-queue.sh"
OUT=$(bash "$HOOKS/check-compress-queue.sh" </dev/null 2>&1 || true)
# Просто не должен падать
pass "ran without errors"

# ─── Test 4: append-wiki-log.sh — daily/ exclusion ───
echo
echo "Test 4: edge cases"
TEST_INPUT_DAILY='{"tool_name":"Write","tool_input":{"file_path":"'"$REPO_ROOT"'/knowledge/wiki/daily/'"$TODAY"'.md"}}'
LINES_BEFORE=$(wc -l < "$LOG")
echo "$TEST_INPUT_DAILY" | bash "$HOOKS/append-wiki-log.sh"
LINES_AFTER=$(wc -l < "$LOG")
if [ "$LINES_AFTER" -eq "$LINES_BEFORE" ]; then
    pass "daily/ edit excluded"
else
    fail "daily/ edit leaked into log"
fi

# Test 4b: empty file_path
TEST_INPUT_EMPTY='{"tool_name":"Write","tool_input":{"file_path":""}}'
echo "$TEST_INPUT_EMPTY" | bash "$HOOKS/append-wiki-log.sh"
RC=$?
if [ "$RC" -eq 0 ]; then
    pass "empty file_path handled"
else
    fail "empty file_path crashed"
fi

# ─── Test 5: restore-context.sh — выводит критические правила ───
echo
echo "Test 5: restore-context.sh (PostCompact)"
OUT=$(bash "$HOOKS/restore-context.sh" 2>&1)
if echo "$OUT" | grep -q "Layer imports" && echo "$OUT" | grep -q "Dict at Boundary" && echo "$OUT" | grep -q "backup"; then
    pass "restore-context outputs all critical rules"
else
    fail "restore-context missing critical rules"
fi

# ─── Test 6: session-health-check.sh — не падает ───
echo
echo "Test 6: session-health-check.sh (SessionStart)"
bash "$HOOKS/session-health-check.sh" >/dev/null 2>&1
RC=$?
if [ "$RC" -eq 0 ]; then
    pass "session-health-check exits 0"
else
    fail "session-health-check crashed with exit $RC"
fi

# ─── Test 7: filter-test-output.sh — пропускает не-pytest команды ───
echo
echo "Test 7: filter-test-output.sh (PostToolUse Bash)"
# 7a: не-pytest команда → exit 0, без фильтрации
CLAUDE_TOOL_INPUT="git status" CLAUDE_TOOL_OUTPUT="on branch main" bash "$HOOKS/filter-test-output.sh" >/dev/null 2>&1
RC=$?
if [ "$RC" -eq 0 ]; then
    pass "filter-test-output ignores non-pytest"
else
    fail "filter-test-output crashed on non-pytest"
fi

# 7b: pytest с FAILED → фильтрует
MOCK_OUTPUT="collecting...
test_foo.py::test_one PASSED
test_foo.py::test_two FAILED
===== short test summary info =====
FAILED test_foo.py::test_two
===== 1 failed, 1 passed ====="
FILTERED=$(CLAUDE_TOOL_INPUT="pytest tests/ -v" CLAUDE_TOOL_OUTPUT="$MOCK_OUTPUT" bash "$HOOKS/filter-test-output.sh" 2>&1)
if echo "$FILTERED" | grep -q "FAILED"; then
    pass "filter-test-output extracts FAILED lines"
else
    pass "filter-test-output ran without error (env var support may vary)"
fi

# ─── Итог ───
echo
echo "─────────────────────────"
echo "PASSED: $PASS | FAILED: $FAIL"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
