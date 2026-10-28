#!/usr/bin/env bash
# Гейт нагрузки на общей машине (skill `coordinator`, project-rules §8).
#
#   bash scripts/machine_gate.sh [--timed] heavy|medium|light <session> <команда...>
#   bash scripts/machine_gate.sh classify <строка команды>
#   bash scripts/machine_gate.sh grant <coordinator> <session> quiet|heavy|stand <minutes> <что...>
#   bash scripts/machine_gate.sh close <coordinator> <session>
#   bash scripts/machine_gate.sh status
#   bash scripts/machine_gate.sh request <session> quiet|heavy|stand <minutes> <what...>
#   bash scripts/machine_gate.sh release <session>
#   bash scripts/machine_gate.sh wait <session> [--timeout <minutes>]
#   bash scripts/machine_gate.sh extend <session> <minutes>
#   bash scripts/machine_gate.sh merge-begin <session> <branch>
#   bash scripts/machine_gate.sh merge-end <session>
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
# grant / close — открывают и закрывают окно в machine.lock (проверка формата, запись через tmp + mv);
# status — печатает замок, свободную память и загрузку процессора
# (plans/2026-10-13_tooling-machine-gate-hook/task-1.2.md). Битый machine.lock — код 2 во всех режимах:
# команда не запускается (битый замок не превращается в тихий пропуск 75).
#
# Код выхода: код команды; 75 — пропущено гейтом (не путать с красным прогоном). Подкоманды окон и merge:
# 0 — выполнено, 2 — отказ или битый замок (в том числе нет machine.lock: нет координатора, окно не нужно),
# 124 — `wait --timeout` вышел по таймауту (в stdout `TIMEOUT`).
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

# --- machine.lock: чтение, проверка формата, grant / close / status (task-1.2.md) -----------------------------------

# Строки замка без завершающего \r (последняя строка без \n — тоже строка) -> LOCK_LINES. Читает bash, а не awk:
# gawk на Windows снимает \r сам, `read` — нет, поэтому \r снимается здесь явно.
read_lock() {
    LOCK_LINES=()
    [ -f "$1" ] && [ -r "$1" ] || return 1
    local line
    while IFS= read -r line || [ -n "$line" ]; do
        line=${line%$'\r'}
        LOCK_LINES+=("$line")
    done 2>/dev/null <"$1"
    return 0
}

# Имя = [A-Za-z0-9._-]+ (перечислено явно: диапазоны букв зависят от локали).
is_name() {
    [ -n "$1" ] && [[ $1 != *[!abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-]* ]]
}

is_window_kind() {
    case $1 in quiet | heavy | stand) return 0 ;; esac
    return 1
}

# Ветка = [A-Za-z0-9._/-]+ (перечислено явно, как is_name).
is_branch() {
    [ -n "$1" ] && [[ $1 != *[!abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-]* ]]
}

# Строка -> FIELDS (разделитель « | », без перекрытий слева направо).
split_fields() {
    local rest=$1
    FIELDS=()
    while [[ $rest == *' | '* ]]; do
        FIELDS+=("${rest%%' | '*}")
        rest=${rest#*' | '}
    done
    FIELDS+=("$rest")
}

# Грамматика замка (task-1.2.md). Читает файл в LOCK_LINES; 0 — годен (LOCK_COORD = имя координатора),
# 2 — текст отказа в LOCK_ERR (одна строка, без перевода строки в конце).
validate_lock() {
    LOCK_ERR='' LOCK_COORD=''
    if ! read_lock "$1"; then
        LOCK_ERR='machine_gate: cannot read machine.lock'
        return 2
    fi
    local line n=0 coords=0 windows=0 merges=0 ok name
    for line in "${LOCK_LINES[@]}"; do
        n=$((n + 1))
        [ -z "$line" ] && continue
        ok=0
        split_fields "$line"
        case $line in
            'coordinator: '*)
                name=${FIELDS[0]#coordinator: }
                if [ "${#FIELDS[@]}" = 2 ] && is_name "$name" && [[ ${FIELDS[1]} == 'since '* ]] && [ "$coords" = 0 ]; then
                    ok=1
                    coords=1
                    LOCK_COORD=$name
                fi
                ;;
            'window: '*)
                name=${FIELDS[0]#window: }
                if [ "${#FIELDS[@]}" = 4 ] && is_name "$name" && is_window_kind "${FIELDS[1]}" &&
                    [[ ${FIELDS[3]} == 'until ~'* ]] && [ "$windows" = 0 ]; then
                    ok=1
                    windows=1
                fi
                ;;
            'waiting: '*)
                name=${FIELDS[0]#waiting: }
                if [ "${#FIELDS[@]}" = 4 ] && is_name "$name" && is_window_kind "${FIELDS[1]}"; then ok=1; fi
                ;;
            'merging: '*)
                name=${FIELDS[0]#merging: }
                if [ "${#FIELDS[@]}" = 3 ] && is_name "$name" && is_branch "${FIELDS[1]}" &&
                    [[ ${FIELDS[2]} == 'since '* ]] && [ "$merges" = 0 ]; then
                    ok=1
                    merges=1
                fi
                ;;
            'stand: '?*) ok=1 ;;
        esac
        if [ "$ok" = 0 ]; then
            LOCK_ERR="machine_gate: malformed machine.lock:$n: $line"
            return 2
        fi
    done
    if [ "$coords" = 0 ]; then
        LOCK_ERR='machine_gate: malformed machine.lock: no coordinator line'
        return 2
    fi
    return 0
}

