# Plan: гейт машины как механизм — хук PreToolUse и подкоманды machine_gate.sh

- **Slug:** tooling-machine-gate-hook
- **Дата:** 2026-10-13
- **Статус:** DRAFT
- **Ветка:** `feat/tooling-machine-gate-hook`
- **Plan review:** —
- **Откуда:** коммит `9173bf1c4` (skill `coordinator`, `scripts/machine_gate.sh`, `project-rules` §8,
  `.claude/CLAUDE.md` «Shared machine»); оценка ревьюера, принятая владельцем («полезно и нужно»):
  2026-10-13 правила прозой не сработали — старый протокол `stand.lock` не вспомнила ни одна сессия.
  Значит, правило должно стать механизмом.

## Обзор

Сейчас гейт `machine_gate.sh` работает, только если агент сам вспомнил его вызвать. План делает две вещи:
1. хук PreToolUse на Bash не пускает тестовую или тяжёлую команду мимо гейта, пока лежит `machine.lock`;
   гейт сам определяет, тяжёлая команда или лёгкая, и не верит заявке агента;
2. у координатора появляются `grant` / `close` / `status`: замок переписывается с проверкой формата,
   битый замок даёт код 2 (не тихие 75), `status` печатает свободную RAM и загрузку CPU.

Без демона, без новой зависимости: bash + уже используемый в хуках python (только разбор JSON) + powershell CIM.

## Решения, принятые в плане (ponytail)

- **Классификатор — один, в гейте.** Новая подкоманда `machine_gate.sh classify <строка команды>`.
  Её вызывают и хук, и сам гейт в режимах `heavy|medium|light`. Второй копии правил нет.
- **Хук тонкий.** Замка нет — `exit 0` до запуска python (выключено = ноль стоимости). В сыром stdin нет
  ни одного слова-кандидата — `exit 0` до python. Только потом python достаёт `tool_input.command`,
  а решение принимает `classify`.
- **Хук блокирует любую тестовую команду мимо гейта, пока замок есть**: всех трёх классов. Это ровно правило
  §8 «every test or stand command goes through the gate». Хук не знает имени сессии (во входе хука есть
  только `session_id`), поэтому окно проверяет не он, а гейт. Держатель окна тоже идёт через гейт —
  гейт его пропустит.
- **Внутренняя ошибка хука → пропуск (fail open).** Нет python, нет гейта, битый JSON — `exit 0`.
  Это помощник координации, не граница безопасности. Блок (`exit 2`) — только по явному ответу `classify`.
- **Хук живёт в плагине `dev`** (там же skill `coordinator`): `.claude/plugins/dev/hooks/machine-gate-guard.sh`.
  Регистрация — только в `.claude/settings.json`. Регистрацию в `dev/.claude-plugin/plugin.json` пропускаем:
  хук завязан на путь замка этой машины, плагины в проекте не включены (`enabledPlugins` — только внешние).
- **Путь гейта в хуке — от файла хука**: `$(dirname "$0")/../../../../scripts/machine_gate.sh`, то есть то же
  дерево, откуда запущен хук. Замок — абсолютный путь (`MACHINE_LOCK_DIR`, по умолчанию
  `/d/PROJECT_INNOTECH/Inspector_vision`); от cwd решение не зависит.
- **`timed` — только в гейте.** Признак `medium` «трогает чувствительное к времени» (список путей или `--timed`)
  делает допуск `medium` как у `heavy`. `classify` и хук его не знают: второй копии правил нет.
- **Блок хука печатает `<segment>` целиком, с префиксом `VAR=val`** (принятое исключение): сегмент должен быть
  воспроизводим (`PYTHONPATH` меняет смысл), значения уже в транскрипте, секреты по правилам лежат в env, не в строке.
- **Писать замок может только координатор:** `grant`/`close` первым аргументом берут имя координатора и
  сверяют его со строкой `coordinator:`. Проверка дешёвая и ловит полосу, которая пишет замок сама.

