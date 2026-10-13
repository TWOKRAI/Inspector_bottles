# Plan: гейт машины как механизм — хук PreToolUse и подкоманды machine_gate.sh

- **Slug:** tooling-machine-gate-hook
- **Дата:** 2026-10-13
- **Статус:** DRAFT
- **Ветка:** (заполняется после approve; предлагается `feat/tooling-machine-gate-hook`)
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
  Её вызывают и хук, и сам гейт в режимах `heavy|light`. Второй копии правил нет.
- **Хук тонкий.** Замка нет — `exit 0` до запуска python (выключено = ноль стоимости). В сыром stdin нет
  ни одного слова-кандидата — `exit 0` до python. Только потом python достаёт `tool_input.command`,
  а решение принимает `classify`.
- **Хук блокирует любую тестовую команду мимо гейта, пока замок есть**: тяжёлую и лёгкую. Это ровно правило
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
- **Писать замок может только координатор:** `grant`/`close` первым аргументом берут имя координатора и
  сверяют его со строкой `coordinator:`. Проверка дешёвая и ловит полосу, которая пишет замок сама.

## Таблица классификации (контракт для тестов; литералы, не из кода)

Вынесена в [`2026-10-13_tooling-machine-gate-hook/classification.md`](2026-10-13_tooling-machine-gate-hook/classification.md) (бюджет размера 32 КБ). С ответом владельца о классе `medium` её правит Task 1.1.

## Порядок выполнения

### Фаза 1 — механизм

### Task 1.1 — хук PreToolUse и `classify` в гейте [PENDING]
- **Level:** Middle · **Assignee:** `developer` (Sonnet); тесты пишет `tester` вслепую до кода
- **Module contract:** n/a (инструменты, не модуль фреймворка)
- **Handoff:** `tester`(RED) → `developer`(GREEN) → `reviewer`
- **Goal:** пока `machine.lock` существует, Bash-команда с тестом или тяжёлой работой мимо `machine_gate.sh`
  блокируется с сообщением, где написана команда гейта; гейт сам переводит ложный `light` в `heavy`.
- **Files:**
  1. `.claude/plugins/dev/hooks/machine-gate-guard.sh` — новый
  2. `scripts/machine_gate.sh` — подкоманда `classify`, переклассификация в `heavy|light`
  3. `.claude/settings.json` — PreToolUse, matcher `Bash`, третьим после `protect-branch.sh`, `timeout: 10`,
     форма строки — как у соседей: `bash \"${CLAUDE_PROJECT_DIR}\"/.claude/plugins/dev/hooks/machine-gate-guard.sh`
  4. `pyproject.toml` — строка `"scripts/machine_gate_tests"` в `testpaths` с комментарием (иначе тесты молча
     не гоняются; страж `test_no_test_dir_is_invisible_to_every_runner`)
  5. `scripts/machine_gate_tests/test_machine_gate_hook.py` — пишет `tester`, developer не правит
  Нужен ещё файл — стоп и вопрос лиду.
- **Steps (developer):**
  1. Красный прогон тестов тестера (команда ниже), список красных — в отчёт.
  2. `classify` в `machine_gate.sh`: функция `classify_cmd`, режем на сегменты через `sed -E`, правила — по
     таблице выше. Ветка `classify` разбирается **до** проверки `$# -lt 3` (у неё один аргумент).
  3. Режимы `heavy|light`: после проверки `kind` вызвать `classify_cmd "$*"`; есть строка `heavy` и заявка
     `light` → `kind=heavy` и строка в stderr. Остальная логика гейта не меняется.
  4. Хук: шапка-комментарий по-русски. Порядок: (а) `lock="${MACHINE_LOCK_DIR:-/d/PROJECT_INNOTECH/Inspector_vision}/machine.lock"`,
     нет файла → `exit 0`; (б) `INPUT=$(cat)`; `grep -qE 'pytest|run_framework_tests|run_sim_all|check_injections|mutation_gate|break_inject|reindex|qex_retry'`
     не нашёл → `exit 0`; (в) python — разрешение как в `.claude/plugins/dev/hooks/lint-brief.sh`
     (`$HOOK_DIR/../../core/hooks/_lib/python-bin.sh`), нет → `exit 0`; команда — через
     `$(... | tr -d '\r')`, печать `sys.stdout.write`, **никогда** `read < <(...)` (урок про CR);
     (г) гейта нет → `exit 0`; `out=$(bash "$gate" classify "$CMD")`; пусто → `exit 0`;
     (д) иначе блок по первой строке `out`: `exit 2`, в stderr ровно три строки и строка `hook:`:
     ```
     BLOCKED by machine-gate-guard: machine.lock exists and this command is <kind> (<reason>) but does not go through the gate.
     Run instead: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" <kind> <session> <segment>
     <session> = the name in your brief; no name -> ask the lead. Exit 75 = skipped by the gate (NO WINDOW), not a red run.
     hook: <значение $0>
     ```
     Строка `hook:` отвечает на открытый вопрос: из какого дерева сработал хук у субагента в worktree.
  5. Регистрация в `settings.json` — **последней правкой**, после зелёных тестов хука.
  6. `ruff check -q` на тестовом файле, `bash -n` на обоих скриптах; файлы `.sh` — LF (проверить
     `git ls-files --eol`), иначе хук мёртв на Windows.

