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

# Резка строки на сегменты вне кавычек и вне тел heredoc (classification.md §1). awk печатает каждый
# сегмент, обрезанный по краям, с завершающим \001: внутри кавычек сегмент может содержать перевод строки.
#   - разделители вне кавычек: && || ; | перевод строки; внутри '...' и "..." не режут, в "..." \" и \\ — пары;
#   - heredoc: << и <<- со словом WORD, 'WORD' или "WORD" (<<< — не heredoc); строки тела до строки,
#     равной WORD (для <<- — после снятия ведущих табуляций), в сегменты не попадают.
read -r -d '' AWK_SPLIT <<'AWK'
function flush(   t) {
    t = seg
    gsub(/^[ \t\r]+/, "", t)
    gsub(/[ \t\r]+$/, "", t)
    if (t != "") printf "%s\001", t
    seg = ""
}
{
    sub(/\r$/, "")
    if (npend > 0) {
        line = $0
        if (pend_strip[1]) sub(/^\t+/, "", line)
        if (line == pend_word[1]) {
            for (k = 1; k < npend; k++) { pend_word[k] = pend_word[k + 1]; pend_strip[k] = pend_strip[k + 1] }
            npend--
        }
        next
    }
    n = length($0)
    i = 1
    while (i <= n) {
        c = substr($0, i, 1)
        d = substr($0, i + 1, 1)
        if (q == "'") {
            seg = seg c
            if (c == "'") q = ""
            i++
        } else if (q == "\"") {
            if (c == "\\" && (d == "\"" || d == "\\")) { seg = seg c d; i += 2; continue }
            seg = seg c
            if (c == "\"") q = ""
            i++
        } else if (c == "\\") {
            seg = seg c d
            i += 2
        } else if (c == "'" || c == "\"") {
            q = c
            seg = seg c
            i++
        } else if ((c == "&" && d == "&") || (c == "|" && d == "|")) {
            flush()
            i += 2
        } else if (c == ";" || c == "|") {
            flush()
            i++
        } else if (c == "<" && d == "<") {
            if (substr($0, i + 2, 1) == "<") { seg = seg "<<<"; i += 3; continue }
            j = i + 2
            strip = 0
            if (substr($0, j, 1) == "-") { strip = 1; j++ }
            while (j <= n && substr($0, j, 1) ~ /[ \t]/) j++
            w = ""
            qc = substr($0, j, 1)
            if (qc == "'" || qc == "\"") {
                j++
                while (j <= n && substr($0, j, 1) != qc) { w = w substr($0, j, 1); j++ }
            } else {
                while (j <= n && substr($0, j, 1) !~ /[ \t;|&<>()]/) { w = w substr($0, j, 1); j++ }
            }
            if (w != "") { npend++; pend_word[npend] = w; pend_strip[npend] = strip }
            seg = seg "<<"
            i += 2
        } else {
            seg = seg c
            i++
        }
    }
    if (q != "") seg = seg "\n"
    else flush()
}
END { flush() }
AWK

# Скрипт по basename -> CLS="kind<TAB>reason" или пусто.
script_class() {
    CLS=''
    case ${1##*/} in
        run_framework_tests.py) CLS=$'heavy\trun_framework_tests' ;;
        run_sim_all.ps1) CLS=$'heavy\trun_sim_all' ;;
        check_injections.py | mutation_gate.py | break_inject*) CLS=$'heavy\tinjection_matrix' ;;
        reindex_retry.py | qex_retry.py) CLS=$'heavy\tqex_index' ;;
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

# Аргументы pytest (classification.md §3) -> CLS.
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
        CLS=$'heavy\tpytest_xdist'
    elif [ "$has_target" = 0 ]; then
        CLS=$'heavy\tpytest_no_file_args'
    elif [ "$bad_dir" = 1 ]; then
        CLS=$'heavy\tpytest_dir_not_module_tests'
    elif [ "$mod_dirs" -ge 2 ]; then
        CLS=$'heavy\tpytest_multi_dir'
    elif [ "$mod_dirs" = 1 ]; then
        CLS=$'medium\tpytest_module_dir'
    else
        CLS=$'light\tpytest_files'
    fi
}

# Ведущие слова позиции команды (do then else time ! { и скобка) снимаются с сегмента: совет хука должен
# быть исполнимым командой гейта. Меняет $seg.
strip_lead() {
    local first paren=0
    while :; do
        seg=${seg#"${seg%%[![:space:]]*}"}
        first=${seg%%[[:space:]]*}
        case $first in
            do | then | else | time | '!' | '{') seg=${seg#"$first"} ;;
            '('*) seg=${seg#\(}; paren=1 ;;
            *) break ;;
        esac
    done
    if [ "$paren" = 1 ]; then seg=${seg%)}; fi
    seg=${seg%"${seg##*[![:space:]]}"}
}