## Классификация и допуск (контракт для тестов; литералы, не из кода)

Вынесены в [`2026-10-13_tooling-machine-gate-hook/classification.md`](2026-10-13_tooling-machine-gate-hook/classification.md)
(бюджет 32 КБ): §1–§3 правила и таблица C1–C31, §4 реклассификация, §5 `timed`, §6 допуск, §7 тесты гейта,
§8 инъекции, §9 REDS и TRAPS Task 1.1.

## Порядок выполнения

### Фаза 1 — механизм

### Task 1.1 — хук PreToolUse и `classify` в гейте [DONE 0bfd4bb76]
- **Level:** Middle+ (три класса, `timed`, флаг, допуск) · **Assignee:** `developer` (Sonnet); тесты пишет `tester` вслепую до кода
- **Module contract:** n/a (инструменты, не модуль фреймворка)
- **Handoff:** `tester`(RED) → `developer`(GREEN) → `reviewer`
- **Gate:** RED тестера → GREEN (гейт `light`, один файл); `bash -n` обоих `.sh`; `ruff check -q`; `git check-attr eol`
  хука = `lf`; инъекции записаны с фактом; reviewer APPROVED по SHA.
- **Goal:** пока `machine.lock` существует, Bash-команда с тестом или тяжёлой работой мимо `machine_gate.sh`
  блокируется с сообщением, где написана команда гейта; гейт знает три класса `light` < `medium` < `heavy`,
  сам поднимает заниженную заявку (никогда не понижает), пускает `medium` по таблице допуска, timed `medium` — как `heavy`.
- **Files** (developer — 1–4, 6, 7; файл 5 пишет tester):
  1. `.claude/plugins/dev/hooks/machine-gate-guard.sh` — новый
  2. `scripts/machine_gate.sh` — подкоманда `classify`, режим `medium`, флаг `--timed`, реклассификация вверх
  3. `.claude/settings.json` — PreToolUse, matcher `Bash`, третьим, сразу после protect-branch.sh, `timeout: 10`,
     форма строки — как у соседей: `bash \"${CLAUDE_PROJECT_DIR}\"/.claude/plugins/dev/hooks/machine-gate-guard.sh`
  4. `pyproject.toml` — строка "scripts/machine_gate_tests" в `testpaths` с комментарием (иначе тесты молча
     не гоняются; страж `test_no_test_dir_is_invisible_to_every_runner`)
  5. `scripts/machine_gate_tests/test_machine_gate_hook.py` — пишет `tester`, developer не правит
  6. `.gitattributes` — строка `.claude/plugins/dev/hooks/machine-gate-guard.sh text eol=lf`
  7. `scripts/machine_gate_timed.txt` — новый, 7 строк литералом (classification.md §5)
  Нужен ещё файл — стоп и вопрос лиду. Слияние 1.1 = регистрация хука (файл 3) → слияние в `main` ждёт
  слова владельца и предупреждения полос координатором.