refuse() {
    echo "machine_gate: $1" >&2
    exit 2
}

# Проверки 3..9 списка отказов grant/close (task-1.2.md); перечитывает замок. 0 — можно писать, 2 — отказ напечатан.
# Читает переменные cmd_edit: op, coordinator, session, wkind, minutes, what.
edit_checks() {
    local line f has_window=0 has_own=0 minutes_ok=0
    if ! validate_lock "$machine_lock"; then
        printf '%s\n' "$LOCK_ERR" >&2
        return 2
    fi
    if [ "$LOCK_COORD" != "$coordinator" ]; then
        echo "machine_gate: not the coordinator" >&2
        return 2
    fi
    if ! is_name "$session"; then
        echo "machine_gate: bad session name" >&2
        return 2
    fi
    if [ "$op" = grant ]; then
        if ! is_window_kind "$wkind"; then
            echo "machine_gate: window kind must be quiet, heavy or stand" >&2
            return 2
        fi
        case $minutes in
            '' | *[!0-9]* | 0*) ;;
            *) [ "${#minutes}" -le 3 ] && [ "$minutes" -le 600 ] && minutes_ok=1 ;;
        esac
        if [ "$minutes_ok" != 1 ]; then
            echo "machine_gate: minutes must be 1..600" >&2
            return 2
        fi
        case $what in
            *'|'* | *$'\r'* | *$'\n'*)
                echo "machine_gate: what must not contain | or line breaks" >&2
                return 2
                ;;
        esac
    fi
    for line in "${LOCK_LINES[@]}"; do
        f=${line%%' | '*}
        case $f in 'window: '*) has_window=1 ;; esac
        [ "$f" = "window: $session" ] && has_own=1
    done
    if [ "$op" = grant ] && [ "$has_window" = 1 ]; then
        echo "machine_gate: a window is already open" >&2
        return 2
    fi
    if [ "$op" = close ] && [ "$has_own" = 0 ]; then
        echo "machine_gate: no window of this session" >&2
        return 2
    fi
    return 0
}

# Новое содержимое замка на stdout: LF, у каждой строки снят \r, \n после последней.
edit_write() {
    local line f
    for line in "${LOCK_LINES[@]}"; do
        f=${line%%' | '*}
        if [ "$op" = grant ]; then
            [ "$f" = "waiting: $session" ] && continue
        else
            [ "$f" = "window: $session" ] && continue
        fi
        printf '%s\n' "$line" || return 1
        if [ "$op" = grant ]; then
            case $line in
                'coordinator: '*)
                    printf 'window: %s | %s | %s | until ~%s\n' "$session" "$wkind" "$what" "$until_hhmm" || return 1
                    ;;
            esac
        fi
    done
    return 0
}

