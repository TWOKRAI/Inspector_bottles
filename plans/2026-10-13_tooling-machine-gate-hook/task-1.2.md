# Task 1.2 — `grant` / `close` / `status` и проверка формата замка — план [2026-10-13_tooling-machine-gate-hook](../2026-10-13_tooling-machine-gate-hook.md)

Статус: [PENDING]. Ветка `feat/tooling-machine-gate-lock` (от `main` после 1.1). Ревью спеки: reviewer `a9c5a895d75a1c08c`,
итерация 1 — CHANGES REQUESTED (14 пунктов), все приняты в этот текст.

- **Level:** Middle · **Assignee:** `developer` (Sonnet); тесты — `tester` вслепую до кода
- **Module contract:** n/a
- **Handoff:** `tester`(RED) → `developer`(GREEN) → инъекции J (лид) → `reviewer`
- **Goal:** координатор меняет замок одной командой с проверкой формата; битый замок никогда не превращается
  в тихий пропуск 75; `status` даёт числа нагрузки без ручного замера.
- **Files:**
  1. `scripts/machine_gate.sh`
  2. `scripts/machine_gate_tests/test_machine_gate_lock.py` — пишет `tester`
  3. `.claude/plugins/dev/skills/coordinator/SKILL.md` (исходник) и 4. `.claude/skills/coordinator/SKILL.md` (зеркало) —
     только указатель на подкоманды в §2; файлы байт в байт одинаковы.
  Тесты Task 1.1 не правятся: их замки (`coordinator: c1 | since x` + `window: <s> | quiet|heavy|stand | x | until ~23:59`)
  проходят грамматику ниже.
- **Gate:** RED тестера → GREEN:
  `bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> python -m pytest -q --tb=short scripts/machine_gate_tests/test_machine_gate_lock.py scripts/machine_gate_tests/test_machine_gate_hook.py scripts/machine_gate_tests/test_machine_gate_classify_hazards.py`;
  `bash -n scripts/machine_gate.sh`; `ruff check -q`; `cmp` двух SKILL.md; инъекции J записаны с фактом; reviewer APPROVED по SHA.

## Грамматика замка (валидатор `validate_lock`)

- `\r` в конце строки отбрасывается; последняя строка без `\n` — тоже строка; пустая строка (длина 0 после снятия `\r`)
  допустима; строка из пробелов и BOM в начале файла — ошибка своей строки.
- Разделитель полей ` | ` (пробел, черта, пробел); `<name>` = `[A-Za-z0-9._-]+` (суффикс ` [ref]` — ошибка);
  `<kind>` ∈ {`quiet`,`heavy`,`stand`}. `medium` — класс команды, не вид окна.
- Свободный текст (`<что>`, `<текст>`) — любые символы, кроме ` | `: скобки, запятые, `~`, `—`, апостроф, `/`, `:` допустимы.
  - `coordinator: <name> | since <текст>` — ровно 2 поля, ровно одна такая строка;
  - `window: <name> | <kind> | <что> | until ~<текст>` — 4 поля, не больше одной строки;
  - `waiting: <name> | <kind> | <что> | <текст>` — 4 поля, сколько угодно;
  - `stand: <непустой текст>`;
  - любая другая строка — ошибка.
- Ошибка → код **2**, в stderr ровно одна строка; сообщается первая ошибка по порядку строк:
  - строка не по грамматике, вторая `coordinator:` или вторая `window:` → `machine_gate: malformed machine.lock:<N>: <строка>`,
    `<N>` — номер физической строки с 1 (пустые считаются), `<строка>` — без `\r`; у повтора — номер второй;
  - все строки годны, но строки `coordinator:` нет (и пустой файл) → `machine_gate: malformed machine.lock: no coordinator line`.
  Строка замка печатается как есть — исключение из правила «текст ошибки не несёт вводимое значение»: замок —
  конфигурация координатора, его читает каждая сессия, секретов в нём нет (как путь списка, classification.md §5).

## Подкоманды

- `[--timed] heavy|medium|light <session> <cmd…>` — порядок: usage (`< 3`) → `kind must be…` → если `machine.lock` есть,
  `validate_lock` (битый → 2, команда не запускается, строк `reclassified` и `timed list not found` нет) → classification.md §4 → §5 → §6.
  Нет `machine.lock` → проверки нет, запасной протокол `stand.lock` прежний. `classify` замок не читает и не меняется.