- **Steps (developer):**
  1. Красный прогон тестов тестера (команда ниже), список красных — в отчёт.
  2. `classify` в `machine_gate.sh`: функция `classify_cmd`, режем на сегменты через `sed -E`, правила —
     classification.md §1–§3. Ветка `classify` разбирается **до** проверки `$# -lt 3` (у неё один аргумент).
  3. Режимы `[--timed] heavy|medium|light` (usage и ошибка `kind must be heavy, medium or light` — с `medium`):
     снять `--timed`, проверить число аргументов, `classify_cmd "$*"`, поднять класс по §4; `timed` — §5; допуск — §6.
     Ветки `heavy` и `light` не меняются. Файл 7 — 7 строк §5 в том же порядке.
  4. Хук: шапка-комментарий по-русски. Порядок: (а) `lock="${MACHINE_LOCK_DIR:-/d/PROJECT_INNOTECH/Inspector_vision}/machine.lock"`,
     нет файла → `exit 0`; (б) `INPUT=$(cat)`; `grep -qE 'pytest|run_framework_tests|run_sim_all|check_injections|mutation_gate|break_inject|reindex|qex_retry'`
     не нашёл → `exit 0`; (в) python — разрешение как в `.claude/plugins/dev/hooks/lint-brief.sh`
     (`$HOOK_DIR/../../core/hooks/_lib/python-bin.sh`), нет → `exit 0`; команда — через
     `$(... | tr -d '\r')`, печать `sys.stdout.write`, **никогда** `read < <(...)` (урок про CR);
     (г) гейта нет → `exit 0`; `out=$(bash "$gate" classify "$CMD")`; пусто → `exit 0`;
     (д) иначе блок по первой строке `out` (`<kind>` — любой из трёх): `exit 2`, в stderr ровно три строки и строка `hook:`:
     ```
     BLOCKED by machine-gate-guard: machine.lock exists and this command is <kind> (<reason>) but does not go through the gate.
     Run instead: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" <kind> <session> <segment>
     <session> = the name in your brief; no name -> ask the lead. Exit 75 = skipped by the gate (NO WINDOW), not a red run.
     hook: <значение $0>
     ```
     Строка `hook:` отвечает на открытый вопрос: из какого дерева сработал хук у субагента в worktree.
  5. Регистрация в `settings.json` — **последней правкой**, после зелёных тестов хука.
  6. `ruff check -q` на тестовом файле, `bash -n` на обоих скриптах; LF хука — строкой в `.gitattributes` (файл 6),
     проверка `git check-attr eol -- <хук>` → `eol: lf` (`git ls-files --eol` до `git add` пуст); иначе хук мёртв на Windows.

#### Task 1.1 — тесты и приёмка

- **REDS (тестер, `scripts/machine_gate_tests/test_machine_gate_hook.py`):** 10 функций, стражи `test_gate_light_file_runs_without_window`
  и `test_gate_call_form_compat` (K1–K7) — classification.md §9 (вынесено по бюджету 32 КБ); таблицы — §2, §7.
- **Acceptance criteria (литерально, всё на temp-замке через `MACHINE_LOCK_DIR=<tmp_path.as_posix()>`):**
  - замок с чужим окном (`window: other-s | heavy | x | until ~23:59`), хук на `pytest multiprocess_framework/modules`
    → код 2, stderr содержит `BLOCKED by machine-gate-guard` и `machine_gate.sh" heavy <session> pytest multiprocess_framework/modules`;
  - тот же замок, хук на `pytest Services/robot_comm/tests` → код 2, `machine_gate.sh" medium <session> pytest Services/robot_comm/tests`;
  - тот же замок, `bash ".../scripts/machine_gate.sh" heavy s1 pytest -q` → код 0, stderr пуст;
  - замка нет, команда C9 → код 0, stderr пуст (`test_hook_allows[no_lock]`); N1–N8 при живом замке → код 0;
  - `machine_gate.sh light s1 python -m pytest --version` без окна `s1` → код 75 и строка `reclassified light -> heavy (pytest_no_file_args)`;
  - G1–G12, T1–T14, R1–R4 и K1–K7 (classification.md §7) — дословно по таблицам;
  - живая проба P1 (раздел «Пайплайн», после слияния) — хук блокирует команду субагента в worktree,
    в отчёте — строка `hook:` и `CLAUDE_PROJECT_DIR`.
- **Out of scope:** MCP-инструмент `mcp__qex__index_codebase` (не Bash; см. вопрос 3); обход через `bash -c "…"`,
  `eval`, переменные — хук не граница безопасности; правка `lint_settings.py` (`REQUIRED_HOOKS`); e2e-серии и
  `scripts/stand_gate` в живом режиме — у них нет устойчивого имени команды, их класс задаёт заявка агента;
  вид окна `medium` (грамматика замка — Task 1.2); проверка RAM гейтом; флаг `--plain`; правка skill и
  project-rules (пайплайн, п. 7).
