#!/usr/bin/env bash
# Гейт нагрузки на общей машине (skill `coordinator`, project-rules §8).
#
#   bash scripts/machine_gate.sh heavy|light <session> <команда...>
#
# heavy — полный прогон, матрица инъекций, серия e2e, стенд, индексация qex:
#         только если строка `window:` в machine.lock — у этой сессии.
# light — один pytest-процесс по своим файлам: можно всегда, кроме чужого окна `quiet`.
# Нет machine.lock (координатора нет) — действует старый протокол: при чужом
# `measure` в stand.lock не запускать ничего.
#
# Код выхода: код команды; 75 — пропущено гейтом (не путать с красным прогоном).
set -u

if [ $# -lt 3 ]; then
    echo "usage: machine_gate.sh heavy|light <session> <command...>" >&2
    exit 2
fi
kind=$1
session=$2
shift 2

lock_dir=${MACHINE_LOCK_DIR:-/d/PROJECT_INNOTECH/Inspector_vision}
machine_lock=$lock_dir/machine.lock
stand_lock=$lock_dir/stand.lock

skip() {
    echo "$1 — skipped (machine_gate: $kind, $session)"
    exit 75
}

case $kind in heavy | light) ;; *) echo "kind must be heavy or light" >&2; exit 2 ;; esac

# Поля строк замков разделены « | »; имя сравнивается целиком, не как регулярное выражение.
if [ -e "$machine_lock" ]; then
    if awk -F' [|] ' -v s="window: $session" '$1 == s {f = 1} END {exit !f}' "$machine_lock"; then
        :
    elif [ "$kind" = heavy ]; then
        skip "NO WINDOW"
    elif awk -F' [|] ' '$1 ~ /^window: / && $2 == "quiet" {f = 1} END {exit !f}' "$machine_lock"; then
        skip "QUIET WINDOW"
    fi
elif [ -e "$stand_lock" ] &&
    awk -F' [|] ' -v s="$session" '$3 == "measure" && $1 != s {f = 1} END {exit !f}' "$stand_lock"; then
    skip "STAND MEASURE (stand.lock)"
fi

"$@"