- `grant <coordinator> <session> <kind> <minutes> <что…>` — `<что>` = остальные аргументы через один пробел (`$*`).
  Имена сравниваются целиком как строки (не регулярное выражение, не префикс): `<coordinator>` — с именем строки
  `coordinator:`; строки сессии — поле 1 равно `waiting: <session>` / `window: <session>` целиком.
  `minutes` — целое 1..600 (0 — опечатка; 600 = 10 ч, дольше окна на этой машине не бывает: самое длинное — индексация qex, 80+ мин).
  Пишет `window: <session> | <kind> | <что> | until ~HH:MM` (`date -d "+<minutes> minutes" +%H:%M`) сразу после строки
  `coordinator:`, удаляет все строки с полем 1 `waiting: <session>`, остальные строки (и пустые) сохраняет в прежнем
  порядке. Файл пишется с LF: у каждой строки снят `\r`, после последней строки — `\n`.
  Запись: `machine.lock.tmp` в той же папке создаётся под `set -C` (занятый tmp — отказ п. 10) → `mv`; код `mv` проверяется.
- `close <coordinator> <session>` — удаляет строку с полем 1 `window: <session>`; остальное — как у `grant`
  (сравнение имён, LF, tmp под `set -C`, `mv` с проверкой кода).
- **Отказы `grant`/`close`** — код 2, файл байт в байт прежний, `machine.lock.tmp` не остаётся (кроме чужого в п. 10); в stderr
  ровно одна строка (значения аргументов в текст не попадают). Проверки по порядку, первая сработавшая даёт отказ:
  1. число аргументов (`grant` — меньше 6 вместе с `grant`; `close` — не ровно 3) →
     `usage: machine_gate.sh grant <coordinator> <session> quiet|heavy|stand <minutes> <what...>` /
     `usage: machine_gate.sh close <coordinator> <session>`;
  2. нет `machine.lock` → `machine_gate: no machine.lock`;
  3. замок битый → строка `malformed` (грамматика);
  4. `<coordinator>` ≠ имени строки `coordinator:` → `machine_gate: not the coordinator`;
  5. `<session>` не `<name>` → `machine_gate: bad session name`;
  6. (grant) вид не `quiet|heavy|stand` → `machine_gate: window kind must be quiet, heavy or stand`;
  7. (grant) `minutes` не `^[1-9][0-9]{0,2}$` или > 600 → `machine_gate: minutes must be 1..600`;
  8. (grant) в `<что>` есть `|`, `\r` или `\n` → `machine_gate: what must not contain | or line breaks`;
  9. (grant) в замке есть строка `window:` (любой сессии, своей тоже) → `machine_gate: a window is already open`;
     (close) нет строки с полем 1 `window: <session>` → `machine_gate: no window of this session`;
  10. `machine.lock.tmp` уже есть → `machine_gate: machine.lock.tmp exists (another grant/close running, or a leftover)`;
  11. `mv` не удался → `machine_gate: cannot replace machine.lock (busy), retry` (tmp удаляется).
- `status` — замок `${MACHINE_LOCK_DIR:-/d/PROJECT_INNOTECH/Inspector_vision}/machine.lock`. Печатает строки замка (каждая без `\r`
  и с `\n`, последняя тоже) или `machine.lock: none`, затем `ram_free_mb: <целое>` и `cpu_load_pct: <целое>`. Один вызов
  `timeout 20 powershell -NoProfile -Command '…'` (встроенная команда, не `-File`): `Win32_OperatingSystem.FreePhysicalMemory`
  один раз (КБ → МБ, целое деление); `Win32_Processor.LoadPercentage` — 5 запросов подряд без `Start-Sleep` (запрос сам
  меряет ~1 с: 5 подряд = 5,2 с — это 5-секундная выборка skill §3); пустые (`$null`) пропускаются, среднее — до целого;
  вывод powershell — через `tr -d '\r'`. powershell нет, ошибка, истёк `timeout` или все 5 пустые → `n/a` в своей строке.
  Замок битый → всё напечатано, затем строка `malformed` в stderr, код 2; иначе код 0.

## Steps (developer)

красный прогон → `validate_lock` → вызов во всех режимах → `grant`/`close` → `status` → указатель в SKILL.md: в
`.claude/plugins/dev/skills/coordinator/SKILL.md` §2 строку
`- Rewrite the whole file on every change with the Write tool; never append from two sessions.` заменить целиком на
`- Rewrite the whole file on every change with the Write tool, or open and close a window with `machine_gate.sh grant|close <coordinator> …` (checks the format, writes atomically); never append from two sessions. `machine_gate.sh status` prints the lock with free RAM and CPU.`
→ побайтная копия в `.claude/skills/coordinator/SKILL.md` → `cmp` → `bash -n`.

## Acceptance criteria

