# Классификация и допуск гейта — план [2026-10-13_tooling-machine-gate-hook](../2026-10-13_tooling-machine-gate-hook.md)

> Вынесено из плана (бюджет размера 32 КБ). Контракт для тестов Task 1.1; все значения — литералы, не из кода.
> Три класса — по ответу владельца 2 (раздел «Ответы владельца» в плане): `light` < `medium` < `heavy`.

## 1. Сегменты и позиция команды

`classify` режет строку на сегменты по `&&`, `||`, `;`, `|`, переводу строки. Сегмент, в котором есть
`machine_gate.sh`, пропускается: его классифицирует сам гейт. Для каждого остального сегмента печатается
одна строка `<kind>\t<reason>\t<сегмент>`, где `kind` ∈ {`heavy`, `medium`, `light`}. Сегменты класса «нет»
не печатаются. Пустой вывод значит «тестовых команд нет». Код выхода всегда 0. Заявки агента
`classify` не получает и от неё не зависит.

Команда распознаётся **только в позиции команды**: в начале сегмента, после необязательных `VAR=val`,
`timeout N`, `uv run [--опции]`, `<python> [-опции] -m`. Слово в аргументах (`grep pytest`) не в счёт.
Скрипты C1–C8 узнаются по имени файла (basename) в позиции аргумента python/powershell.

## 2. Таблица классификации

| # | Сегмент | kind | reason |
|---|---|---|---|
| C1 | `python scripts/run_framework_tests.py` | heavy | `run_framework_tests` |
| C2 | `uv run --no-sync python scripts/run_framework_tests.py -k recipe` | heavy | `run_framework_tests` |
| C3 | `powershell -File scripts/run_sim_all.ps1` | heavy | `run_sim_all` |
| C4 | `python scripts/validate_commit/check_injections.py --plan x` | heavy | `injection_matrix` |
| C5 | `python scripts/mutation_gate.py` | heavy | `injection_matrix` |
| C6 | `python backend_ctl/probes/break_inject_g3_seams.py` | heavy | `injection_matrix` |
| C7 | `uv run --no-project python .claude/plugins/mcp-qex/reindex_retry.py` | heavy | `qex_index` |
| C8 | `python scripts/qex_retry.py` | heavy | `qex_index` |
| C9 | `pytest -q` | heavy | `pytest_no_file_args` |
| C10 | `python -m pytest multiprocess_framework/modules` | heavy | `pytest_dir_not_module_tests` |
| C11 | `pytest -n 4 a/tests/test_x.py` | heavy | `pytest_xdist` |
| C12 | `.venv/Scripts/python.exe -m pytest -q --tb=short Services/robot_comm/tests/test_kinematics_v2.py` | light | `pytest_files` |
| C13 | `PYTHONPATH=/d/wt pytest a/tests/test_x.py::test_one -q` | light | `pytest_files` |
| C14 | `cd /d/wt && pytest -q` | heavy (2-й сегмент) | `pytest_no_file_args` |
| C15 | `pytest Services/robot_comm/tests` | medium | `pytest_module_dir` |
| C16 | `python -m pytest -q --tb=short multiprocess_framework/modules/recipe/tests/` | medium | `pytest_module_dir` |
| C17 | `.venv/Scripts/python.exe -m pytest Services/robot_comm/tests Services/robot_comm/tests/test_kinematics_v2.py` | medium | `pytest_module_dir` |
| C18 | `PYTHONPATH=/d/wt pytest -q /d/wt/Services/robot_comm/tests -k kin` | medium | `pytest_module_dir` |
| C19 | `bash scripts/machine_gate.sh light s1 pytest Services/robot_comm/tests` | — (пустой вывод) | — |
| C20 | `pytest Services` | heavy | `pytest_no_file_args` |
| C21 | `pytest tests` | heavy | `pytest_no_file_args` |
| C22 | `pytest ./tests` | heavy | `pytest_dir_not_module_tests` |
| C23 | `pytest Services/` | heavy | `pytest_dir_not_module_tests` |
| C24 | `pytest Services/robot_comm/tests Services/line_sim/tests` | heavy | `pytest_multi_dir` |
| C25 | `pytest -n 4 Services/robot_comm/tests` | heavy | `pytest_xdist` |
| C26 | `pytest -q Services/robot_comm/tests multiprocess_framework/modules` | heavy | `pytest_dir_not_module_tests` |
| C27 | `python -m pytest --version` | heavy | `pytest_no_file_args` |
| C28 | `pytest Services\robot_comm\tests` | heavy | `pytest_dir_not_module_tests` |
| N1–N8 | `grep -n pytest pyproject.toml`; `git log --grep=pytest --oneline`; `cat pytest.ini`; `rg run_framework_tests scripts`; `git show HEAD:scripts/run_sim_all.ps1`; `echo pytest`; `pip show pytest`; `ls` | — (пустой вывод) | — |