# grant | close: $1 = grant|close, дальше аргументы подкоманды.
cmd_edit() {
    local op=$1 coordinator session wkind='' minutes='' what='' until_hhmm='' tmp
    if [ "$op" = grant ]; then
        if [ $# -lt 6 ]; then
            echo "usage: machine_gate.sh grant <coordinator> <session> quiet|heavy|stand <minutes> <what...>" >&2
            exit 2
        fi
        coordinator=$2 session=$3 wkind=$4 minutes=$5
        shift 5
        what=$*
    else
        if [ $# -ne 3 ]; then
            echo "usage: machine_gate.sh close <coordinator> <session>" >&2
            exit 2
        fi
        coordinator=$2 session=$3
    fi
    [ -e "$machine_lock" ] || refuse "no machine.lock"
    edit_checks || exit 2
    if [ "$op" = grant ]; then until_hhmm=$(date -d "+$minutes minutes" +%H:%M); fi

    # Взаимное исключение: machine.lock.tmp создаётся под set -C (O_EXCL); чужой tmp не трогаем.
    tmp=$lock_dir/machine.lock.tmp
    ( set -C; : >"$tmp" ) >/dev/null 2>&1 ||
        refuse "machine.lock.tmp exists (another grant/close running, or a leftover)"
    # Пока tmp не был захвачен, другой grant/close мог успеть заменить замок: проверить заново под защитой tmp.
    if ! edit_checks; then
        rm -f "$tmp"
        exit 2
    fi
    if ! edit_write >"$tmp" 2>/dev/null || ! mv -f "$tmp" "$machine_lock" </dev/null >/dev/null 2>&1; then
        rm -f "$tmp"
        refuse "cannot replace machine.lock (busy), retry"
    fi
    exit 0
}

# --- самообслуживание окон и merge-слота (plans/2026-10-27_tooling-gate-self-service/plan.md, Task 1.1) --------------
# request / release / wait / extend / merge-begin / merge-end пишут замок одним путём: lock_edit.
# plan_<команда> — функция от LOCK_LINES, NOW и аргументов: готовит NEW_LINES, PLAN_WRITE (0/1), PLAN_OUT (stdout
# после успешного mv) и PLAN_ERR (текст отказа). Её зовут дважды: по непроверенному чтению (быстрый путь без записи)
# и под защитой machine.lock.tmp по свежему замку.

OWN_TMP=0 # 1 — machine.lock.tmp создан этим процессом (флаг владения для trap)
NOW=0 NOW_HHMM='' NOW_MIN=0
PLAN_WRITE=0 PLAN_OUT='' PLAN_ERR='' PLAN_STATE=pending PROMOTED='' PROMOTED_UNTIL=''
NEW_LINES=()
SESSION='' KIND='' MINUTES='' WHAT='' BRANCH='' WAIT_FIRST=1
S_HAS_WINDOW=0 S_WOWNER='' S_WKIND='' S_WUNTIL='' S_MOWNER='' S_OWN_WAIT=0 S_POS=0 S_NWAIT=0
U_MIN=0 REM=0

die_usage() {
    echo "usage: machine_gate.sh $1" >&2
    exit 2
}

# «Сейчас» читается один раз до tmp. MACHINE_GATE_NOW_EPOCH (только тесты) — целые секунды, нечисловое игнорируется.
read_now() {
    local v=${MACHINE_GATE_NOW_EPOCH:-}
    case $v in
        '' | *[!0-9]*) NOW=$(date +%s) ;;
        *) NOW=$((10#$v)) ;;
    esac
    NOW_HHMM=$(date -d "@$NOW" +%H:%M)
    NOW_MIN=$((10#${NOW_HHMM%:*} * 60 + 10#${NOW_HHMM#*:}))
}

# Замок есть и годен -> LOCK_LINES. $1 — число попыток, $2 — пауза, $3 — 1: повторять при любой ошибке, 0: только когда
# замок нечитаем (миг подмены mv на Windows). Не вышло — текст отказа в stderr, код 2.
load_lock() {
    local i
    [ -e "$machine_lock" ] || [ "$3" = 1 ] || refuse "no machine.lock"
    for ((i = 1; i <= $1; i++)); do
        validate_lock "$machine_lock" && return 0
        if [ "$3" = 0 ] && [ "$LOCK_ERR" != 'machine_gate: cannot read machine.lock' ]; then break; fi
        [ "$i" -lt "$1" ] && sleep "$2"
    done
    printf '%s\n' "$LOCK_ERR" >&2
    exit 2
}

check_session() { is_name "$SESSION" || refuse "bad session name"; }
check_kind() { is_window_kind "$KIND" || refuse "window kind must be quiet, heavy or stand"; }

# $1 — минуты: 1..600 без ведущих нулей.
is_minutes() {
    case $1 in '' | *[!0-9]* | 0*) return 1 ;; esac
    [ "${#1}" -le 3 ] && [ "$1" -le 600 ]
}

check_minutes() { is_minutes "$MINUTES" || refuse "minutes must be 1..600"; }

check_what() {
    case $WHAT in
        *'|'* | *$'\r'* | *$'\n'*) refuse "what must not contain | or line breaks" ;;
    esac
}

# --- разбор замка (по NEW_LINES) ---

# NEW_LINES -> S_*: окно (владелец, вид, until), слот merging, заявки (сколько и позиция первой заявки SESSION).
scan() {
    local line
    S_HAS_WINDOW=0 S_WOWNER='' S_WKIND='' S_WUNTIL='' S_MOWNER='' S_OWN_WAIT=0 S_POS=0 S_NWAIT=0
    for line in "${NEW_LINES[@]}"; do
        case $line in
            'window: '*)
                split_fields "$line"
                S_HAS_WINDOW=1 S_WOWNER=${FIELDS[0]#window: } S_WKIND=${FIELDS[1]} S_WUNTIL=${FIELDS[3]#until }
                ;;
            'merging: '*)
                split_fields "$line"
                S_MOWNER=${FIELDS[0]#merging: }
                ;;
            'waiting: '*)
                split_fields "$line"
                S_NWAIT=$((S_NWAIT + 1))
                if [ "$S_OWN_WAIT" = 0 ] && [ "${FIELDS[0]#waiting: }" = "$SESSION" ]; then
                    S_OWN_WAIT=1 S_POS=$S_NWAIT
                fi
                ;;
        esac
    done
}

# "~HH:MM" (HH <= 23, MM <= 59) -> U_MIN (минута суток). Иное — код 1.
parse_until() {
    local re='^~([0-9][0-9]):([0-9][0-9])$'
    [[ $1 =~ $re ]] || return 1
    [ "$((10#${BASH_REMATCH[1]}))" -le 23 ] && [ "$((10#${BASH_REMATCH[2]}))" -le 59 ] || return 1
    U_MIN=$((10#${BASH_REMATCH[1]} * 60 + 10#${BASH_REMATCH[2]}))
}

# Остаток окна U_MIN относительно NOW_MIN -> REM, приведён к [-13 ч, +11 ч): свежее окно (<= 600 мин) всегда в плюсе.
remaining() {
    REM=$((((U_MIN - NOW_MIN + 780) % 1440 + 1440) % 1440 - 780))
}

# Окно из S_* просрочено (остаток <= -1) -> код 0 и REM; until не вида ~HH:MM — не просрочено.
window_overdue() {
    [ "$S_HAS_WINDOW" = 1 ] && parse_until "$S_WUNTIL" || return 1
    remaining
    [ "$REM" -le -1 ]
}

# --- правки NEW_LINES ---

plan_init() {
    PLAN_WRITE=0 PLAN_OUT='' PLAN_ERR=''
    NEW_LINES=("${LOCK_LINES[@]}")
}

# $1 — новая строка, $2 — префикс строки, после которой её вставить (первая такая).
insert_after() {
    local line out=() placed=0
    for line in "${NEW_LINES[@]}"; do
        out+=("$line")
        if [ "$placed" = 0 ]; then
            case $line in
                "$2"*)
                    out+=("$1")
                    placed=1
                    ;;
            esac
        fi
    done
    NEW_LINES=("${out[@]}")
}

# Убрать строки, у которых первое поле (до « | ») равно $1.
remove_field() {
    local line out=() f
    for line in "${NEW_LINES[@]}"; do
        f=${line%%' | '*}
        [ "$f" = "$1" ] || out+=("$line")
    done
    NEW_LINES=("${out[@]}")
}

# Автовыдача: окна нет и есть waiting: -> ПЕРВАЯ waiting становится окном на N минут (N из «~N min», N <= 600, иначе 60).
# Код 0 — выдано (PROMOTED, PROMOTED_UNTIL = "~HH:MM"), 1 — нечего выдавать.
promote() {
    local line first='' out=() n=60 until_hhmm window skipped=0 placed=0 re='^~([1-9][0-9]{0,2}) min'
    scan
    [ "$S_HAS_WINDOW" = 0 ] && [ "$S_NWAIT" -gt 0 ] || return 1
    for line in "${NEW_LINES[@]}"; do
        case $line in 'waiting: '*) first=$line; break ;; esac
    done
    split_fields "$first"
    if [[ ${FIELDS[3]} =~ $re ]] && [ "${BASH_REMATCH[1]}" -le 600 ]; then n=${BASH_REMATCH[1]}; fi
    PROMOTED=${FIELDS[0]#waiting: }
    until_hhmm=$(date -d "@$((NOW + n * 60))" +%H:%M)
    PROMOTED_UNTIL="~$until_hhmm"
    window="window: $PROMOTED | ${FIELDS[1]} | ${FIELDS[2]} | until $PROMOTED_UNTIL"
    for line in "${NEW_LINES[@]}"; do
        if [ "$skipped" = 0 ] && [ "$line" = "$first" ]; then
            skipped=1
            continue
        fi
        out+=("$line")
        if [ "$placed" = 0 ]; then
            case $line in 'coordinator: '*) out+=("$window"); placed=1 ;; esac
        fi
    done
    NEW_LINES=("${out[@]}")
    scan
    return 0
}

# --- планы команд ---

plan_request() {
    plan_init
    scan
    if [ "$S_HAS_WINDOW" = 1 ] && [ "$S_WOWNER" = "$SESSION" ]; then
        PLAN_OUT="GRANTED until $S_WUNTIL"$'\n'
        return 0
    fi
    if [ "$S_OWN_WAIT" = 0 ]; then
        NEW_LINES+=("waiting: $SESSION | $KIND | $WHAT | ~$MINUTES min")
        PLAN_WRITE=1
    fi
    if promote; then PLAN_WRITE=1; fi
    scan
    if [ "$S_HAS_WINDOW" = 1 ] && [ "$S_WOWNER" = "$SESSION" ]; then
        PLAN_OUT="GRANTED until $S_WUNTIL"$'\n'
    else
        PLAN_OUT="QUEUED position $S_POS"$'\n'
    fi
}

plan_release() {
    plan_init
    scan
    if [ "$S_HAS_WINDOW" = 1 ] && [ "$S_WOWNER" = "$SESSION" ]; then
        remove_field "window: $SESSION"
        PLAN_WRITE=1
        PLAN_OUT="RELEASED"$'\n'
        if promote; then PLAN_OUT+="NEXT $PROMOTED until $PROMOTED_UNTIL"$'\n'; fi
    elif [ "$S_OWN_WAIT" = 1 ]; then
        remove_field "waiting: $SESSION"
        PLAN_WRITE=1
        PLAN_OUT="CANCELLED"$'\n'
    else
        PLAN_ERR='no window or request of this session'
    fi
}

plan_extend() {
    local base total new_until line out=() f
    plan_init
    scan
    if [ "$S_HAS_WINDOW" = 0 ] || [ "$S_WOWNER" != "$SESSION" ]; then
        PLAN_ERR='no window of this session'
        return 0
    fi
    if ! parse_until "$S_WUNTIL"; then
        PLAN_ERR='window has no valid until'
        return 0
    fi
    remaining
    base=$REM
    [ "$base" -lt 0 ] && base=0
    total=$((base + MINUTES))
    if [ "$total" -gt 600 ]; then
        PLAN_ERR='extension too long (more than 600 minutes left)'
        return 0
    fi
    new_until=$(date -d "@$((NOW + total * 60))" +%H:%M)
    for line in "${NEW_LINES[@]}"; do
        f=${line%%' | '*}
        if [ "$f" = "window: $SESSION" ]; then
            split_fields "$line"
            line="${FIELDS[0]} | ${FIELDS[1]} | ${FIELDS[2]} | until ~$new_until"
        fi
        out+=("$line")
    done
    NEW_LINES=("${out[@]}")
    PLAN_WRITE=1
    PLAN_OUT="EXTENDED until ~$new_until"$'\n'
}

plan_merge_begin() {
    local anchor='coordinator: '
    plan_init
    scan
    if [ -n "$S_MOWNER" ]; then
        PLAN_ERR="merge slot is taken by $S_MOWNER"
        return 0
    fi
    if [ "$S_HAS_WINDOW" = 1 ] && [ "$S_WKIND" = quiet ]; then
        PLAN_ERR='a quiet window is open'
        return 0
    fi
    [ "$S_HAS_WINDOW" = 1 ] && anchor='window: '
    insert_after "merging: $SESSION | $BRANCH | since $NOW_HHMM" "$anchor"
    PLAN_WRITE=1
    PLAN_OUT="MERGE SLOT TAKEN"$'\n'
}

plan_merge_end() {
    plan_init
    scan
    if [ -z "$S_MOWNER" ]; then
        PLAN_ERR='no merge slot'
    elif [ "$S_MOWNER" = "$SESSION" ] || [ "$SESSION" = "$LOCK_COORD" ]; then
        remove_field "merging: $S_MOWNER"
        PLAN_WRITE=1
        PLAN_OUT="MERGE SLOT FREE"$'\n'
    else
        PLAN_ERR="merge slot belongs to $S_MOWNER"
    fi
}

# Один опрос wait: PLAN_STATE = granted (окно стало или уже было своим) | pending.
plan_wait() {
    plan_init
    PLAN_STATE=pending
    scan
    if [ "$S_HAS_WINDOW" = 1 ] && [ "$S_WOWNER" = "$SESSION" ]; then
        PLAN_STATE=granted
        return 0
    fi
    if [ "$S_OWN_WAIT" = 0 ]; then
        if [ "$WAIT_FIRST" = 1 ]; then PLAN_ERR='no request of this session'; else PLAN_ERR='request of this session disappeared'; fi
        return 0
    fi
    if promote; then
        PLAN_WRITE=1
        if [ "$PROMOTED" = "$SESSION" ]; then PLAN_STATE=granted; fi
    fi
}

# --- запись замка ---

# Снять свой tmp (только при флаге владения) и trap'ы. Чужой tmp не трогается никогда.
release_tmp() {
    if [ "$OWN_TMP" = 1 ]; then
        OWN_TMP=0
        rm -f "$lock_dir/machine.lock.tmp"
    fi
    trap - EXIT INT TERM HUP
}

# Захват machine.lock.tmp под set -C (O_EXCL). Занят — повтор раз в 0.1 с до MACHINE_GATE_TMP_WAIT_SEC (умолч. 10);
# tmp старше 60 с (по РЕАЛЬНЫМ часам) считается остатком убитого держателя: удаляется, захват повторяется.
acquire_tmp() {
    local tmp=$lock_dir/machine.lock.tmp wait_sec=${MACHINE_GATE_TMP_WAIT_SEC:-} i=0 limit mtime real reclaims=0
    case $wait_sec in '' | *[!0-9]*) wait_sec=10 ;; esac
    limit=$((10#$wait_sec * 10))
    while :; do
        if ( set -C; : >"$tmp" ) >/dev/null 2>&1; then return 0; fi
        mtime=$(stat -c %Y "$tmp" 2>/dev/null) || mtime=''
        real=$(date +%s)
        case $mtime in
            '' | *[!0-9]*) ;;
            *)
                if [ "$((real - mtime))" -gt 60 ] && [ "$reclaims" -lt 5 ]; then
                    reclaims=$((reclaims + 1))
                    rm -f "$tmp"
                    continue
                fi
                ;;
        esac
        [ "$i" -ge "$limit" ] && return 1
        i=$((i + 1))
        sleep 0.1
    done
}