- **TRAPS:** classification.md §9.

### Task 1.2 — `grant` / `close` / `status` и проверка формата замка [PENDING] (после 1.1: тот же `machine_gate.sh`)
- **Level:** Middle · **Assignee:** `developer` (Sonnet); тесты — `tester` вслепую до кода
- **Module contract:** n/a
- **Handoff:** `tester`(RED) → `developer`(GREEN) → `reviewer`
- **Gate:** RED тестера → GREEN (гейт `light`, один файл); `bash -n scripts/machine_gate.sh`; `ruff check -q`; `cmp` двух
  SKILL.md; инъекции J записаны с фактом; reviewer APPROVED по SHA.
- **Goal:** координатор меняет замок одной командой с проверкой формата; битый замок никогда не превращается
  в тихий пропуск 75; `status` даёт числа нагрузки без ручного замера.
- **Files:**
  1. `scripts/machine_gate.sh`
  2. `scripts/machine_gate_tests/test_machine_gate_lock.py` — пишет `tester`
  3. `.claude/skills/coordinator/SKILL.md` и 4. `.claude/plugins/dev/skills/coordinator/SKILL.md` — только
     указатель на подкоманды в §2 (одна-две строки, оба файла байт в байт одинаковы)
- **Грамматика замка (валидатор `validate_lock`):** `\r` в конце строки отбрасывается; пустые строки
  допустимы; разделитель полей ` | `; `<name>` = `[A-Za-z0-9._-]+`; `<kind>` ∈ {`quiet`,`heavy`,`stand`}.
  - `coordinator: <name> | since <текст>` — ровно 2 поля, ровно одна такая строка;
  - `window: <name> | <kind> | <что> | until ~<текст>` — 4 поля, не больше одной строки;
  - `waiting: <name> | <kind> | <что> | <текст>` — 4 поля, сколько угодно;
  - `stand: <непустой текст>`;
  - любая другая строка — ошибка.
  Ошибка → stderr `machine_gate: malformed machine.lock:<N>: <строка>`, код **2**.
  Пометка (Task 1.1): `medium` — класс команды, а не вид окна; грамматика замка и `kind` окна (`quiet|heavy|stand`) не меняются; режим гейта `medium` проверяет замок так же, как `heavy|light`.
- **Подкоманды:**
  - `heavy|light <session> <cmd…>` — если замок есть, сначала `validate_lock` (битый → 2, команда не запускается).
  - `grant <coordinator> <session> <kind> <minutes> <что…>` — замок обязан быть и пройти проверку;
    `<coordinator>` = имя в строке `coordinator:`; окна нет; `minutes` — целое 1..600; в `<что>` нет `|`.
    Пишет `window: <session> | <kind> | <что> | until ~HH:MM` (`date -d "+N minutes" +%H:%M`) сразу после строки
    `coordinator:`, удаляет строки `waiting: <session> | …`, остальные строки сохраняет в прежнем порядке.
    Запись атомарная: `machine.lock.tmp` в той же папке → `mv`. Любой отказ → код 2, файл байт в байт прежний.
  - `close <coordinator> <session>` — удаляет строку `window:` этой сессии; окно чужое или его нет → код 2.
  - `status` — печатает содержимое замка (или `machine.lock: none`), затем `ram_free_mb: <целое>` и
    `cpu_load_pct: <целое>`. Источник: один вызов `powershell -NoProfile -Command`:
    `Win32_OperatingSystem.FreePhysicalMemory` (КБ → МБ) и `Win32_Processor.LoadPercentage`, среднее пяти
    замеров через 1 с (skill §3 требует 5-секундную выборку). powershell нет → `n/a`. Код 0.
