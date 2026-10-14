# Классификация и допуск гейта — план [2026-10-13_tooling-machine-gate-hook](../2026-10-13_tooling-machine-gate-hook.md)

> Вынесено из плана (бюджет размера 32 КБ). Контракт для тестов Task 1.1; все значения — литералы, не из кода.
> Три класса — ответ владельца 2: `light` < `medium` < `heavy`. Признак `timed` и отмена слота — решения
> владельца 2026-10-13 через координатора b4 (раздел «Ответы владельца» в плане).

## 1. Сегменты и позиция команды

`classify` режет строку на сегменты по `&&`, `||`, `;`, `|`, переводу строки. Сегмент, в котором есть
`machine_gate.sh`, пропускается: его классифицирует сам гейт. Для каждого остального сегмента печатается
одна строка `<kind>\t<reason>\t<сегмент>`, где `kind` ∈ {`heavy`, `medium`, `light`}. Сегменты класса «нет»
не печатаются. Пустой вывод значит «тестовых команд нет». Код выхода всегда 0. Заявки агента и признака
`timed` `classify` не получает и не печатает.

Команда распознаётся **только в позиции команды**: в начале сегмента, после необязательных `VAR=val`,
`timeout N`, `uv run [--опции]`, `<python> [-опции] -m`. Слово в аргументах (`grep pytest`) не в счёт.
- **Кавычки.** `&&`, `||`, `;`, `|` внутри `'…'` и `"…"` сегмент не режут; внутри `"…"` обратная косая перед `"`
  экранирует кавычку.
- **Heredoc.** Строка с `<<` или `<<-` и словом-ограничителем (`WORD`, `'WORD'`, `"WORD"`) классифицируется как
  обычно, а строки её тела — до строки, равной `WORD` (для `<<-` — после снятия ведущих табуляций), —
  не классифицируются; строка после ограничителя снова классифицируется.
- **Префиксы позиции команды (дополнение).** Кроме `VAR=val`, `timeout`, `uv run`: слова `env`, `time`, `xargs`,
  `do`, `then`, `else`, `!`, `{`, `(`; у `timeout` пропускаются опции и значения опций `-k`, `-s`; у `uv run` —
  опции и значения опций `--python`, `--with`, `--project`, `--directory`, `-p`; `<python>` пропускает `-X <знач>`
  и `-W <знач>` перед `-m`; `powershell`, `powershell.exe`, `pwsh`, `pwsh.exe` ищут скрипт по ЛЮБОМУ токену сегмента.
  В третьем поле вывода ведущие слова `do`, `then`, `else`, `!`, `{`, `(`, `time` из сегмента удаляются (совет хука
  должен быть исполнимым командой гейта).
- **`make`.** Первый неопционный аргумент ∈ `gate`, `test`, `test-fast`, `test-fw`, `test-ctl` → `heavy` `make_suite`;
  прочие цели (`check`, `lint`, `help`, `test-ctl-offline`) — пусто.