#### Task 1.1 — тесты и приёмка

- **REDS (тестер, `scripts/machine_gate_tests/test_machine_gate_hook.py`):**
  1. `test_classify_heavy` (параметры C1–C11, C14; проверяет kind и reason)
  2. `test_classify_light` (C12, C13)
  3. `test_classify_none` (N1–N8: пустой stdout, код 0)
  4. `test_hook_allows` (параметры: `no_lock` + C9; `wrapped` — `bash "<gate>" heavy s1 pytest -q`; `non_test` — N1;
     `bad_json` — stdin `not json`; везде замок с чужим окном, кроме `no_lock`) → код 0, stderr пуст
  5. `test_hook_blocks` (параметры: C10 → в stderr `BLOCKED by machine-gate-guard` и
     `machine_gate.sh" heavy <session> python -m pytest multiprocess_framework/modules`; C12 → `machine_gate.sh" light <session>`) → код 2
  6. `test_hook_blocks_unwrapped_segment_after_wrapped` — `bash "<gate>" light s1 pytest a/tests/test_x.py && pytest -q` → код 2
  7. `test_hook_independent_of_cwd` — cwd = `tmp_path` вне git, `CLAUDE_PROJECT_DIR=tmp_path`, команда C9 → код 2
  8. `test_gate_reclassifies_light_to_heavy` (параметры: `python <tmp>/run_framework_tests.py`, где файл — заглушка
     `print("FAKE")`; `python -m pytest --version`), замок без окна `s1`, `light s1 …` → код 75, stdout содержит
     `NO WINDOW`, stderr содержит `reclassified light -> heavy`, `FAKE` в stdout **нет**
  9. `test_hook_registered_in_settings` — в `.claude/settings.json`, PreToolUse, matcher `Bash`, есть команда
     с `machine-gate-guard.sh`
  Стражи (зелёные и до правки): `test_gate_heavy_claim_not_downgraded` (окно `s1`, `heavy s1 python -c "import sys; sys.exit(3)"` → код 3);
  `test_gate_light_file_runs_without_window` (замок без окна, без `quiet`; `light s1 python -m pytest -q <tmp>/test_ok.py` → код 0).
- **Acceptance criteria (литерально, всё на temp-замке через `MACHINE_LOCK_DIR=<tmp_path.as_posix()>`):**
  - замок с чужим окном (`window: other-s | heavy | x | until ~23:59`), хук на `pytest multiprocess_framework/modules`
    → код 2, stderr содержит `BLOCKED by machine-gate-guard` и `machine_gate.sh" heavy <session> pytest multiprocess_framework/modules`;
  - тот же замок, `bash ".../scripts/machine_gate.sh" heavy s1 pytest -q` → код 0, stderr пуст;
  - замка нет → код 0, stderr пуст, на любой команде из таблицы;
  - N1–N8 при живом замке → код 0;
  - `machine_gate.sh light s1 python -m pytest --version` без окна `s1` → код 75 и строка `reclassified light -> heavy (pytest_no_file_args)`;
  - живая проба P1 (раздел «Пайплайн», после слияния) — хук блокирует команду субагента в worktree,
    в отчёте — строка `hook:` и `CLAUDE_PROJECT_DIR`.
- **Out of scope:** MCP-инструмент `mcp__qex__index_codebase` (не Bash; см. вопрос 3); обход через `bash -c "…"`,
  `eval`, переменные — хук не граница безопасности; правка `lint_settings.py` (`REQUIRED_HOOKS`); e2e-серии и
  `scripts/stand_gate` в живом режиме — у них нет устойчивого имени команды, их класс задаёт заявка агента.
- **TRAPS:** пути temp-замка передавать как `tmp_path.as_posix()`; bash на Windows — помощник `_git_bash()` из
  `scripts/atlas/tests/test_lint_brief_1_9c.py:982` **скопировать** в тест, не импортировать; ни один тест не
  трогает живой `D:\PROJECT_INNOTECH\Inspector_vision\machine.lock` (всегда `MACHINE_LOCK_DIR`); тестер перечисляет
  файлы, а не каталог, иначе его же прогон классифицируется `heavy`.