- **Steps (developer):** красный прогон → `validate_lock` → вызов в `heavy|light` → `grant`/`close` →
  `status` → указатель в обоих SKILL.md (`.claude/skills/coordinator/SKILL.md` §2, строка «Rewrite the whole file…»
  дополняется: «or `machine_gate.sh grant|close` — validates the format; `status` prints the lock with free RAM and CPU»)
  → `cmp` двух SKILL.md → `bash -n`.
- **REDS (`scripts/machine_gate_tests/test_machine_gate_lock.py`):**
  1. `test_grant_writes_window_and_drops_waiting` — замок `coordinator: c1 | since x` / `waiting: s2 | heavy | a | ~3 min` /
     `waiting: s3 | heavy | b | ~80 min` / `stand: free`; `grant c1 s2 heavy 20 T3.9 tests` → код 0; строки ровно:
     `coordinator: c1 | since x`, `window: s2 | heavy | T3.9 tests | until ~HH:MM` (regex `\d\d:\d\d`),
     `waiting: s3 | heavy | b | ~80 min`, `stand: free`
  2. `test_grant_refuses` (параметры: `second_window`, `non_coordinator` — `grant s9 …`, `bad_kind` — `fast`,
     `bad_minutes` — `0`, `no_lock`) → код 2, файл неизменен (сравнение байтов)
  3. `test_close_removes_own_window` → код 0, строки `window:` нет, прочее на месте
  4. `test_close_refuses_foreign_window` → код 2, файл неизменен
  5. `test_malformed_lock_exit_2` (замки: `window:s2 | heavy` без пробела; `windw: …`; две строки `window:`;
     `window: s2 | fast | x | until ~1`; нет строки `coordinator:`; `window` с 3 полями; режимы `heavy s2 echo RAN`,
     `light s2 echo RAN`, `grant c1 s2 heavy 5 x`) → код 2, stderr содержит `malformed machine.lock:`, `RAN` в stdout нет
  6. `test_status_prints_lock_and_metrics` (с замком и без) → код 0, есть строки `ram_free_mb: \d+|n/a` и `cpu_load_pct: \d+|n/a`;
     с замком — его строки на месте; без — `machine.lock: none`
  Стражи: `test_live_sample_lock_is_valid` — дословный живой замок 2026-10-13:
  ```
  coordinator: inspector-bottles-84 | since 2026-10-13 12:00
  waiting: inspector-bottles-3e | heavy | T3.9 post-merge Services/robot_comm/tests on main (after owner's word in its session) | ~3 min
  waiting: inspector-bottles-a4 | heavy | qex full reindex — only after the .ignore cause is found, evening | ~80 min
  stand: free
  ```
  `heavy inspector-bottles-3e echo RAN` → код 75 (проверка формата пройдена, окна нет);
  `test_crlf_lock_is_valid` — тот же замок с `\r\n` → тоже 75, не 2.
- **Acceptance criteria:** все REDS зелёные, стражи зелёные; ручная проверка лидом на temp-замке:
  `MACHINE_LOCK_DIR=<tmp> bash scripts/machine_gate.sh status` печатает два числа; битый замок → `echo $?` = `2`.
- **Out of scope:** подкоманда `wait`/постановка в очередь; вердикт допуска по порогам (координатор судит
  по числам сам); правка текста skill `coordinator` сверх указателя; любой демон или служба; проверка, что
  `grant` зовёт именно сессия-координатор (имя сверяется, личность — нет).

## Пайплайн (по `.claude/CLAUDE.md` «Task launch convention»; здесь — только специфика)

Режим песочницы A: один писатель, ветка `feat/tooling-machine-gate-hook`, задачи строго по очереди (1.1 → 1.2).
Все прогоны — через гейт `light <session>` с перечислением файлов, например:
`bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> python -m pytest -q --tb=short scripts/machine_gate_tests/test_machine_gate_hook.py`.
Имя `<session>` лид даёт в каждом брифе.