- `<python>` — токен с basename `python`, `python3`, `python.exe`, `python3.exe` или `py`.
- Скрипты — по basename первого неопционного аргумента `<python>` или `powershell`: `run_framework_tests.py`,
  `run_sim_all.ps1`, `check_injections.py`, `mutation_gate.py`, `break_inject*.py` (префикс `break_inject`),
  `reindex_retry.py`, `qex_retry.py`.

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
| C29 | `pytest -c /d/wt/pyproject.toml a/tests/test_x.py` | light | `pytest_files` |
| C30 | `pytest --ignore a/tests/slow Services/robot_comm/tests` | medium | `pytest_module_dir` |
| C31 | `python backend_ctl/probes/break_inject_g4_other.py` | heavy | `injection_matrix` |
| C32 | `powershell -ExecutionPolicy Bypass -File scripts\run_sim_all.ps1` | heavy | `run_sim_all` |
| C33 | `pwsh -File scripts/run_sim_all.ps1` | heavy | `run_sim_all` |
| C34 | `python -X faulthandler -m pytest Services/robot_comm/tests` | medium | `pytest_module_dir` |
| C35 | `python -X utf8 -m pytest -q` | heavy | `pytest_no_file_args` |
| C36 | `python -W ignore -m pytest a/tests/test_x.py` | light | `pytest_files` |
| C37 | `env PYTHONUTF8=1 pytest -q` | heavy | `pytest_no_file_args` |
| C38 | `time pytest a/tests/test_x.py` (3-е поле: `pytest a/tests/test_x.py`) | light | `pytest_files` |
| C39 | `for f in a b; do pytest -q $f; done` (3-е поле: `pytest -q $f`; один ряд) | heavy | `pytest_no_file_args` |
| C40 | `if true; then pytest -q; fi` (3-е поле: `pytest -q`; один ряд) | heavy | `pytest_no_file_args` |
| C41 | `uv run --python 3.12 pytest -q` | heavy | `pytest_no_file_args` |
| C42 | `timeout -k 5 300 pytest -q` | heavy | `pytest_no_file_args` |
| C43 | `make gate` | heavy | `make_suite` |
| C44 | `make test-fast` | heavy | `make_suite` |
| C45 | `cat <<'EOF'⏎x⏎EOF⏎pytest -q` (один ряд, сегмент `pytest -q`) | heavy | `pytest_no_file_args` |
| C46 | `pytest -q && echo "done; ok"` (один ряд, сегмент `pytest -q`) | heavy | `pytest_no_file_args` |
| C47 | `echo "a \" b" ; pytest -q` (один ряд, сегмент `pytest -q`) | heavy | `pytest_no_file_args` |
| C48 | `{ pytest -q; }` (3-е поле: `pytest -q`; один ряд) | heavy | `pytest_no_file_args` |
| N9–N19 | `grep -n -E "cwd\|pytest\|subprocess" scripts/run_framework_tests.py`; `rg -n "conftest\|pytest\|unittest" scripts`; `git commit -m "fix: hook; pytest -q is blocked"`; `git log --grep="x; pytest -q"`; `echo 'a && pytest -q'`; `cat >> report.md <<'EOF'⏎pytest -q⏎EOF`; `git commit -F - <<EOF⏎python -m pytest a/tests⏎EOF`; `cat <<-EOF⏎⇥pytest -q⏎⇥EOF`; `make check`; `make test-ctl-offline`; `make help` | — (пустой вывод) | — |
| N1–N8 | `grep -n pytest pyproject.toml`; `git log --grep=pytest --oneline`; `cat pytest.ini`; `rg run_framework_tests scripts`; `git show HEAD:scripts/run_sim_all.ps1`; `echo pytest`; `pip show pytest`; `ls` | — (пустой вывод) | — |

Обозначения: `⏎` — перевод строки, `⇥` — табуляция (тесты пишут настоящие). N9–N19 — по порядку перечисления; id параметра — `N9`…`N19`. Строки C32–C48 и N9–N19 проверяют авторские тесты developer в отдельном файле
`scripts/machine_gate_tests/test_machine_gate_classify_hazards.py` (слепой tester второй раз не запускается): `test_classify_hazards` (C32–C48, N9–N19), `test_hook_hazards_allow` (N9–N16 через хук при живом замке с чужим окном → код 0, stderr пуст), `test_hook_advice` (H1–H4 ниже), `test_classify_many_segments_is_fast` (1500 сегментов `echo x` и последний `pytest -q`: classify за ≤ 8 с, один ряд heavy).

Совет хука (дополнение к шагу 4(д) плана): ведущие `VAR=val` сегмента ставятся ПЕРЕД `bash`; строка совета — `<VAR=val …> bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" <kind> <session> <остаток сегмента>`; `<kind>` и сегмент берутся из строки classify с НАИБОЛЬШИМ рангом (при равенстве — первой), как в §4.
- H1 `cd D:/wt && PYTHONPATH=. python -m pytest a/tests/test_x.py` → код 2; stderr содержит `PYTHONPATH=. bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> python -m pytest a/tests/test_x.py` и не содержит `light <session> PYTHONPATH`;
- H2 `pytest a/tests/test_x.py && pytest -q` → код 2; stderr содержит `machine_gate.sh" heavy <session> pytest -q`;
- H3 `make gate` → код 2; stderr содержит `machine_gate.sh" heavy <session> make gate`;
- H4 `powershell -ExecutionPolicy Bypass -File scripts\run_sim_all.ps1` → код 2; stderr содержит `(run_sim_all)`.
Слова-кандидаты префильтра хука — прежние плюс `make`. До вызова `classify_segment` гейт пропускает сегменты, в которых нет ни одного слова-кандидата (иначе 1200 сегментов — 9 с при таймауте хука 10 с).