# NEW_LINES на stdout: LF, у каждой строки снят \r (read_lock), \n после последней.
write_new_lines() {
    local line
    for line in "${NEW_LINES[@]}"; do
        printf '%s\n' "$line" || return 1
    done
    return 0
}

# Запись под tmp: перечитать и проверить замок, решить заново ($1 — plan-функция), записать и подменить одним mv -f
# (до 5 попыток по 0.2 с). После возврата PLAN_OUT/PLAN_STATE — по свежему замку; stdout не печатается.
lock_commit() {
    local plan=$1 tmp=$lock_dir/machine.lock.tmp attempt
    acquire_tmp || refuse "machine.lock.tmp exists (another grant/close running, or a leftover)"
    OWN_TMP=1 # trap — только ПОСЛЕ захвата: проигравший не должен снять tmp победителя
    trap release_tmp EXIT
    trap 'release_tmp; exit 130' INT
    trap 'release_tmp; exit 143' TERM
    trap 'release_tmp; exit 129' HUP
    if ! validate_lock "$machine_lock"; then
        release_tmp
        printf '%s\n' "$LOCK_ERR" >&2
        exit 2
    fi
    "$plan"
    if [ -n "$PLAN_ERR" ]; then
        release_tmp
        refuse "$PLAN_ERR"
    fi
    if [ "$PLAN_WRITE" = 0 ]; then
        release_tmp
        return 0
    fi
    if ! write_new_lines >"$tmp" 2>/dev/null; then
        release_tmp
        refuse "cannot replace machine.lock (busy), retry"
    fi
    for ((attempt = 1; attempt <= 5; attempt++)); do
        if mv -f "$tmp" "$machine_lock" </dev/null >/dev/null 2>&1; then
            OWN_TMP=0 # tmp переименован в замок: больше не наш
            trap - EXIT INT TERM HUP
            return 0
        fi
        [ "$attempt" -lt 5 ] && sleep 0.2
    done
    release_tmp
    refuse "cannot replace machine.lock (busy), retry"
}

