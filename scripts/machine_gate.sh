#!/usr/bin/env bash
# Гейт нагрузки на общей машине (skill `coordinator`, project-rules §8).
#
#   bash scripts/machine_gate.sh [--timed] heavy|medium|light <session> <команда...>
#   bash scripts/machine_gate.sh classify <строка команды>
#
# heavy  — полный прогон, матрица инъекций, серия e2e, стенд, индексация qex:
#          только если строка `window:` в machine.lock — у этой сессии.
# medium — каталог тестов одного модуля (`pytest Services/x/tests`): запускается, кроме чужого окна
#          `quiet` / `stand`. Timed medium (флаг `--timed` или команда задевает путь из
#          machine_gate_timed.txt) допускается как heavy.
# light  — один pytest-процесс по своим файлам: можно всегда, кроме чужого окна `quiet`.
# Заявка (heavy|medium|light) поднимается до класса команды, если `classify` даёт класс выше; вниз —
# никогда. Нет machine.lock (координатора нет) — действует старый протокол: при чужом
# `measure` в stand.lock не запускать ничего.
# classify — печатает `<kind>\t<reason>\t<сегмент>` по каждому тестовому сегменту строки
# (plans/2026-10-13_tooling-machine-gate-hook/classification.md §1–§3); код выхода всегда 0.
#
# Код выхода: код команды; 75 — пропущено гейтом (не путать с красным прогоном).
set -u

# --- classify ----------------------------------------------------------------------------------------------------

is_python() {
    case ${1##*/} in python | python3 | python.exe | python3.exe | py) return 0 ;; esac
    return 1
}

# Скрипт по basename -> "kind<TAB>reason" или пусто.
script_class() {
    case ${1##*/} in
        run_framework_tests.py) printf 'heavy\trun_framework_tests' ;;
        run_sim_all.ps1) printf 'heavy\trun_sim_all' ;;
        check_injections.py | mutation_gate.py | break_inject*) printf 'heavy\tinjection_matrix' ;;
        reindex_retry.py | qex_retry.py) printf 'heavy\tqex_index' ;;
    esac
}

# Каталог модуля: после снятия одного хвостового `/`, разбивки по `/` и отбрасывания пустых и `.` сегментов
# не меньше двух сегментов, последний равен `tests`. Обратная косая черта сегменты не режет.
is_module_dir() {
    local t=${1%/} seg last='' n=0 part
    local IFS=/
    read -ra part <<<"$t"
    for seg in "${part[@]}"; do
        if [ -n "$seg" ] && [ "$seg" != . ]; then
            n=$((n + 1))
            last=$seg
        fi
    done
    [ "$n" -ge 2 ] && [ "$last" = tests ]
}

# Аргументы pytest (classification.md §3) -> "kind<TAB>reason".
pytest_class() {
    local tok expect_value=0 xdist=0 has_target=0 bad_dir=0 mod_dirs=0
    for tok in "$@"; do
        if [ "$expect_value" = 1 ]; then
            expect_value=0
            continue
        fi
        case $tok in
            -n* | --numprocesses*) xdist=1 ;;
            -c | -p | -k | -m | -o | --rootdir | --basetemp | --confcutdir | --ignore | --ignore-glob | --deselect)
                expect_value=1
                ;;
            -*) ;;
            *.py | *.py::*) has_target=1 ;;
            */* | *\\*)
                has_target=1
                if is_module_dir "$tok"; then mod_dirs=$((mod_dirs + 1)); else bad_dir=1; fi
                ;;
        esac
    done
    if [ "$xdist" = 1 ]; then
        printf 'heavy\tpytest_xdist'
    elif [ "$has_target" = 0 ]; then
        printf 'heavy\tpytest_no_file_args'
    elif [ "$bad_dir" = 1 ]; then
        printf 'heavy\tpytest_dir_not_module_tests'
    elif [ "$mod_dirs" -ge 2 ]; then
        printf 'heavy\tpytest_multi_dir'
    elif [ "$mod_dirs" = 1 ]; then
        printf 'medium\tpytest_module_dir'
    else
        printf 'light\tpytest_files'
    fi
}

# Один сегмент -> "kind<TAB>reason" или пусто (тестовой команды в позиции команды нет).
classify_segment() {
    local -a toks
    local i=0 n t base j tok
    read -ra toks <<<"$1"
    n=${#toks[@]}
    # Префиксы: VAR=val, timeout N, uv run [--опции].
    while [ "$i" -lt "$n" ]; do
        t=${toks[i]}
        if [[ $t =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
            i=$((i + 1))
        elif [ "$t" = timeout ]; then
            i=$((i + 1))
            while [ "$i" -lt "$n" ] && [[ ${toks[i]} == -* ]]; do i=$((i + 1)); done
            i=$((i + 1))
        elif [ "$t" = uv ] && [ "$((i + 1))" -lt "$n" ] && [ "${toks[i + 1]}" = run ]; then
            i=$((i + 2))
            while [ "$i" -lt "$n" ] && [[ ${toks[i]} == -* ]]; do i=$((i + 1)); done
        else
            break
        fi
    done
    [ "$i" -lt "$n" ] || return 0
    t=${toks[i]//\\//}
    base=${t##*/}
    if [ "$base" = pytest ] || [ "$base" = pytest.exe ]; then
        pytest_class "${toks[@]:i+1}"
    elif is_python "$base"; then
        for ((j = i + 1; j < n; j++)); do
            tok=${toks[j]//\\//}
            if [ "$tok" = -m ]; then
                if [ "$((j + 1))" -lt "$n" ] && [ "${toks[j + 1]}" = pytest ]; then
                    pytest_class "${toks[@]:j+2}"
                fi
                return 0
            elif [[ $tok != -* ]]; then
                script_class "$tok"
                return 0
            fi
        done
    elif [ "$base" = powershell ] || [ "$base" = powershell.exe ]; then
        for ((j = i + 1; j < n; j++)); do
            tok=${toks[j]//\\//}
            if [[ $tok != -* ]]; then
                script_class "$tok"
                return 0
            fi
        done
    fi
    return 0
}

classify_cmd() {
    local segs seg res
    segs=$(printf '%s\n' "$1" | sed -E 's/&&|\|\||;|\|/\n/g')
    while IFS= read -r seg || [ -n "$seg" ]; do
        seg=${seg#"${seg%%[![:space:]]*}"}
        seg=${seg%"${seg##*[![:space:]]}"}
        [ -n "$seg" ] || continue
        case $seg in *machine_gate.sh*) continue ;; esac
        res=$(classify_segment "$seg")
        [ -n "$res" ] || continue
        printf '%s\t%s\n' "$res" "$seg"
    done <<<"$segs"
}

rank() {
    case $1 in light) echo 1 ;; medium) echo 2 ;; heavy) echo 3 ;; *) echo 0 ;; esac
}