Пояснения: C10 — каталог есть, но не `*/tests`; C16 — хвостовой `/`; C17 — каталог модуля и `.py` рядом, класс
задаёт каталог; C18 — абсолютный путь, `kin` — значение `-k`; C19 — обёрнутый сегмент, заявку поднимает гейт;
C20, C21 — токена с `/` нет, значит путей нет; C22 — после отбрасывания `.` остаётся один сегмент; C26 — правило 3
срабатывает раньше правила 5; C28 — `\` делает токен путём, но сегменты каталога режутся только по `/`
(один сегмент `Services\robot_comm\tests`); C29, C30 — значение опции из списка §3 не путь; C31 — префикс `break_inject`.

## 3. Правило pytest

Токены сегмента после `pytest` — через пробел; кавычки не разбираются (токен `"a/tests"` — не каталог модуля).
- **опция** — токен, начинающийся с `-`;
- **значение** — токен сразу после опции из списка `-c`, `-p`, `-k`, `-m`, `-o`, `--rootdir`, `--basetemp`,
  `--confcutdir`, `--ignore`, `--ignore-glob`, `--deselect`: не опция, не файл, не каталог (форма `--opt=x` —
  один токен-опция);
- **файл** — не опция и не значение, оканчивается на `.py` или содержит `.py::`;
- **каталог** — не опция, не значение и не файл, содержит `/` или `\`;
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
Неверный класс → stderr `kind must be heavy, medium or light`, код 2, команда не запускается.

## 5. Признак `timed` (только в гейте; `classify` и хук его не знают)

- Форма вызова: `machine_gate.sh [--timed] heavy|medium|light <session> <cmd…>`. `--timed` — строго первым
  аргументом, перед классом; гейт снимает его, затем проверяет число аргументов (`< 3` → usage, код 2).
  Без флага форма, коды 0/2 и тексты 75 прежние. Флага снятия (`--plain`) нет.
- Список: файл `${MACHINE_GATE_TIMED_LIST:-<каталог гейта>/machine_gate_timed.txt}`; `\r` в конце строки
  отбрасывается; пустые строки пропускаются; остальные — записи целиком. Поставляемый
  `scripts/machine_gate_timed.txt` — ровно 7 строк в этом порядке:
  `Plugins/sim/`, `Services/robot_comm/`, `Services/line_sim/`, `Services/device_hub/`, `multiprocess_framework/`,
  `run_framework_tests.py`, `run_sim_all.ps1`.
- Совпадение: строка команды (`$*`) режется на токены по пробелам; в токене `\` → `/`; запись — **подстрока**
  токена. Смотрятся все токены команды, не только пути после pytest. `/d/wt/Services/robot_comm/tests` и
  `multiprocess_framework/modules/recipe/tests` — timed; `a/tests` — нет.
- `timed` = флаг `--timed` **или** совпадение по списку. Признак влияет **только** на итоговый класс `medium`
  (после §4); для `light` и `heavy` флаг и список молча без эффекта.
- Список читается **всегда**, когда итоговый класс `medium` (до проверки окна, и при своём окне тоже); при
  `light` и `heavy` не читается. Сравнение с учётом регистра. Файла нет или он не читается → такой `medium` timed
  (fail-closed) и stderr `machine_gate: timed list not found: <путь>`. Путь печатается как есть: это конфигурация
  оператора, не секрет (исключение из правила «текст ошибки не несёт вводимое значение»).

## 6. Допуск по классам

Своё окно — строка, где поле 1 равно `window: <session>` целиком. Чужое — любая другая строка с полем 1
`window: …`; её вид — поле 2. Пропуск печатает в **stdout** `<ТЕКСТ> — skipped (machine_gate: <класс>, <session>)`
(класс — после §4) и даёт код 75. Запуск — код команды. Слота и ограничения «один `medium` за раз» нет:
параллельность ограничивает RAM-допуск координатора; гейт RAM не меряет.

| Состояние замка | `heavy` | `medium` не-timed | `medium` timed | `light` |
|---|---|---|---|---|
| нет `machine.lock` | `stand.lock`: чужой `measure` → 75 `STAND MEASURE (stand.lock)`, иначе запуск | так же | так же | так же |
| своё окно любого вида | запуск | запуск | запуск | запуск |
| чужое `quiet` | 75 `NO WINDOW` | 75 `QUIET WINDOW` | 75 `NO WINDOW` | 75 `QUIET WINDOW` |
| чужое `stand` | 75 `NO WINDOW` | 75 `STAND WINDOW` | 75 `NO WINDOW` | запуск |
| чужое `heavy` | 75 `NO WINDOW` | запуск | 75 `NO WINDOW` | запуск |
| окон нет | 75 `NO WINDOW` | запуск | 75 `NO WINDOW` | запуск |

Битый `machine.lock` → код 2 во всех режимах, до §4–§6 (Task 1.2, [task-1.2.md](task-1.2.md)).

Колонки `heavy` и `light` — поведение гейта на 2026-10-13, не меняются (стражи K1–K7). Timed `medium` по допуску
≡ `heavy`. Окно «только для timed medium и heavy» следует из «одно окно в замке»; логики «чужой timed ждёт» нет.

## 7. Тесты гейта Task 1.1 (`test_machine_gate_hook.py`)

**Обозначения.** `L` = `tmp_path/"lock"`, env `MACHINE_LOCK_DIR=L.as_posix()`; `T` = `tmp_path.as_posix()`;
`TW` = `str(tmp_path)` (с `\`); `PY` = `Path(sys.executable).as_posix()`; сессия гейта — `s1`. Каждый
`L/machine.lock` начинается строкой `coordinator: c1 | since x`. Окна (вторая строка): чужое —
`window: other-s | <вид> | x | until ~23:59`; своё — `window: s1 | <вид> | x | until ~23:59`; «окон нет» — только
строка `coordinator:`. `stand.lock` — `L/stand.lock`, строка `other-s | x | measure` (в таблицах `\|` — экранирование
markdown). Временный список (строки G, T, кроме T10, T11): `<T>/timed.txt` со строками `Services/robot_comm/`,
`multiprocess_framework/`, `zz_timed_only_here/`; env `MACHINE_GATE_TIMED_LIST=<T>/timed.txt`.

Файл `test_m.py` (одинаковый во всех каталогах ниже):
```python
import pathlib
def test_m():
    pathlib.Path(__file__).resolve().parents[1].joinpath("seen.txt").write_text("RAN")