1. **Ревьюер плана** (`reviewer`, `MODE: plan`, opus) → владелец: approve и ответы на вопросы ниже.
2. **Тестер вслепую до кода** (`tester`, sonnet) — по одной задаче. Читать можно: этот план, classification.md,
   `scripts/atlas/tests/test_lint_brief_1_9c.py` (только `_git_bash`), skill `coordinator` §2.
   **Запрещено читать:** `scripts/machine_gate.sh`, `.claude/plugins/dev/hooks/machine-gate-guard.sh`,
   `git log -p`/`git show` по этим путям, рабочую копию разработчика. Ожидаемые значения — литералы из таблиц плана.
   Итог — красный прогон с выводом; коммит делает лид.
3. **Разработчик** (`developer`, sonnet) — FILES выше, первая правка в первых 5 вызовах, тесты тестера не правит
   (расхождение с планом → вопрос лиду). Сообщение коммита — в файл, коммитит лид.
4. **Инъекции — предсказание до прогона** (лид; каждая — `light` прогон одного файла): таблица I1–I7 (хук,
   `classify`), M1–M18 (`medium`, `timed`), J1–J5 (Task 1.2) — classification.md §8 (вынесена по бюджету 32 КБ).

5. **Ревьюер кода** (`reviewer`, opus) — по зафиксированному SHA (`git diff <base>..<sha>`), получает зелёный
   вывод pre-report gate и таблицу инъекций; смотрит семантику: ложные срабатывания на обычных командах,
   fail-open, атомарность записи, CR.
6. **Живая проба P1** (лид, после слияния в `main`, пока лежит живой `machine.lock`): субагент `haiku` с
   `isolation: "worktree"` выполняет ровно `python -m pytest --version` (безвредно, если хук не сработал)
   и `echo "$CLAUDE_PROJECT_DIR"; pwd`, возвращает вывод и код дословно. Ожидание: блок, в stderr
   `BLOCKED by machine-gate-guard`; строка `hook:` показывает, из какого дерева запущен хук. Результат —
   ответ на открытый вопрос ревью; записать в `docs/claude/OPEN_QUESTIONS.md` или в урок памяти.
7. **Post-merge, лид** (не код Task 1.1; после слияния 1.1 в `main`): правка в исходнике плагина, затем побайтная
   копия и `cmp`. (а) skill `coordinator` §3 — строка `medium`: один каталог `*/tests`, ~2–5 мин, без окна; блок —
   чужое `quiet`/`stand`; timed (список `scripts/machine_gate_timed.txt` или `--timed`) — только в своём окне.
   (б) `project-rules` §8 — `[--timed] heavy|medium|light` и одна фраза про `medium`/timed. (в) `.claude/CLAUDE.md`
   «Shared machine» — то же. Файлы: `.claude/plugins/dev/skills/{coordinator,project-rules}/SKILL.md`
   → `.claude/skills/{coordinator,project-rules}/SKILL.md`. Регистрацию хука в `settings.json` в `main` — только по
   слову владельца и после предупреждения полос.

## Бюджет

Тестер 1.1 — мягкий 120k / жёсткий 200k; разработчик 1.1 — 150k / 250k; тестер 1.2 — 100k / 170k;
разработчик 1.2 — 120k / 200k. Ревьюер плана и два ревью кода — до 120k каждый. Итого порядка 0.9–1.4M токенов.

## Риски и ограничения

- **Хук общий для всех сессий основного дерева.** После слияния он начнёт блокировать голые `pytest`
  во всех полосах, пока лежит замок. Это и есть цель, но координатора надо предупредить до слияния,
  чтобы полосы не приняли блок за поломку. Ложное срабатывание на не-тестовой команде мешает всем —
  поэтому негативные случаи N1–N8 в тестах обязательны.