set -f # токены команды режутся по пробелам без раскрытия шаблонов
if [ "${1:-}" = classify ]; then
    shift
    classify_cmd "$*"
    exit 0
fi

timed_flag=0
if [ "${1:-}" = --timed ]; then
    timed_flag=1
    shift
fi

if [ $# -lt 3 ]; then
    echo "usage: machine_gate.sh [--timed] heavy|medium|light <session> <command...>" >&2
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

case $kind in heavy | medium | light) ;; *) echo "kind must be heavy, medium or light" >&2; exit 2 ;; esac

# Реклассификация: только вверх, строка с наибольшим рангом (при равенстве — первая).
claim=$kind
best_rank=$(rank "$claim")
best_kind=''
best_reason=''
classified=$(classify_cmd "$*")
while IFS=$'\t' read -r k r _; do
    [ -n "$k" ] || continue
    if [ "$(rank "$k")" -gt "$best_rank" ]; then
        best_rank=$(rank "$k")
        best_kind=$k
        best_reason=$r
    fi
done <<<"$classified"
if [ -n "$best_kind" ]; then
    kind=$best_kind
    echo "machine_gate: reclassified $claim -> $kind ($best_reason)" >&2
fi

# timed: только для итогового medium. Список читается всегда (до проверки окна); нет списка — fail-closed.
timed=0
if [ "$kind" = medium ]; then
    [ "$timed_flag" = 1 ] && timed=1
    timed_list=${MACHINE_GATE_TIMED_LIST:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/machine_gate_timed.txt}
    if [ -f "$timed_list" ] && [ -r "$timed_list" ]; then
        entries=()
        while IFS= read -r line || [ -n "$line" ]; do
            line=${line%$'\r'}
            [ -n "$line" ] && entries+=("$line")
        done <"$timed_list"
        for tok in $*; do
            tok=${tok//\\//}
            for entry in "${entries[@]}"; do
                case $tok in *"$entry"*) timed=1 ;; esac
            done
        done
    else
        echo "machine_gate: timed list not found: $timed_list" >&2
        timed=1
    fi
fi

# Поля строк замков разделены « | »; имя сравнивается целиком, не как регулярное выражение.
if [ -e "$machine_lock" ]; then
    if awk -F' [|] ' -v s="window: $session" '$1 == s {f = 1} END {exit !f}' "$machine_lock"; then
        :
    elif [ "$kind" = heavy ] || [ "$timed" = 1 ]; then
        skip "NO WINDOW"
    elif awk -F' [|] ' '$1 ~ /^window: / && $2 == "quiet" {f = 1} END {exit !f}' "$machine_lock"; then
        skip "QUIET WINDOW"
    elif [ "$kind" = medium ] &&
        awk -F' [|] ' '$1 ~ /^window: / && $2 == "stand" {f = 1} END {exit !f}' "$machine_lock"; then
        skip "STAND WINDOW"
    fi
elif [ -e "$stand_lock" ] &&
    awk -F' [|] ' -v s="$session" '$3 == "measure" && $1 != s {f = 1} END {exit !f}' "$stand_lock"; then
    skip "STAND MEASURE (stand.lock)"
fi

set +f
"$@"