```
`seen.txt` лежит в родителе каталога `tests`: есть — команда запускалась; нет — не запускалась.
- `MOD` = `PY -m pytest -q -p no:cacheprovider <T>/mod/tests` (не-timed); `MODF` = то же с `<T>/mod/tests/test_m.py`;
- `MODT` = то же с `<T>/Services/robot_comm/tests` (timed по списку); `FILET` = `<T>/Services/robot_comm/tests/test_m.py`;
  `FILETW` = `TW\Services\robot_comm\tests\test_m.py`; `MODZ` = каталог `<T>/zz_timed_only_here/tests`.

Правило колонки stderr: пустая ячейка → в stderr нет `reclassified` и нет `timed list not found`.

**`test_gate_medium`, строки G — не-timed** (красный до кода; заявка `medium`, если не сказано иное):

| ID | вызов | `machine.lock` (2-я строка) | команда | код | stdout содержит | stderr содержит | `seen` |
|---|---|---|---|---|---|---|---|
| G1 | `medium s1` | — (окон нет) | MOD | 0 | — | | есть |
| G2 | `medium s1` | чужое `quiet` | MOD | 75 | `QUIET WINDOW`, `(machine_gate: medium, s1)` | | нет |
| G3 | `medium s1` | чужое `stand` | MOD | 75 | `STAND WINDOW`, `(machine_gate: medium, s1)` | | нет |
| G4 | `medium s1` | чужое `heavy` | MOD | 0 | — | | есть |
| G5 | `medium s1` | своё `quiet` / `heavy` / `stand` (3 параметра) | MOD | 0 | — | | есть |
| G6 | `medium s1` | нет `machine.lock`, нет `stand.lock` | MOD | 0 | — | | есть |
| G7 | `medium s1` | нет `machine.lock`; есть `stand.lock` | MOD | 75 | `STAND MEASURE (stand.lock)` | | нет |
| G8 | `light s1` | чужое `quiet` | MOD | 75 | `QUIET WINDOW`, `(machine_gate: medium, s1)` | `machine_gate: reclassified light -> medium (pytest_module_dir)` | нет |
| G9 | `light s1` | чужое `stand` | MOD | 75 | `STAND WINDOW` | как G8 | нет |
| G10 | `--timed medium s1` | — (окон нет) | MOD | 75 | `NO WINDOW`, `(machine_gate: medium, s1)` | | нет |
| G11 | `--timed medium s1` | своё `heavy` | MOD | 0 | — | | есть |
| G12 | `--timed light s1` | — (окон нет) | MODF | 0 | — | | есть |

**`test_gate_medium`, строки T — timed:**

| ID | вызов | `machine.lock` (2-я строка) | команда | код | stdout содержит | stderr содержит | `seen` |
|---|---|---|---|---|---|---|---|
| T1 | `medium s1` | — (окон нет) | MODT | 75 | `NO WINDOW`, `(machine_gate: medium, s1)` | | нет |
| T2 | `medium s1` | чужое `heavy` | MODT | 75 | `NO WINDOW` | | нет |
| T3 | `medium s1` | чужое `quiet` | MODT | 75 | `NO WINDOW`; **нет** `QUIET WINDOW` | | нет |
| T4 | `medium s1` | чужое `stand` | MODT | 75 | `NO WINDOW`; **нет** `STAND WINDOW` | | нет |
| T5 | `medium s1` | своё `quiet` / `heavy` / `stand` (3 параметра) | MODT | 0 | — | | есть |
| T6 | `medium s1` | нет `machine.lock`, нет `stand.lock` | MODT | 0 | — | | есть |
| T7 | `medium s1` | нет `machine.lock`; есть `stand.lock` | MODT | 75 | `STAND MEASURE (stand.lock)` | | нет |
| T8 | `light s1` | — (окон нет) | MODT | 75 | `NO WINDOW`, `(machine_gate: medium, s1)` | `machine_gate: reclassified light -> medium (pytest_module_dir)` | нет |
| T9 | `medium s1` | — (окон нет) | FILET | 75 | `NO WINDOW` | | нет |
| T10 | `medium s1`; env списка = `<T>/no_such.txt` | — (окон нет) | MOD | 75 | `NO WINDOW` | `machine_gate: timed list not found:` и `no_such.txt` | нет |
| T11 | `medium s1`; env списка = `<T>/no_such.txt` | своё `heavy` | MOD | 0 | — | `machine_gate: timed list not found:` и `no_such.txt` | есть |
| T12 | `light s1` | — (окон нет) | FILET | 0 | — | | есть |
| T13 | `medium s1` | — (окон нет) | FILETW | 75 | `NO WINDOW` | | нет |
| T14 | `medium s1` | — (окон нет) | MODZ | 75 | `NO WINDOW` | | нет |

T9, T13 — заявка `medium` на файл внутри timed-пути: не понижается и timed по токену. T12 — `light` внутри
timed-пути запускается: timed влияет только на `medium`. T14 — запись есть только во временном списке.

**`test_gate_claim`** (красный до кода; замок без окна `s1`, `<T>/run_framework_tests.py` = `print("FAKE")`):

| ID | вызов | команда | код | stdout | stderr содержит |
|---|---|---|---|---|---|
| R1 | `light s1` | `python <T>/run_framework_tests.py` | 75 | `NO WINDOW`, нет `FAKE` | `machine_gate: reclassified light -> heavy (run_framework_tests)` |
| R2 | `light s1` | `python -m pytest --version` | 75 | `NO WINDOW` | `machine_gate: reclassified light -> heavy (pytest_no_file_args)` |
| R3 | `medium s1` | `python <T>/run_framework_tests.py` | 75 | `NO WINDOW`, нет `FAKE` | `machine_gate: reclassified medium -> heavy (run_framework_tests)` |
| R4 | `fast s1` | `echo RAN` | 2 | нет `RAN` | `kind must be heavy, medium or light` |

**`test_gate_call_form_compat`** — страж формы вызова полос (`heavy|light <session> <cmd>`); зелёный **до и после**
правки. `EXIT(n)` = `PY -c "import sys; sys.exit(n)"`. Во всех строках stderr не содержит `reclassified`.

| ID | заявка | `machine.lock` (2-я строка) | команда | код | stdout содержит |
|---|---|---|---|---|---|
| K1 | heavy | чужое `heavy` | `EXIT(3)` | 75 | `NO WINDOW`, `(machine_gate: heavy, s1)` |
| K2 | light | чужое `quiet` | `EXIT(3)` | 75 | `QUIET WINDOW`, `(machine_gate: light, s1)` |
| K3 | light | чужое `heavy` | `EXIT(4)` | 4 | — |
| K4 | light | чужое `stand` | `EXIT(4)` | 4 | — |
| K5 | light | нет `machine.lock`; есть `stand.lock` | `EXIT(3)` | 75 | `STAND MEASURE (stand.lock)` |
| K6 | heavy | — (окон нет) | `PY -m pytest -q -p no:cacheprovider <T>/test_ok.py` | 75 | `NO WINDOW` |
| K7 | heavy | нет `machine.lock`, нет `stand.lock` | `EXIT(5)` | 5 | — |

`<T>/test_ok.py` = `def test_ok(): pass`.

## 8. Инъекции — предсказание до прогона

Таблица, предсказания и факт прогона — в [injections.md](injections.md).

## 9. REDS, стражи и TRAPS Task 1.1 (тестер; `scripts/machine_gate_tests/test_machine_gate_hook.py`)

**REDS — 10 функций:**
1. `test_classify` — C1–C18, C20–C31 по id строки; проверяет kind и reason.
2. `test_classify_none` — N1–N8, C19: пустой stdout, код 0.
3. `test_hook_allows` — параметры: `no_lock` (замка нет, команда C9); `wrapped` — `bash "<gate>" heavy s1 pytest -q`;
   N1–N8; `bad_json` — stdin `{"tool_input": {"command": "pytest -q"` (обрезанный JSON со словом-кандидатом);
   везде, кроме `no_lock`, замок с чужим окном → код 0, stderr пуст.
4. `test_hook_blocks` — параметры: `C10` → stderr содержит `BLOCKED by machine-gate-guard` и
   `machine_gate.sh" heavy <session> python -m pytest multiprocess_framework/modules`; `C12` → `machine_gate.sh" light <session>`;
   `C15` → `this command is medium (pytest_module_dir)` и `machine_gate.sh" medium <session> pytest Services/robot_comm/tests` → код 2.
5. `test_hook_blocks_unwrapped_segment_after_wrapped` — `bash "<gate>" light s1 pytest a/tests/test_x.py && pytest -q` → код 2.
6. `test_hook_independent_of_cwd` — cwd = `tmp_path` вне git, `CLAUDE_PROJECT_DIR=tmp_path`, команда C9 → код 2.
7. `test_gate_claim` — R1–R4 (§7).
8. `test_gate_medium` — G1–G12, T1–T14 (§7).
9. `test_hook_installed` — параметры: `settings` — в `.claude/settings.json` у записи PreToolUse с matcher `Bash`
   третья команда списка `hooks` содержит `machine-gate-guard.sh`, вторая — `protect-branch.sh`, у третьей `timeout` = 10;
   `eol_lf` — вывод `git check-attr eol -- .claude/plugins/dev/hooks/machine-gate-guard.sh` оканчивается на `eol: lf`.
10. `test_timed_list_shipped` — `scripts/machine_gate_timed.txt` (рядом с гейтом) содержит ровно 7 непустых строк
    в порядке §5, литералами.

**Стражи (зелёные и до правки):** `test_gate_light_file_runs_without_window` (замок без окна; `light s1 PY -m pytest
-q -p no:cacheprovider <T>/test_ok.py` → код 0); `test_gate_call_form_compat` (K1–K7) — полосы уже зовут
`heavy|light <session> <cmd>`: форма, коды и тексты 75 не меняются.

**TRAPS:**
- пути temp-замка и списка — `tmp_path.as_posix()`; ни один тест не трогает живой
  `D:\PROJECT_INNOTECH\Inspector_vision\machine.lock` (всегда `MACHINE_LOCK_DIR`) и поставляемый список (строки G, T —
  всегда `MACHINE_GATE_TIMED_LIST`);
- каждый temp-замок начинается строкой `coordinator: c1 | since x` (иначе Task 1.2 сделает тесты красными);
- `machine.lock` и `stand.lock` писать с LF (`write_bytes` или `write_text(..., newline="\n")`); временный
  список `timed.txt` (строки G, T) — с `\r\n` через `write_bytes`: гейт обязан снимать `\r` (инъекция M18);
- bash — помощник `_git_bash()` из `scripts/atlas/tests/test_lint_brief_1_9c.py:982` **скопировать**, не
  импортировать; он возвращает лаунчер `<Git>/bin/bash.exe` (найден по родителям `git`), а не `System32\bash.exe` (WSL);
- у каждого вызова гейта и хука — `subprocess.run(..., timeout=60)`; реальные прогоны — через `PY` (`sys.executable`);
- тестер при своём прогоне перечисляет файлы, а не каталог, иначе его прогон классифицируется `medium` или `heavy`.