REDS, стражи и оба файла Task 1.1 зелёные; ручная проверка лидом на temp-замке `<tmp>`:
`MACHINE_LOCK_DIR=<tmp> bash scripts/machine_gate.sh status` → две последние строки `ram_free_mb: <число>`, `cpu_load_pct: <число>`, код 0;
`printf 'windw: x\n' > <tmp>/machine.lock; MACHINE_LOCK_DIR=<tmp> bash scripts/machine_gate.sh light s1 echo RAN; echo $?` →
stderr `machine_gate: malformed machine.lock:1: windw: x`, `RAN` нет, `2`.
До слияния в `main`: `bash scripts/machine_gate.sh status` на живом замке (только чтение) → код 0; код 2 → координатор правит
замок до слияния и предупреждает полосы.

## Out of scope

Подкоманда `wait`/постановка в очередь; вердикт допуска по порогам (координатор судит по числам сам); правка текста skill
`coordinator` сверх указателя; любой демон или служба; проверка, что `grant` зовёт именно сессия-координатор (имя сверяется,
личность — нет); истечение окна по `until` (гейт время не сравнивает, окно живёт до `close`); создание замка, смена
координатора и удаление файла (skill §2, §8 — Write tool); правка строки `stand:` при `grant … stand`; повтор `mv` при занятом
файле (отказ «busy», координатор повторяет сам); отдельный код выхода для битого замка (остаётся 2).

## REDS (`scripts/machine_gate_tests/test_machine_gate_lock.py`)

Ожидаемые значения — литералы отсюда. «Замок R1» = строки `coordinator: c1 | since x` / `waiting: s2 | heavy | a | ~3 min` /
`waiting: s22 | heavy | c | ~1 min` / `waiting: s3 | heavy | b | ~80 min` / `stand: free` (LF, `\n` после последней).

1. `test_grant_writes_window_and_drops_waiting` (параметры `lf`, `crlf` — замок R1 с `\r\n`): `grant c1 s2 heavy 20 T3.9 tests`
   (`T3.9`, `tests` — два аргумента) → код 0, stderr пуст; байты файла — fullmatch
   `coordinator: c1 \| since x\nwindow: s2 \| heavy \| T3\.9 tests \| until ~(\d\d:\d\d)\nwaiting: s22 \| heavy \| c \| ~1 min\nwaiting: s3 \| heavy \| b \| ~80 min\nstand: free\n`;
   HH:MM — между (часы Python до вызова + 20 мин) и (после вызова + 20 мин) по минутам; `os.stat(lock).st_ino` после ≠ до;
   в каталоге замка только `machine.lock`.
2. `test_grant_refuses` — база: замок R1 (LF). Параметр → вызов → текст после `machine_gate: `:
   `second_window` (база + `window: s3 | heavy | b | until ~23:59` второй строкой) `grant c1 s2 heavy 20 x` → `a window is already open`;
   `own_window` (то же с `window: s2 | heavy | b | until ~23:59`) → то же;
   `non_coordinator` `grant s9 s2 heavy 20 x`, `coordinator_prefix` `grant c s2 heavy 20 x`, `coordinator_regex` `grant c. s2 heavy 20 x` → `not the coordinator`;
   `bad_session` `grant c1 "s2 [ab]" heavy 20 x` → `bad session name`;
   `bad_kind` `fast`, `medium_kind` `medium` → `window kind must be quiet, heavy or stand`;
   `bad_minutes` `0`, `601`, `abc` → `minutes must be 1..600`;
   `pipe_in_what` `"a | b"`, `newline_in_what` `"a\nb"` → `what must not contain | or line breaks`;
   `few_args` `grant c1 s2 heavy 20` → строка `usage: machine_gate.sh grant <coordinator> <session> quiet|heavy|stand <minutes> <what...>` целиком;
   `no_lock` (пустой каталог) → `no machine.lock`, файл так и не появился;
   `tmp_exists` (рядом `machine.lock.tmp` с байтами `x`) → `machine.lock.tmp exists (another grant/close running, or a leftover)`, tmp не изменён;
   `busy` (только win32: тест держит `open(lock, "rb")` на время вызова) → `cannot replace machine.lock (busy), retry`, tmp нет.
   Везде код 2, stderr ровно одна строка, байты замка прежние.
3. `test_close_removes_own_window`: замок `coordinator: c1 | since x` / `window: s2 | heavy | x | until ~23:59` / пустая строка /
   `waiting: s3 | heavy | b | ~80 min` / `stand: free`; `close c1 s2` → код 0, байты ровно
   `coordinator: c1 | since x\n\nwaiting: s3 | heavy | b | ~80 min\nstand: free\n`, `st_ino` изменился, tmp нет.