### Task 1.2 — `grant` / `close` / `status` и проверка формата замка [PENDING] (после 1.1: тот же `machine_gate.sh`)
- **Level:** Middle · **Assignee:** `developer` (Sonnet); тесты — `tester` вслепую до кода
- **Module contract:** n/a
- **Handoff:** `tester`(RED) → `developer`(GREEN) → `reviewer`
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
2. **Тестер вслепую до кода** (`tester`, sonnet) — по одной задаче. Читать можно: этот план,
   `scripts/atlas/tests/test_lint_brief_1_9c.py` (только `_git_bash`), skill `coordinator` §2.
   **Запрещено читать:** `scripts/machine_gate.sh`, `.claude/plugins/dev/hooks/machine-gate-guard.sh`,
   `git log -p`/`git show` по этим путям, рабочую копию разработчика. Ожидаемые значения — литералы из таблиц плана.
   Итог — красный прогон с выводом; коммит делает лид.
3. **Разработчик** (`developer`, sonnet) — FILES выше, первая правка в первых 5 вызовах, тесты тестера не правит
   (расхождение с планом → вопрос лиду). Сообщение коммита — в файл, коммитит лид.
4. **Инъекции — предсказание до прогона** (лид, записать в план до запуска; каждая — `light` прогон одного файла):

   | ID | Поломка | Предсказанные красные |
   |---|---|---|
   | I1 | хук: проверка замка инвертирована (`exit 0` при наличии замка) | `test_hook_blocks`, `test_hook_blocks_unwrapped_segment_after_wrapped`, `test_hook_independent_of_cwd` |
   | I2 | `classify`: удалено правило `-n` | `test_classify_heavy[C11]` |
   | I3 | `classify`: снята привязка к позиции команды | `test_classify_none` (N1, N2, N3, N6, N7 минимум), `test_hook_allows[non_test]` |
   | I4 | хук: «обёрнуто», если `machine_gate.sh` есть где угодно в строке (не по сегментам) | `test_hook_blocks_unwrapped_segment_after_wrapped` |
   | I5 | гейт: убрана переклассификация `light → heavy` | `test_gate_reclassifies_light_to_heavy` (оба) |
   | I6 | хук: убран `tr -d '\r'` | предсказание: **может остаться зелёным** (`[[:space:]]` съедает `\r`); если зелёное — записать как необнаруженную и объяснить, не выдумывать тест под неё |
   | J1 | `validate_lock` всегда успешен | `test_malformed_lock_exit_2` (все) |
   | J2 | `grant` не проверяет существующее окно | `test_grant_refuses[second_window]` |
   | J3 | `close` удаляет любое окно | `test_close_refuses_foreign_window` |
   | J4 | `grant` не удаляет `waiting:` своей сессии | `test_grant_writes_window_and_drops_waiting` |
   | J5 | `validate_lock` не отбрасывает `\r` | `test_crlf_lock_is_valid` |

5. **Ревьюер кода** (`reviewer`, opus) — по зафиксированному SHA (`git diff <base>..<sha>`), получает зелёный
   вывод pre-report gate и таблицу инъекций; смотрит семантику: ложные срабатывания на обычных командах,
   fail-open, атомарность записи, CR.
6. **Живая проба P1** (лид, после слияния в `main`, пока лежит живой `machine.lock`): субагент `haiku` с
   `isolation: "worktree"` выполняет ровно `python -m pytest --version` (безвредно, если хук не сработал)
   и `echo "$CLAUDE_PROJECT_DIR"; pwd`, возвращает вывод и код дословно. Ожидание: блок, в stderr
   `BLOCKED by machine-gate-guard`; строка `hook:` показывает, из какого дерева запущен хук. Результат —
   ответ на открытый вопрос ревью; записать в `docs/claude/OPEN_QUESTIONS.md` или в урок памяти.

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
  хука, и команда пройдёт. Тест H7 (`test_hook_independent_of_cwd`) это не ловит — он лишь имитирует другой cwd.
  Настоящее доказательство — только проба P1.
- **Эвристика по тексту команды.** `bash -c`, переменные, алиасы её обходят. Для координации этого достаточно,
  граница безопасности — не здесь.
- **Строгость `light`.** `pytest <каталог тестов модуля>` считается тяжёлым — см. вопрос 2.

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
2. **Каталог тестов = тяжёлое?** План: `pytest Services/robot_comm/tests` → `heavy` (правило «один процесс по
   своим **файлам**»). Альтернатива: каталог `*/tests` одного модуля считать лёгким. Рекомендация: строго, как в плане.
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
3. **Нет сейчас:** отдельный matcher на `mcp__qex__index_codebase` не нужен.
