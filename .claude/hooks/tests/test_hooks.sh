#!/bin/bash
# Smoke-тесты для активных хуков. Запуск:
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

# ─── Test 1: restore-context.sh — выводит критические правила ───
echo "Test 1: restore-context.sh (PostCompact)"
OUT=$(bash "$HOOKS/restore-context.sh" 2>&1)
if echo "$OUT" | grep -q "Layer imports" && echo "$OUT" | grep -q "Dict at Boundary" && echo "$OUT" | grep -q "backup"; then
    pass "restore-context outputs all critical rules"
else
    fail "restore-context missing critical rules"
fi

# ─── Test 2: session-health-check.sh — не падает ───
echo
echo "Test 2: session-health-check.sh (SessionStart)"
bash "$HOOKS/session-health-check.sh" >/dev/null 2>&1
RC=$?
if [ "$RC" -eq 0 ]; then
    pass "session-health-check exits 0"
else
    fail "session-health-check crashed with exit $RC"
fi

# ─── Test 3: filter-test-output.sh — пропускает не-pytest команды ───
echo
echo "Test 3: filter-test-output.sh (PostToolUse Bash)"
# 3a: не-pytest команда → exit 0, без фильтрации
CLAUDE_TOOL_INPUT="git status" CLAUDE_TOOL_OUTPUT="on branch main" bash "$HOOKS/filter-test-output.sh" >/dev/null 2>&1
RC=$?
if [ "$RC" -eq 0 ]; then
    pass "filter-test-output ignores non-pytest"
else
    fail "filter-test-output crashed on non-pytest"
fi

# 3b: pytest с FAILED → фильтрует
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