# Один сегмент -> CLS ("kind<TAB>reason" или пусто: тестовой команды в позиции команды нет).
classify_segment() {
    local -a toks
    local i=0 n t base j tok
    CLS=''
    IFS=$' \t\n' read -d '' -ra toks <<<"$1"
    n=${#toks[@]}
    # Префиксы позиции команды: VAR=val, env, time, xargs, do/then/else/!/{/(, timeout, uv run.
    while [ "$i" -lt "$n" ]; do
        t=${toks[i]}
        if [[ $t =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
            i=$((i + 1))
        elif [ "$t" = env ] || [ "$t" = xargs ]; then
            i=$((i + 1))
            while [ "$i" -lt "$n" ] && [[ ${toks[i]} == -* ]]; do i=$((i + 1)); done
        elif [ "$t" = time ] || [ "$t" = do ] || [ "$t" = then ] || [ "$t" = else ] || [ "$t" = '!' ] ||
            [ "$t" = '{' ] || [ "$t" = '(' ]; then
            i=$((i + 1))
        elif [ "$t" = timeout ]; then
            i=$((i + 1))
            while [ "$i" -lt "$n" ] && [[ ${toks[i]} == -* ]]; do
                case ${toks[i]} in -k | -s) i=$((i + 1)) ;; esac
                i=$((i + 1))
            done
            i=$((i + 1))
        elif [ "$t" = uv ] && [ "$((i + 1))" -lt "$n" ] && [ "${toks[i + 1]}" = run ]; then
            i=$((i + 2))
            while [ "$i" -lt "$n" ] && [[ ${toks[i]} == -* ]]; do
                case ${toks[i]} in --python | --with | --project | --directory | -p) i=$((i + 1)) ;; esac
                i=$((i + 1))
            done
        else
            break
        fi
    done
    [ "$i" -lt "$n" ] || return 0
    t=${toks[i]//\\//}
    base=${t##*/}
    case $base in
        pytest | pytest.exe)
            pytest_class "${toks[@]:i+1}"
            ;;
        python | python3 | python.exe | python3.exe | py)
            for ((j = i + 1; j < n; j++)); do
                tok=${toks[j]//\\//}
                case $tok in
                    -m)
                        if [ "$((j + 1))" -lt "$n" ] && [ "${toks[j + 1]}" = pytest ]; then
                            pytest_class "${toks[@]:j+2}"
                        fi
                        return 0
                        ;;
                    -X | -W) j=$((j + 1)) ;;
                    -*) ;;
                    *)
                        script_class "$tok"
                        return 0
                        ;;
                esac
            done
            ;;
        powershell | powershell.exe | pwsh | pwsh.exe)
            for ((j = i + 1; j < n; j++)); do
                tok=${toks[j]//\\//}
                script_class "$tok"
                [ -n "$CLS" ] && return 0
            done
            ;;
        make | make.exe)
            for ((j = i + 1; j < n; j++)); do
                tok=${toks[j]}
                case $tok in
                    -C | -f) j=$((j + 1)) ;;
                    -*) ;;
                    [A-Za-z_]*=*) ;;
                    gate | test | test-fast | test-fw | test-ctl) CLS=$'heavy\tmake_suite'; return 0 ;;
                    *) return 0 ;;
                esac
            done
            ;;
    esac
    return 0
}

# Строка команды -> по ряду `<kind>\t<reason>\t<сегмент>` на каждый тестовый сегмент. Сегменты без слов-кандидатов
# отбрасываются до classify_segment (разбор токенов стоит миллисекунды на сегмент).
classify_cmd() {
    local segs seg
    segs=$(printf '%s\n' "$1" | awk "$AWK_SPLIT")
    while IFS= read -r -d $'\001' seg; do
        case $seg in *machine_gate.sh*) continue ;; esac
        case $seg in
            *pytest* | *run_framework_tests* | *run_sim_all* | *check_injections* | *mutation_gate* | *break_inject* | \
                *reindex* | *qex_retry* | *make*) ;;
            *) continue ;;
        esac
        strip_lead
        [ -n "$seg" ] || continue
        classify_segment "$seg"
        [ -n "$CLS" ] || continue
        printf '%s\t%s\n' "$CLS" "$seg"
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