Пояснения к строкам: C10 — reason сменился с `pytest_no_file_args` на `pytest_dir_not_module_tests` (каталог есть,
но не `*/tests`); C16 — хвостовой `/`; C17 — каталог модуля и `.py` рядом, класс задаёт каталог; C18 — абсолютный
путь, `kin` без `/` — не путь; C19 — обёрнутый сегмент, заявку `light` поднимает гейт (G9–G11); C20, C21 — токена с
`/` нет, значит путей нет; C22 — после отбрасывания `.` остаётся один сегмент; C26 — приоритет правила 3 над 4;
C28 — `\` делает токен путём, но сегменты каталога режутся только по `/`.

## 3. Правило pytest

Токены сегмента после `pytest` — через пробел; кавычки не разбираются (токен `"a/tests"` — не каталог модуля).
- **опция** — токен, начинающийся с `-`;
- **файл** — не опция, оканчивается на `.py` или содержит `.py::`;
- **каталог** — не опция и не файл, содержит `/` или `\`;
- **каталог модуля** — каталог, у которого после снятия одного хвостового `/`, разбивки по `/` и отбрасывания
  пустых сегментов и сегментов `.` осталось **не меньше двух** сегментов и последний равен `tests`.

Порядок — первое совпавшее правило:
1. есть `-n`, `-n=…`, `-nN`, `--numprocesses…` → `heavy` `pytest_xdist`;
2. нет ни файла, ни каталога → `heavy` `pytest_no_file_args`;
3. есть каталог, который не каталог модуля → `heavy` `pytest_dir_not_module_tests`;
4. токенов-каталогов модуля два и больше → `heavy` `pytest_multi_dir`;
5. ровно один каталог модуля (файлы рядом допустимы) → `medium` `pytest_module_dir`;
6. только файлы → `light` `pytest_files`.

## 4. Реклассификация в гейте — только вверх

Ранг: `light` = 1, `medium` = 2, `heavy` = 3. Гейт в режимах `heavy|medium|light` вызывает `classify "$*"`
и берёт строку с наибольшим рангом (при равенстве — первую). Ранг строки больше ранга заявки → дальше гейт
работает с классом строки и пишет в stderr ровно одну строку
`machine_gate: reclassified <заявка> -> <класс> (<reason>)`. Иначе (ранг не больше, вывод пуст) — класс заявки,
строки `reclassified` нет. Примеры: `light` + C15 → `medium`; `light` + C1 → `heavy`; `medium` + C1 → `heavy`;
`medium` + C12 → остаётся `medium`; `heavy` + что угодно → `heavy`.

## 5. Допуск по классам

Свое окно — строка, где поле 1 равно `window: <session>` целиком. Чужое — любая другая строка с полем 1
`window: …`; её вид — поле 2. Пропуск печатает в **stdout** `<ТЕКСТ> — skipped (machine_gate: <класс>, <session>)`
(класс — после реклассификации) и даёт код 75. Запуск — код команды.

| Состояние замка | `heavy` | `medium` | `light` |
|---|---|---|---|
| нет `machine.lock` | правило `stand.lock`: чужой `measure` → 75 `STAND MEASURE (stand.lock)`, иначе запуск | как `light`, слот не берётся | как сегодня |
| своё окно любого вида | запуск | запуск, слот не берётся | запуск |
| чужое `quiet` | 75 `NO WINDOW` | 75 `QUIET WINDOW` | 75 `QUIET WINDOW` |
| чужое `stand` | 75 `NO WINDOW` | 75 `STAND WINDOW` | запуск |
| чужое `heavy` | 75 `NO WINDOW` | слот взят → запуск; занят живым → 75 `MEDIUM SLOT BUSY` | запуск |
| окон нет | 75 `NO WINDOW` | слот взят → запуск; занят живым → запуск **без** слота | запуск |

Колонки `heavy` и `light` — поведение гейта на 2026-10-13, не меняются (стражи K1–K7).

## 6. Слот `medium`

- Каталог `$lock_dir/medium.slot`, внутри файл `pid`: `$$` гейта и перевод строки.
- Взять: `mkdir "$slot"` удался → записать `pid`, `trap release EXIT`.
- `mkdir` не удался: в `pid` число и `kill -0 <pid>` успешен → слот занят. Иначе (файла нет, не число, процесс
  мёртв) → `rm -f "$slot/pid"`, `rmdir "$slot"`, ещё одна попытка `mkdir`; снова неудача → занят.
- `release`: только если в `pid` записан свой `$$` — `rm -f "$slot/pid"`, `rmdir "$slot"`. Чужой слот не трогает;
  `rm -rf` не используется; `exit` в trap не вызывается (код команды сохраняется).
- Слот не берётся: своё окно; нет `machine.lock`; класс после реклассификации `light` или `heavy`.
- Держатель убит без trap (TaskStop, закрытый терминал) → PID мёртв → слот забирает следующий `medium`.
- PID — пространство Git Bash (MSYS). Windows-PID (`os.getpid()`, `Popen.pid`) `kill -0` в Git Bash не видит:
  проверено менеджером 2026-10-13 — `$$` живого bash → код 0; `Popen.pid` и `os.getpid()` → код 1.

## 7. Тесты гейта Task 1.1 (`test_machine_gate_hook.py`)

**Обозначения.** `L` = `tmp_path/"lock"`, env `MACHINE_LOCK_DIR=L.as_posix()`; `T` = `tmp_path.as_posix()`;
`PY` = `Path(sys.executable).as_posix()`; сессия гейта — `s1`. Каждый `L/machine.lock` начинается строкой
`coordinator: c1 | since x` (иначе валидатор Task 1.2 сделает эти тесты красными). Окна (вторая строка):
чужое — `window: other-s | <вид> | x | until ~23:59`; своё — `window: s1 | <вид> | x | until ~23:59`.
«Окон нет» — только строка `coordinator:`. `stand.lock` — `L/stand.lock`.

`MOD` = `PY -m pytest -q -p no:cacheprovider <T>/mod/tests`; файл `<T>/mod/tests/test_m.py`:
```python
import os, pathlib
def test_m():
    pid = pathlib.Path(os.environ["MACHINE_LOCK_DIR"], "medium.slot", "pid")
    seen = pid.read_text().strip() if pid.is_file() else "NONE"
    pathlib.Path(__file__).resolve().parents[1].joinpath("seen.txt").write_text(seen)