4. `test_close_refuses`: `foreign_window` (окно у `s22`, `close c1 s2`) → `no window of this session`; `no_window` → то же;
   `non_coordinator` (`close s9 s2` при окне `s2`) → `not the coordinator`; код 2, stderr ровно строка, байты прежние.
5. `test_malformed_lock_exit_2` — декартово произведение 10 замков × 6 вызовов (60 случаев, ~0,1 с на вызов гейта).
   Замок = `coordinator: c1 | since x` + строка-дефект второй строкой (кроме `no_coordinator`):
   `window:s2 | heavy | x | until ~23:59`; `windw: s2 | heavy | x | until ~23:59`;
   две строки `window: s2 | heavy | x | until ~23:59` и `window: s3 | heavy | x | until ~23:59`;
   `window: s2 | fast | x | until ~1`; `window: s2 | medium | x | until ~1`; `window: s2 | heavy | until ~1`;
   `window: s2 [ab] | heavy | x | until ~23:59`; `coordinator: c2 | since y`; `waiting: s3 | heavy | b`;
   `no_coordinator` — только `window: s2 | heavy | x | until ~23:59`.
   Вызовы: `heavy s2 echo RAN`, `medium s2 echo RAN`, `--timed medium s2 echo RAN`, `light s2 echo RAN`,
   `grant c1 s2 heavy 5 x`, `close c1 s2` → код 2, `RAN` в stdout нет, stderr ровно одна строка:
   `windw:` → `machine_gate: malformed machine.lock:2: windw: s2 | heavy | x | until ~23:59`;
   две `window:` → начинается с `machine_gate: malformed machine.lock:3: window: s3`;
   `no_coordinator` → `machine_gate: malformed machine.lock: no coordinator line`;
   остальные → начинается с `machine_gate: malformed machine.lock:2: `; для `grant`/`close` байты замка прежние.
6. `test_status_prints_lock_and_metrics` — параметры `lock` (замок R1), `no_lock` (пустой каталог), `no_final_newline`
   (замок R1 без `\n` в конце), `malformed` (`coordinator: c1 | since x` / `windw: x`) → код 0 (`malformed` — код 2 и
   stderr ровно `machine_gate: malformed machine.lock:2: windw: x`); `re.search(r"^ram_free_mb: (\d+|n/a)$", out, re.M)` и
   `re.search(r"^cpu_load_pct: (\d+|n/a)$", out, re.M)` — это две последние строки stdout; строки замка — первыми, в прежнем
   порядке; без замка первая строка `machine.lock: none`; на win32 `ram_free_mb` — число. ~6 с на вызов.

## Стражи (зелёные и до правки)

- `test_live_sample_lock_is_valid` — параметры `lf`, `crlf` (каждая строка `\r\n` и пустая строка `\r\n` после первой),
  `no_final_newline` (LF, без `\n` в конце) — дословный живой замок 2026-10-13:
  ```
  coordinator: inspector-bottles-84 | since 2026-10-13 12:00
  waiting: inspector-bottles-3e | heavy | T3.9 post-merge Services/robot_comm/tests on main (after owner's word in its session) | ~3 min
  waiting: inspector-bottles-a4 | heavy | qex full reindex — only after the .ignore cause is found, evening | ~80 min
  stand: free
  ```
  `heavy inspector-bottles-3e echo RAN` → код 75, stdout содержит `NO WINDOW`, `RAN` нет, stderr пуст.
- `test_coordinator_free_text_is_valid` — формы, которые пишет координатор (свободный текст со скобками, запятыми, `~`, `—`):
  ```
  coordinator: inspector-bottles-23 | since 2026-10-14 08:43
  window: inspector-bottles-5d | heavy | T3.7 matrix (J1–J5, one file), then e2e ~3 runs | until ~13:40
  waiting: layer-render-6-2-17 | quiet | A/B timing, 2 × 5 min — after the window above | ~10 min
  stand: free
  ```
  `light s9 echo RAN` → код 0, `RAN` в stdout; `heavy s9 echo RAN` → код 75, `NO WINDOW`; stderr пуст в обоих.

## TRAPS

Как classification.md §9 (`_git_bash()` копией, `subprocess.run(..., timeout=60)`, замки — `write_bytes`); **каждый** вызов
гейта — с `MACHINE_LOCK_DIR=tmp_path.as_posix()`; `no_lock` — пустой подкаталог (без env тест читает и может переписать живой
замок); `busy` — `pytest.mark.skipif(sys.platform != "win32")` (на POSIX `rename` поверх открытого файла проходит);
`status` — ~6 с на вызов (powershell); реализацию гейта не читать; тестер перечисляет файлы, не каталог.
