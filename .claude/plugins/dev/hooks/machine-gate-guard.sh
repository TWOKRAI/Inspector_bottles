#!/usr/bin/env bash
# machine-gate-guard.sh (Task 1.1, план tooling-machine-gate-hook) — PreToolUse, matcher Bash.
#
# Пока существует machine.lock (координатор на общей машине), Bash-команда с тестом или тяжёлой
# работой мимо scripts/machine_gate.sh блокируется: код выхода 2, в stderr — команда гейта.
# Класс команды решает `machine_gate.sh classify`, хук сам ничего не классифицирует: блок только по
# непустому ответу classify. Любая внутренняя ошибка (нет python, битый JSON, нет гейта, сбой
# classify) — пропуск, код 0: хук не граница безопасности, а напоминание.
#
# Порядок: замка нет -> 0; дешёвый grep по словам-кандидатам до запуска python; команда из JSON
# через python (печать без CR: на Windows `read < <(...)` убивает хук хвостовым \r, поэтому
# `$(... | tr -d '\r')`); гейт ищется от самого хука, а не от cwd (субагент в worktree может стоять
# в любом каталоге); stdout не пишется никогда.
#
# Окружение: MACHINE_LOCK_DIR — каталог замков (по умолчанию общий каталог машины).

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

lock="${MACHINE_LOCK_DIR:-/d/PROJECT_INNOTECH/Inspector_vision}/machine.lock"
[ -e "$lock" ] || exit 0

INPUT=$(cat)
printf '%s' "$INPUT" | grep -qE 'pytest|run_framework_tests|run_sim_all|check_injections|mutation_gate|break_inject|reindex|qex_retry|make' || exit 0

# python-bin.sh делает `exit 1`, если интерпретатора нет: читаем его в подоболочке, чтобы пропустить, а не упасть.
PYLIB="$HOOK_DIR/../../core/hooks/_lib/python-bin.sh"
PY=""
[ -f "$PYLIB" ] && PY=$(source "$PYLIB" 2>/dev/null; printf '%s' "${PY:-}")
[ -n "$PY" ] || exit 0

# shellcheck disable=SC2086  # $PY может быть `py -3`
CMD=$(printf '%s' "$INPUT" | $PY -c '
import json, sys
try:
    command = json.loads(sys.stdin.buffer.read().decode("utf-8"))["tool_input"]["command"]
except Exception:
    sys.exit(0)
if isinstance(command, str):
    sys.stdout.write(command)
' 2>/dev/null | tr -d '\r')
[ -n "$CMD" ] || exit 0

gate="$HOOK_DIR/../../../../scripts/machine_gate.sh"
[ -f "$gate" ] || exit 0

out=$(bash "$gate" classify "$CMD" 2>/dev/null) || exit 0
[ -n "$out" ] || exit 0

# Совет строится по строке classify с НАИБОЛЬШИМ рангом (light < medium < heavy, при равенстве первая):
# так же гейт поднимает заявку (classification.md §4).
best=0
kind=""
reason=""
segment=""
while IFS=$'\t' read -r k r seg; do
    case $k in light) rk=1 ;; medium) rk=2 ;; heavy) rk=3 ;; *) rk=0 ;; esac
    if [ "$rk" -gt "$best" ]; then
        best=$rk
        kind=$k
        reason=$r
        segment=$seg
    fi
done <<<"$out"
[ -n "$kind" ] || exit 0

# Ведущие VAR=val сегмента ставятся ПЕРЕД bash: после слова <session> они стали бы командой, а не окружением.
vars=""
while [[ $segment =~ ^[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+ ]]; do
    vars+="${BASH_REMATCH[0]}"
    segment=${segment:${#BASH_REMATCH[0]}}
done

{
    printf 'BLOCKED by machine-gate-guard: machine.lock exists and this command is %s (%s) but does not go through the gate.\n' "$kind" "$reason"
    printf 'Run instead: %sbash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" %s <session> %s\n' "$vars" "$kind" "$segment"
    printf '<session> = the name in your brief; no name -> ask the lead. Exit 75 = skipped by the gate (NO WINDOW), not a red run.\n'
    printf 'hook: %s\n' "$0"
} >&2
exit 2