```
`MOD_FAIL` — тот же файл и последней строкой `    assert False` (pytest — код 1). `seen` = `<T>/mod/seen.txt`:
есть — команда запускалась; нет — не запускалась. `<T>/test_ok.py` = `def test_ok(): pass`.
`LIVE` — первая строка stdout `Popen([bash, "-c", "echo $$; sleep 60"])`, процесс жив до конца теста (в `finally` —
`kill()`); `DEAD` — stdout завершённого `bash -c "echo $$"`. «Слот LIVE» = до запуска созданы `L/medium.slot/`
и `L/medium.slot/pid` с текстом `<PID>\n`. `bash` — `_git_bash()`.

**`test_gate_medium`** (красный до кода). Пустая ячейка stderr → в stderr нет `reclassified`.

| ID | `machine.lock` (2-я строка) | слот до | заявка | команда | код | stdout содержит | stderr содержит | после |
|---|---|---|---|---|---|---|---|---|
| G1 | — | — | medium | MOD | 0 | — | | `seen` — число; `L/medium.slot` нет |
| G2 | чужое `quiet` | — | medium | MOD | 75 | `QUIET WINDOW`, `(machine_gate: medium, s1)` | | `seen` нет |
| G3 | чужое `stand` | — | medium | MOD | 75 | `STAND WINDOW`, `(machine_gate: medium, s1)` | | `seen` нет |
| G4 | чужое `heavy` | — | medium | MOD | 0 | — | | `seen` — число; `L/medium.slot` нет |
| G5 | чужое `heavy` | LIVE | medium | MOD | 75 | `MEDIUM SLOT BUSY`, `(machine_gate: medium, s1)` | | `seen` нет; `pid` = LIVE |
| G6 | чужое `heavy` | DEAD | medium | MOD | 0 | — | | `seen` — число ≠ DEAD; `L/medium.slot` нет |
| G7 | — | LIVE | medium | MOD | 0 | — | | `seen` = LIVE; `pid` = LIVE |
| G8 | своё `quiet` / `heavy` / `stand` (3 параметра) | LIVE | medium | MOD | 0 | — | | `seen` = LIVE; `pid` = LIVE |
| G9 | чужое `quiet` | — | light | MOD | 75 | `QUIET WINDOW`, `(machine_gate: medium, s1)` | `machine_gate: reclassified light -> medium (pytest_module_dir)` | `seen` нет |
| G10 | чужое `stand` | — | light | MOD | 75 | `STAND WINDOW` | как G9 | `seen` нет |
| G11 | чужое `heavy` | LIVE | light | MOD | 75 | `MEDIUM SLOT BUSY` | как G9 | `seen` нет |
| G12 | чужое `heavy` | LIVE | medium | `PY -m pytest -q -p no:cacheprovider <T>/test_ok.py` | 75 | `MEDIUM SLOT BUSY` | | — |
| G13 | нет `machine.lock`, нет `stand.lock` | — | medium | MOD | 0 | — | | `seen` = `NONE` |
| G14 | нет `machine.lock`; `stand.lock` = `other-s \| x \| measure` | — | medium | MOD | 75 | `STAND MEASURE (stand.lock)` | | `seen` нет |
| G15 | — | — | medium | MOD_FAIL | 1 | — | | `seen` — число; `L/medium.slot` нет |

«`seen` — число» = только цифры. G12 — заявка `medium` на файловую команду не понижается до `light`.
`\|` в ячейках — экранирование markdown; в файле `stand.lock` строка `other-s | x | measure`.

**`test_gate_reclassifies_to_heavy`** (красный до кода; замок без окна `s1`, `<T>/run_framework_tests.py` = `print("FAKE")`):

| ID | заявка | команда | код | stdout | stderr содержит |
|---|---|---|---|---|---|
| R1 | light | `python <T>/run_framework_tests.py` | 75 | `NO WINDOW`, нет `FAKE` | `machine_gate: reclassified light -> heavy (run_framework_tests)` |
| R2 | light | `python -m pytest --version` | 75 | `NO WINDOW` | `machine_gate: reclassified light -> heavy (pytest_no_file_args)` |
| R3 | medium | `python <T>/run_framework_tests.py` | 75 | `NO WINDOW`, нет `FAKE` | `machine_gate: reclassified medium -> heavy (run_framework_tests)` |

**`test_gate_call_form_compat`** — страж формы вызова полос (`heavy|light <session> <cmd>`); зелёный **до и после**
правки. `EXIT(n)` = `PY -c "import sys; sys.exit(n)"`. Во всех строках stderr не содержит `reclassified`.

| ID | заявка | `machine.lock` (2-я строка) | команда | код | stdout содержит |
|---|---|---|---|---|---|
| K1 | heavy | чужое `heavy` | `EXIT(3)` | 75 | `NO WINDOW`, `(machine_gate: heavy, s1)` |
| K2 | light | чужое `quiet` | `EXIT(3)` | 75 | `QUIET WINDOW`, `(machine_gate: light, s1)` |
| K3 | light | чужое `heavy` | `EXIT(4)` | 4 | — |
| K4 | light | чужое `stand` | `EXIT(4)` | 4 | — |
| K5 | light | нет `machine.lock`; `stand.lock` = `other-s \| x \| measure` | `EXIT(3)` | 75 | `STAND MEASURE (stand.lock)` |
| K6 | heavy | — (окон нет) | `PY -m pytest -q -p no:cacheprovider <T>/test_ok.py` | 75 | `NO WINDOW` |
| K7 | heavy | нет `machine.lock`, нет `stand.lock` | `EXIT(5)` | 5 | — |

## 8. Инъекции — предсказание до прогона (раздел «Пайплайн», п. 4 плана)

Лид записывает факт рядом с предсказанием; каждая инъекция — `light` прогон одного файла.
Имена — тесты `test_machine_gate_hook.py` (I, M) и `test_machine_gate_lock.py` (J); в скобках — id параметров.

| ID | Поломка | Предсказанные красные |
|---|---|---|
| I1 | хук: проверка замка инвертирована (`exit 0` при наличии замка) | `test_hook_blocks` (C10, C12, C15), `test_hook_blocks_unwrapped_segment_after_wrapped`, `test_hook_independent_of_cwd`, `test_hook_allows[no_lock]` |
| I2 | `classify`: удалено правило `-n` | `test_classify[C11]`, `test_classify[C25]` |
| I3 | `classify`: снята привязка к позиции команды | `test_classify_none` (N1, N2, N3, N6, N7 минимум), `test_hook_allows[non_test]` |
| I4 | хук: «обёрнуто», если `machine_gate.sh` есть где угодно в строке (не по сегментам) | `test_hook_blocks_unwrapped_segment_after_wrapped` |
| I5 | гейт: убрана вся реклассификация (класс = заявка) | `test_gate_reclassifies_to_heavy` (R1–R3), `test_gate_medium` (G9, G10, G11) |
| I6 | хук: убран `tr -d '\r'` | предсказание: **может остаться зелёным** (`[[:space:]]` съедает `\r`); если зелёное — записать как необнаруженную и объяснить, не выдумывать тест под неё |
| M1 | гейт: `medium` не проверяет чужое `quiet` | `test_gate_medium` (G2, G9) |
| M2 | гейт: чужое `stand` не блокирует `medium` | `test_gate_medium` (G3, G10) |
| M3 | гейт: слот не берётся и не проверяется (после проверок `quiet`/`stand` — сразу запуск) | `test_gate_medium` (G1, G4, G5, G6, G11, G12, G15) |
| M4 | гейт: слот не освобождается (нет `trap … EXIT`) | `test_gate_medium` (G1, G4, G6, G15) |
| M5 | гейт: `trap release EXIT` ставится до попытки `mkdir`, `release` удаляет слот без сверки PID | `test_gate_medium` (G5, G7) |
| M6 | гейт: класс = вывод `classify`, если он не пуст (понижение разрешено) | `test_gate_medium[G12]`, `test_gate_call_form_compat[K6]` |
| M7 | `classify`: правило 5 даёт `heavy` вместо `medium` (reason прежний) | `test_classify` (C15–C18), `test_hook_blocks[C15]`, `test_gate_medium` (G1–G7, G9–G11, G15) |
| M8 | `classify`: reason `pytest_module_dir` переименован в `pytest_module_tests` | `test_classify` (C15–C18), `test_hook_blocks[C15]`, `test_gate_medium` (G9, G10, G11) |
| M9 | `classify`: каталог модуля — любой каталог, оканчивающийся на `tests` (сегменты не считаются) | `test_classify[C22]` — ловит одна строка; слабое место, не добирать тестами без решения лида |
| M10 | гейт: занятый живой слот даёт 75 и без чужого окна `heavy` | `test_gate_medium[G7]` |
| J1 | `validate_lock` всегда успешен | `test_malformed_lock_exit_2` (все) |
| J2 | `grant` не проверяет существующее окно | `test_grant_refuses[second_window]` |
| J3 | `close` удаляет любое окно | `test_close_refuses_foreign_window` |
| J4 | `grant` не удаляет `waiting:` своей сессии | `test_grant_writes_window_and_drops_waiting` |
| J5 | `validate_lock` не отбрасывает `\r` | `test_crlf_lock_is_valid` |

Стражи `test_gate_call_form_compat` (K1–K7), `test_gate_heavy_claim_not_downgraded`, `test_gate_light_file_runs_without_window`
зелёные при каждой инъекции, кроме M6 (K6). I1: добавлен `test_hook_allows[no_lock]` — без замка инвертированный хук
идёт дальше и блокирует C9 (в прежней редакции предсказания его не было).