- **Worktree, вырезанный до слияния.** Если окажется, что у субагента в worktree `CLAUDE_PROJECT_DIR` указывает
  на сам worktree, в старых worktree файла хука нет. Тогда bash выдаст «No such file», это неблокирующая ошибка
  хука, и команда пройдёт. REDS #6 (`test_hook_independent_of_cwd`) это не ловит — он лишь имитирует другой cwd.
  Настоящее доказательство — только проба P1.
- **Эвристика по тексту команды.** `bash -c`, переменные, алиасы её обходят. Для координации этого достаточно,
  граница безопасности — не здесь.
- **Форма ≠ длительность.** `medium` = один каталог `*/tests`, но `multiprocess_framework/modules/process_module/tests`
  (252 файла) может идти > 5 мин; класс тогда поднимает сама сессия (`heavy`). Не-timed `medium` без предела
  числа: параллельность держит только RAM-допуск координатора.

## Смежное

- Skill `coordinator` §2, §7: план даёт ему механизм; skill получает только указатель на `grant|close|status`.
- `scripts/stand_gate` и запасной протокол `stand.lock` в гейте — не меняются.
- Урок `docs/claude/memory/feedback_a_hook_dead_on_windows_by_a_trailing_cr.md` — основание для LF-проверки и
  `tr -d '\r'`; урок `feedback_protect_branch_blocks_worktree_subagents.md` — основание для пробы P1
  (хук протект-ветки видит cwd основного дерева, а не worktree).
- `plans/queue/ORDER.md`: смежного плана нет; строку в очередь ставит лид при регистрации плана.

## Открытые вопросы владельцу

1. **Блокировать ли голый лёгкий pytest** (один тестовый файл) при живом замке? План: да — это буква §8
   («every test command goes through the gate»), и только так закрывается чужое окно `quiet`.
   Альтернатива: блокировать лёгкое только при окне `quiet`. Рекомендация: да, блокировать всё.
2. ~~Каталог тестов = тяжёлое?~~ **Закрыт** — ответ 2 ниже: третий класс `medium` (Task 1.1, classification.md).
3. **`mcp__qex__index_codebase`** (индексация через MCP, не Bash) хук не ловит. Нужен ли отдельный matcher
   (при живом замке — всегда блок с подсказкой «окно у координатора»)? Рекомендация: нет сейчас; индексирует
   только лид, и он знает про окно.

### Ответы владельца (2026-10-13, записал координатор inspector-bottles-b4)

1. **Да, блокировать всё:** любой pytest мимо `machine_gate.sh` при живом замке — блок с подсказкой.
2. **Третий класс — `medium`** (предложение владельца): `heavy` — то, что идёт **дольше ~5 мин**. Итого три класса:
   `light` — свои файлы, < ~2 мин; `medium` — ~2–5 мин (пример: каталог `*/tests` одного модуля);
   `heavy` — > ~5 мин (полный прогон, матрица, слепой tester с sim, e2e-серия, стенд, индексация qex).
   Хук не знает длительность заранее и классифицирует по форме команды: файлы → `light`, один каталог модуля →
   `medium`, несколько модулей / весь набор / `run_framework_tests.py` / матрица → `heavy`; сессия может поднять класс
   сама, но не понизить. **Допуск `medium` (предложение координатора, владелец подтвердил 2026-10-13):** без окна;
   блокируется чужим окном `quiet` или `stand` (там замеры), при чужом `heavy` разрешён, но не больше одного `medium` за раз.
   Затрагивает `scripts/machine_gate.sh` (третий аргумент класса), skill `coordinator` §3 и project-rules §8 —
   правка в задачах этого плана, не отдельно.
   **Решение координатора inspector-bottles-b4 по поручению владельца («как лучше и правильнее»), 2026-10-13:** слот «один `medium` за раз» отменён; `medium` с путём из
   `scripts/machine_gate_timed.txt` или с `--timed` (timed) допускается как `heavy` — classification.md §5, §6.
3. **Нет сейчас:** отдельный matcher на `mcp__qex__index_codebase` не нужен.
