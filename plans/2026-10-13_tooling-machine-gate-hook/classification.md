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
| N1–N8 | `grep -n pytest pyproject.toml`; `git log --grep=pytest --oneline`; `cat pytest.ini`; `rg run_framework_tests scripts`; `git show HEAD:scripts/run_sim_all.ps1`; `echo pytest`; `pip show pytest`; `ls` | — (пустой вывод) | — |

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

## 8. Инъекции — предсказание до прогона (раздел «Пайплайн», п. 4 плана)

Лид записывает факт рядом с предсказанием; каждая инъекция — `light` прогон одного файла. Имена — тесты
`test_machine_gate_hook.py` (I, M) и `test_machine_gate_lock.py` (J); в скобках — id параметров.

| ID | Поломка | Предсказанные красные |
|---|---|---|
| I1 | хук: проверка замка инвертирована (`exit 0` при наличии замка) | `test_hook_blocks` (C10, C12, C15), `test_hook_blocks_unwrapped_segment_after_wrapped`, `test_hook_independent_of_cwd`, `test_hook_allows[no_lock]` |
| I2 | `classify`: удалено правило `-n` | `test_classify` (C11, C25) |
| I3 | `classify`: снята привязка к позиции команды | гарантированно `test_classify_none` (N1, N6, N7), `test_hook_allows` (N1, N6, N7); N2–N5 — зависят от реализации (подстрока против токена), не обещаются |
| I4 | хук: «обёрнуто», если `machine_gate.sh` есть где угодно в строке (не по сегментам) | `test_hook_blocks_unwrapped_segment_after_wrapped` |
| I5 | гейт: убрана вся реклассификация (класс = заявка) | `test_gate_claim` (R1–R3), `test_gate_medium` (G8, G9, T8) |
| I6 | хук: убран `tr -d '\r'` | **может остаться зелёной**: в тестах хука нет многострочных команд, python CR не выдаёт; если зелёная — записать как необнаруженную, тест под неё не придумывать |
| I7 | хук: вызов python без обработки ошибки (битый JSON → traceback, ненулевой код) | `test_hook_allows[bad_json]` |
| M1 | `classify`: правило 5 даёт `heavy` вместо `medium` (reason прежний) | `test_classify` (C15–C18, C30), `test_hook_blocks[C15]`, `test_gate_medium` (G1–G11, T1–T8, T10, T11, T14): строка `reclassified … -> heavy` там, где stderr должен быть пуст |
| M2 | `classify`: reason `pytest_module_dir` переименован в `pytest_module_tests` | `test_classify` (C15–C18, C30), `test_hook_blocks[C15]`, `test_gate_medium` (G8, G9, T8) |
| M3 | `classify`: каталог модуля — любой каталог, чей последний сегмент (разбивка по `/`) равен `tests`, сегменты не считаются | `test_classify[C22]`; C28 остаётся зелёной (`/` нет — один сегмент `Services\robot_comm\tests`, не `tests`) |
| M4 | `classify`: значения опций списка §3 не пропускаются | `test_classify` (C29, C30) |
| M5 | гейт: не-timed `medium` не проверяет чужое `quiet` | `test_gate_medium` (G2, G8) |
| M6 | гейт: чужое `stand` не блокирует не-timed `medium` | `test_gate_medium` (G3, G9) |
| M7 | гейт: класс = вывод `classify`, если он не пуст (понижение разрешено) | `test_gate_medium` (T9, T13), `test_gate_call_form_compat[K6]` |
| M8 | гейт: `timed` не вычисляется (список не читается, флаг снимается и забывается) | `test_gate_medium` (T1–T4, T8–T11, T13, T14, G10) |
| M9 | гейт: `--timed` снимается, но не учитывается (список работает) | `test_gate_medium[G10]` |
| M10 | гейт: `--timed` не разбирается (первый аргумент считается классом) | `test_gate_medium` (G10, G11, G12) — код 2 |
| M11 | гейт: подстрока заменена точным равенством токена записи | `test_gate_medium` (T1–T4, T8, T9, T13, T14) |
| M12 | гейт: timed `medium` под чужим `quiet` отвечает `QUIET WINDOW` | `test_gate_medium[T3]` |
| M13 | гейт: список читается только рядом с гейтом, env `MACHINE_GATE_TIMED_LIST` не учитывается | `test_gate_medium` (T10, T11, T14) — T1–T9 зелёные: `Services/robot_comm/` есть и в поставляемом списке |
| M14 | гейт: fail-closed убран (список недоступен → ничего не timed; строка stderr остаётся) | `test_gate_medium[T10]` |
| M15 | гейт: `--timed` действует и на `light` (как timed `medium`) | `test_gate_medium[G12]` |
| M16 | гейт: совпадение по списку действует и на `light` | `test_gate_medium[T12]` |
| M17 | гейт: в токене не делается `\` → `/` | `test_gate_medium[T13]` |
| M18 | гейт: `\r` в конце записи списка не отбрасывается (временный список тестов записан с `\r\n`) | `test_gate_medium` (T1–T4, T8, T9, T13, T14) |
| J1 | `validate_lock` всегда успешен | `test_malformed_lock_exit_2` (все) |
| J2 | `grant` не проверяет существующее окно | `test_grant_refuses[second_window]` |
| J3 | `close` удаляет любое окно | `test_close_refuses_foreign_window` |
| J4 | `grant` не удаляет `waiting:` своей сессии | `test_grant_writes_window_and_drops_waiting` |
| J5 | `validate_lock` не отбрасывает `\r` | `test_crlf_lock_is_valid` |

Стражи `test_gate_call_form_compat` (K1–K7) и `test_gate_light_file_runs_without_window` зелёные при каждой
инъекции, кроме M7 (K6). I1 включает `test_hook_allows[no_lock]`: без замка инвертированный хук идёт дальше и
блокирует C9.

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