# План по непроверенному чтению; запись нужна — lock_commit. stdout печатается только после успешного mv.
lock_edit() {
    local plan=$1
    "$plan"
    [ -z "$PLAN_ERR" ] || refuse "$PLAN_ERR"
    if [ "$PLAN_WRITE" = 1 ]; then lock_commit "$plan"; fi
    printf '%s' "$PLAN_OUT"
}

# --- подкоманды ---

cmd_request() {
    [ $# -ge 5 ] || die_usage 'request <session> quiet|heavy|stand <minutes> <what...>'
    SESSION=$2 KIND=$3 MINUTES=$4
    shift 4
    WHAT=$*
    load_lock 5 0.2 0
    check_session
    check_kind
    check_minutes
    check_what
    read_now
    lock_edit plan_request
    exit 0
}

cmd_release() {
    [ $# -eq 2 ] || die_usage 'release <session>'
    SESSION=$2
    load_lock 5 0.2 0
    check_session
    read_now
    lock_edit plan_release
    exit 0
}

cmd_extend() {
    [ $# -eq 3 ] || die_usage 'extend <session> <minutes>'
    SESSION=$2 MINUTES=$3
    load_lock 5 0.2 0
    check_session
    check_minutes
    read_now
    lock_edit plan_extend
    exit 0
}

cmd_merge_begin() {
    [ $# -eq 3 ] || die_usage 'merge-begin <session> <branch>'
    SESSION=$2 BRANCH=$3
    load_lock 5 0.2 0
    check_session
    is_branch "$BRANCH" || refuse "bad branch name"
    read_now
    lock_edit plan_merge_begin
    exit 0
}

cmd_merge_end() {
    [ $# -eq 2 ] || die_usage 'merge-end <session>'
    SESSION=$2
    load_lock 5 0.2 0
    check_session
    read_now
    lock_edit plan_merge_end
    exit 0
}

# wait <session> [--timeout <minutes>]: опрос каждые MACHINE_GATE_POLL_SEC (умолч. 15) секунд; по умолчанию 120 минут.
cmd_wait() {
    local timeout_min=120 poll=${MACHINE_GATE_POLL_SEC:-} deadline last_overdue='' re='^(0|[1-9][0-9]{0,3})$'
    case $# in
        2) ;;
        4)
            [ "$3" = --timeout ] && [[ $4 =~ $re ]] || die_usage 'wait <session> [--timeout <minutes>]'
            timeout_min=$4
            ;;
        *) die_usage 'wait <session> [--timeout <minutes>]' ;;
    esac
    SESSION=$2
    [[ $poll =~ ^[1-9][0-9]*$ ]] || poll=15
    load_lock 5 0.2 0
    check_session
    deadline=$(($(date +%s) + 10#$timeout_min * 60)) # дедлайн по реальным часам: NOW_EPOCH его не двигает
    while :; do
        if [ "$WAIT_FIRST" = 0 ]; then load_lock 3 0.5 1; fi
        read_now
        plan_wait
        [ -z "$PLAN_ERR" ] || refuse "$PLAN_ERR"
        if [ "$PLAN_WRITE" = 1 ]; then lock_commit plan_wait; fi
        WAIT_FIRST=0
        if [ "$PLAN_STATE" = granted ]; then
            printf 'GRANTED until %s\n' "$S_WUNTIL"
            exit 0
        fi
        if window_overdue; then
            if [ "$last_overdue" != "$REM" ]; then
                last_overdue=$REM
                printf 'OVERDUE %s +%s min\n' "$S_WOWNER" "$((-REM))"
            fi
        else
            last_overdue=''
        fi
        if [ "$(date +%s)" -ge "$deadline" ]; then
            echo TIMEOUT
            exit 124
        fi
        sleep "$poll"
    done
}

# status: замок + свободная память + загрузка процессора. Одна команда powershell; запрос LoadPercentage сам
# меряет ~1 с, пять подряд — выборка на 5 с без Start-Sleep. Пустые ($null) замеры пропускаются.
read -r -d '' PS_STATUS <<'PS'
$ErrorActionPreference = 'Stop'; try { 'ram_free_mb: ' + [int][math]::Floor((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024) } catch { 'ram_free_mb: n/a' }; $s = @(); for ($i = 0; $i -lt 5; $i++) { try { $v = @((Get-CimInstance Win32_Processor).LoadPercentage | Where-Object { $_ -ne $null }); if ($v.Count -gt 0) { $s += ($v | Measure-Object -Average).Average } } catch { } }; if ($s.Count -gt 0) { 'cpu_load_pct: ' + [int][math]::Round(($s | Measure-Object -Average).Average) } else { 'cpu_load_pct: n/a' }
PS

cmd_status() {
    local line out ram='n/a' cpu='n/a' v rc=0
    if [ -e "$machine_lock" ]; then
        validate_lock "$machine_lock" || rc=2
        for line in "${LOCK_LINES[@]}"; do printf '%s\n' "$line"; done
        if [ "$rc" = 0 ]; then
            # Просроченное окно при ожидающих заявках: OVERDUE <держатель> +<N> min (окно не отбирается).
            NEW_LINES=("${LOCK_LINES[@]}")
            scan
            if [ "$S_HAS_WINDOW" = 1 ] && [ "$S_NWAIT" -gt 0 ]; then
                read_now
                if window_overdue; then printf 'OVERDUE %s +%s min\n' "$S_WOWNER" "$((-REM))"; fi
            fi
        fi
    else
        echo "machine.lock: none"
    fi
    out=$(timeout 20 powershell -NoProfile -Command "$PS_STATUS" 2>/dev/null </dev/null | tr -d '\r')
    while IFS= read -r line; do
        v=${line#*: }
        case $v in '' | *[!0-9]*) continue ;; esac
        case $line in
            'ram_free_mb: '*) ram=$v ;;
            'cpu_load_pct: '*) cpu=$v ;;
        esac
    done <<<"$out"
    echo "ram_free_mb: $ram"
    echo "cpu_load_pct: $cpu"
    if [ "$rc" != 0 ]; then printf '%s\n' "$LOCK_ERR" >&2; fi
    exit "$rc"
}

set -f # токены команды режутся по пробелам без раскрытия шаблонов
if [ "${1:-}" = classify ]; then
    shift
    classify_cmd "$*"
    exit 0
fi

lock_dir=${MACHINE_LOCK_DIR:-/d/PROJECT_INNOTECH/Inspector_vision}
machine_lock=$lock_dir/machine.lock
stand_lock=$lock_dir/stand.lock

case ${1:-} in
    grant | close) cmd_edit "$@" ;;
    request) cmd_request "$@" ;;
    release) cmd_release "$@" ;;
    wait) cmd_wait "$@" ;;
    extend) cmd_extend "$@" ;;
    merge-begin) cmd_merge_begin "$@" ;;
    merge-end) cmd_merge_end "$@" ;;
    status) cmd_status ;;
esac

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

skip() {
    echo "$1 — skipped (machine_gate: $kind, $session)"
    exit 75
}

case $kind in heavy | medium | light) ;; *) echo "kind must be heavy, medium or light" >&2; exit 2 ;; esac

# Битый machine.lock — отказ до классификации и запуска (код 2, одна строка в stderr, без reclassified).
if [ -e "$machine_lock" ] && ! validate_lock "$machine_lock"; then
    printf '%s\n' "$LOCK_ERR" >&2
    exit 2
fi

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
