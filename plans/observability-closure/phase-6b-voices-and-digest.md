# Ф6 (продолжение) — голоса мимо журнала, консоль процесса, сводка, шум, приёмка

> Начало фазы, правила, граница и пересечение с полосой Ж — [`phase-6-nothing-bypasses.md`](./phase-6-nothing-bypasses.md).

### Task 6.5 — Инвентарь голосов мимо журнала и таблица «куда что»

**Level:** Senior · **Assignee:** teamlead (подшаг инвентаря — haiku) · **Layer:** framework + prototype + Services · **Module contract:** n/a · **[PENDING]**
- **Handoff:** haiku(инвентарь по точным командам) -> teamlead(классификация) -> reviewer(express)

**Goal:** перечислить каждый путь в рантайм-коде, который пишет в stdout/stderr мимо `LoggerCore`, и для каждого решить адрес.
Классы адресов:
(а) журнал процесса — через вид `get_std_logger`;
(б) журнал лаунчера;
(в) аварийный выход — остаётся в stderr, ловит перехват 6.8; только отказ самого писателя, правило «один писатель»;
(г) CLI-инструмент — печать по назначению.
Замер на 2026-10-13 (`git grep -F "print("` без tests/tools/scripts/examples): фреймворк — 134 строки в 37 файлах,
прототип — 56 в 25, Services — 113 в 22. Плюс пути `emergency_log`: по уроку памяти
`project_emergency_log_is_stderr_only.md` они доезжают только до stderr.

**Files:**
- `plans/observability-closure/inventory-voices-bypass.md` — новый отчёт: таблица `файл:строка | текст | поток | класс | задача`

**Acceptance criteria:**
- [ ] Инвентарь считан `git grep -F` по всем написаниям: `print(`, `sys.stderr.write`, `sys.stdout.write`, `emergency_log(`, `_fallback_log(`, `traceback.print_exc`. Команды и итоги — в отчёте.
- [ ] Каждая строка из R-21 найдена в таблице с классом: ретеншен (`log_channel.py:497-511`), «приёмники не приняли» (`channel_routing_manager.py:479`), `[launch] … дубль из pipeline пропущен` (`launch.py:163`), шапка запуска (`launch.py:790`), `announce_presentation_absent` (`launch.py:306`).
- [ ] Строки класса (а)/(б) распределены по задачам 6.6 и 6.7; строки класса (в) перечислены как вход для 6.8.

**Out of scope:** правка кода.

---

### Task 6.6 — Голоса запуска прототипа — в журнал лаунчера (включая R-14)

**Level:** Middle+ · **Assignee:** developer · **Layer:** prototype · **Module contract:** impl-only · **[PENDING]** (после 6.5)
- **Handoff:** developer(REDS в брифе: красный прогон до правки, инъекция) -> reviewer

**Goal:** строки класса (б) из 6.5 в `multiprocess_prototype/backend/launch.py` и `multiprocess_prototype/main.py` идут
в журнал лаунчера (`logs/<run>/launcher/*.log`) через вид. Копия в консоль сохраняется: оператор её видит.
Сюда входит R-14 (`announce_presentation_absent`, `launch.py:219-306`) — это исполнение Task 4.18. Зависимость 4.18
от 4.17 снимается: вид уже буферизует и сливает в файл (урок `feedback_emergency_log_reaches_stderr_not_the_log_files.md`).
Решение — развилка О-3.

**Files:**
- `multiprocess_prototype/backend/launch.py` — `announce_presentation_absent`, сборка фундамента (`:163`), шапка (`:790`), ошибки валидации (`:723-725`), «топология не найдена» (`:131`)
- `multiprocess_prototype/main.py` — `:145`, `:148`
- `multiprocess_prototype/backend/tests/test_launch_voices.py` — новый

**Acceptance criteria:**
- [ ] Каждая строка из списка Files: запуск → строка есть в `launcher/system.log` (или в файле уровня), `rg -uu` по каталогу журнала находит её.
- [ ] Строка по-прежнему видна в консоли запуска.
- [ ] Инъекция: вернуть `print` в одну функцию → её тест краснеет.

**Out of scope:** строки фреймворка (6.7); `print` в CLI-обёртках `run.py` / `frontend/run.py` до venv-переключения — класс (г).

---

### Task 6.7 — Голоса о самом логировании — в файлы процесса, а не только в stderr

**Level:** Senior · **Assignee:** teamlead · **Layer:** framework · **Module contract:** impl-only · **[PENDING]** (после 6.1, 6.5)
- **Handoff:** tester(RED, слепой) -> teamlead(GREEN) -> reviewer

**Goal:** ретеншен (`_warn_retention_failure`, `log_channel.py:497`) и «приёмники не приняли» (`ChannelRoutingManager`, `:466-484`)
сегодня идут через `emergency_log` / `_fallback_log` → только stderr: 0 вхождений в `logs/prototype_2` (R-21).
Это не отказ писателя, поэтому исключение «аварийный выход» к ним не относится. Они идут записью
через `LoggerCore` в файлы процесса; `emergency_log` остаётся только запасной дорогой, если писатель погашен.
Голос «приёмники не приняли» звучит на останове (`shutdown`) — каналы в этот момент закрываются, и порядок надо
согласовать с шаблоном Ж 1.2b-2. **Согласовать с полосой Ж:** `ChannelRoutingManager.shutdown` (`:486`) → `_on_shutdown`.

**Files:**
- `multiprocess_framework/modules/logger_module/channels/log_channel.py` — `_warn_retention_failure`, `_warn`
- `multiprocess_framework/modules/channel_routing_module/core/channel_routing_manager.py` — `_warn_idle_sinks` (имя проверить, `:466`), `_fallback_log`
- `multiprocess_framework/modules/_fallback.py` — только если ADR требует нового входа; иначе не трогать
- `multiprocess_framework/modules/logger_module/tests/test_logging_self_voices.py` — новый
- `multiprocess_framework/modules/logger_module/DECISIONS.md` — поправка к ADR об аварийном выходе

**Acceptance criteria:**
- [ ] Сбой удаления при ретеншене → строка в файле процесса (`warnings.log` или `system.log`) и в `observability.db`.
- [ ] «Приёмники не приняли» на останове → строка в файле процесса до закрытия каналов.
- [ ] Писатель погашен → голос уходит в stderr через `emergency_log` (запасная дорога жива; инъекция «убрать запасную» → тест красный).

**Out of scope:** сами причины шума (6.10) и ретеншена (6.11).

---

### Task 6.8 — Каждый процесс сохраняет свою консоль: сырой stderr, нативные библиотеки, ранние traceback

**Level:** Senior+ · **Assignee:** teamlead · **Layer:** framework · **Module contract:** public-api-change (ручка схемы) · **[PENDING]** (после 6.1, 6.5)
- **Handoff:** teamlead(INTERFACE + ADR) -> tester(RED) -> teamlead(GREEN) -> reviewer; лид — инъекции, стенд

**Goal:** любой запуск, а не только стенд-скрипт, оставляет консоль каждого процесса в `<log_dir>/<процесс>/console.log`.
Сюда попадают: stderr нативных библиотек (ffmpeg `Error number -138`, Qt), traceback до старта логгера, класс (в) из 6.5.
Перехват — на уровне fd 1/2 при старте процесса, до логгера: `os.dup2` в трубу, поток-читатель пишет файл
и передаёт строку в исходную консоль через поток-писатель 6.1 с дропом. Замёрзшая консоль не блокирует процесс.

**Files:**
- `multiprocess_framework/modules/logger_module/core/console_capture.py` — новый
- `multiprocess_framework/modules/process_manager_module/runner/process_runner.py` — `run_process_function`: поднять перехват первым шагом. **Согласовать с полосой Ж** (`_run_lifecycle`, `run_process_function` — область 1.2a/1.2b)
- `multiprocess_framework/modules/logger_module/configs/logger_manager_config.py` — ручка `console_capture`
- `multiprocess_framework/modules/logger_module/tests/test_console_capture.py` — новый
- `multiprocess_framework/modules/logger_module/DECISIONS.md`

**Design (развилки — О-4):**
1. Петля: консольный сток 6.1 пишет в сохранённый дескриптор исходной консоли, а не в fd 2. Иначе запись журнала
   вернулась бы в трубу перехвата.
2. Сырые строки stderr становятся записями журнала (`module="stderr"`, уровень — решает О-4) или только файлом `console.log`.
   Записи дают их в `observability.db` и в сводку 6.9; файл проще и не трогает писателя.
3. Лаунчер (родитель) тоже перехватывает себя. Дети `spawn` на Windows наследуют std-дескрипторы родителя —
   поэтому до первого ребёнка проверить, чей вывод куда попадает. Проверка запуском, не чтением.

**Acceptance criteria:**
- [ ] Ребёнок пишет в fd 2 из C-кода (тест: `os.write(2, ...)`) → строка в его `console.log`.
- [ ] Исключение до `LoggerCore` в ребёнке → traceback в `console.log`.
- [ ] Консоль заморожена → процесс не блокируется на записи в stderr (тест с дедлайном, как в 6.1).
- [ ] `console_capture: off` → fd не тронуты; цена — ноль потоков.
- [ ] Стенд: ffmpeg `Error number -138` есть в `console.log` процесса камеры.

**Out of scope:** тройник стенда (6.4) остаётся как запасной путь до приёмки этой задачи.

---

### Task 6.9 — Сводка журналов после прогона: новые шаблоны и скачки

**Level:** Middle+ · **Assignee:** developer · **Layer:** tooling · **Module contract:** new-lite · **[PENDING]** — независима, можно после 6.4
- **Handoff:** tester(RED, слепой, по критериям) -> developer(GREEN) -> reviewer

**Goal:** одна команда после прогона: `python -m scripts.log_digest <каталог журналов> [--console data/logs/console] [--db <observability.db>] [--baseline <json>] [--update-baseline]`.
Берёт WARNING/ERROR/CRITICAL из `*.log`, файлов консоли и (опционально) таблицы `records` из `observability.db`
(`observability_store.py:244`). Строку сводит к шаблону: маски для чисел, hex, путей, pid, uuid, времени, строк
в кавычках. Считает по шаблону и процессу, сравнивает с базой известных шаблонов и печатает НОВЫЕ шаблоны и скачки
(рост > ×K, K — флаг). Вывод — текст и `--json`. Пользователи — агенты и владелец.

**Files:**
- `scripts/log_digest/__init__.py`, `scripts/log_digest/__main__.py`, `scripts/log_digest/digest.py`
- `scripts/log_digest/README.md`
- `scripts/log_digest/tests/test_digest.py`
- `scripts/log_digest/baseline/prototype.json` — база, снятая со стенда 6.14

**Design:** файлы обходит своим кодом (`os.walk`), не `rg`: корневой `.ignore` прячет `*.log` и `logs/` от rg (Task 6.13).
Кодировка — UTF-8 с `errors="replace"`; число заменённых байтов — в вывод. Только stdlib.

**Acceptance criteria:**
- [ ] Две строки с разными числами/путями/pid дают один шаблон; две строки с разным текстом — два.
- [ ] База из прогона A, прогон B с одной новой строкой → в выводе ровно 1 NEW; шаблон с ростом ×3 при K=2 → 1 скачок.
- [ ] `logs/prototype_2` на стенде 2026-10-13: в выводе есть `liveness-fallback` (R-15), `protected 'devices'`, ретеншен (из консоли).
- [ ] Код выхода: 0 — нет NEW; 1 — есть NEW или скачки; 2 — ошибка входа.

**Out of scope:** живой хвост (это `observability_tail`); правки журналов.

---

### Task 6.10 — Шум по причине, а не по уровню (R-20)

**Level:** Middle+ · **Assignee:** developer · **Layer:** framework + prototype config · **Module contract:** impl-only · **[PENDING]**
- **Handoff:** developer(REDS в брифе) -> reviewer

**Goal:** убрать причины двух шумных голосов; уровни не понижать.
(а) `heartbeat: Частота метрик ограничена телеметрийным тиком 5.0с` (`process_heartbeat.py:430-442`) — по строке на процесс на старт
и на смену. Причина — `interval_sec` метрик меньше тика. Согласовать дефолты: найти источник `interval_sec=1.0`
у прототипа и фреймворка и либо поднять его до тика, либо считать интервал от тика.
(б) «приёмники не приняли» — 16 строк на смену. `gui_file` и `trace_file` объявлены в `channels` системы
(`multiprocess_prototype/backend/config/system.yaml:87-94`) и создаются в каждом процессе, хотя писатели — только в GUI.
Файлы ошибок (`critical/errors/warnings_file`) пусты законно: ошибок нет — это норма, а не дефект маршрута.
Решение: канал открывает файл лениво, по первой записи; вердикт «idle» выносится только каналам, у которых в этом
процессе есть правило маршрута, и не выносится каналам уровня ≥ WARNING.

**Files:**
- `multiprocess_framework/modules/process_module/heartbeat/process_heartbeat.py` — только если дефолт фреймворка. **Согласовать с полосой Ж**
- `multiprocess_framework/modules/channel_routing_module/core/channel_routing_manager.py` — `idle_sinks`
- `multiprocess_prototype/backend/config/system.yaml` — `observability`/`heartbeat`, `channels`
- `multiprocess_framework/modules/channel_routing_module/tests/test_idle_sinks.py` — новый или существующий

**Acceptance criteria:**
- [ ] Стенд: старт + одна смена рецепта → 0 строк «Частота метрик ограничена» (было 9 на старт), 0 строк «приёмники не приняли» о `gui_file`/`trace_file`/файлах ошибок (было 16).
- [ ] Настоящий idle (канал с правилом и без записей) голос даёт — тест.

**Out of scope:** R-15 `liveness-fallback` (план stand-recipe-switch).

---

### Task 6.11 — Ретеншен и занятые файлы лаунчера (R-18)

**Level:** Middle+ · **Assignee:** developer · **Layer:** framework · **Module contract:** impl-only · **[PENDING]**
- **Handoff:** developer(REDS: сначала воспроизведение, затем красный тест) -> reviewer

**Goal:** `PermissionError [WinError 32]` на `launcher/{critical,errors,performance,system,warnings}.log` (стенд 2026-10-13 09:04).
Гипотезы: (1) свип текущего лаунчера идёт после открытия своих файлов и пытается удалить их же;
(2) файлы держит недобитый прошлый процесс. Первый шаг — воспроизвести и назвать держателя
(`handle.exe` недоступен без прав — через запуск двух лаунчеров подряд и запуск с одним). Починка по факту:
свип не трогает файлы, открытые своими хэндлерами (реестр `acquire_shared_rotating_handler`).

**Files:**
- `multiprocess_framework/modules/logger_module/channels/log_channel.py` — свип ретеншена, `_remove_file`
- `multiprocess_framework/modules/logger_module/tests/test_retention_busy.py` — новый

**Acceptance criteria:**
- [ ] Держатель назван с доказательством (вывод запуска в отчёте).
- [ ] Свип в процессе, держащем файл, не пытается его удалить: 0 предупреждений `WinError 32` на старте стенда.
- [ ] Файл чужого живого процесса — один голос на файл (поведение `_warn_retention_failure` сохранено).

**Out of scope:** ретенция стора (`observability.db`, Task 4.14).

---

### Task 6.12 — Запись после рестарта процесса без имени процесса (R-19)

**Level:** Middle+ · **Assignee:** developer · **Layer:** framework · **Module contract:** impl-only · **[PENDING]**
- **Handoff:** developer(REDS в брифе) -> reviewer

**Goal:** `[WARNING] [-] camera_0: [health] OSError …` — первая запись `camera_0` после перезапуска сменой рецепта.
`ConsoleChannel.write` и файловый канал ставят `extra.get("proc_name") or "-"` (`log_channel.py:1015`, `:1080`).
База `proc_name` ставится в `ProcessModule.initialize`, шаг 9 (`process_module.py:300-302`). Гипотеза: запись
сделана раньше шага 9 (сервис или плагин стартует на шагах 1–8). Починка в писателе, без правки `process_module`:
`LoggerCore` берёт `proc_name` по умолчанию из `self.process.name`, пока база не задана.

**Files:**
- `multiprocess_framework/modules/logger_module/core/logger_core.py` — `set_base_context`, сборка `extra`. **Согласовать с полосой Ж** (`LoggerCore.shutdown` в кодмоде 1.2b-2; правка вне `shutdown`)
- `multiprocess_framework/modules/logger_module/tests/test_proc_name_default.py` — новый

**Acceptance criteria:**
- [ ] Воспроизведение: запись до `set_base_context` получает `[-]` (красный тест до правки, литерал `camera_0`).
- [ ] После правки — `[camera_0]`; стенд: смена рецепта → 0 записей `[-]` в `logs/<run>/**/system.log` (`rg -uu -c "\] \[-\] "`).

**Out of scope:** порядок шагов `ProcessModule.initialize` (полоса Ж).

---

### Task 6.13 — Ловушка поиска: `rg` не видит журналы

**Level:** Junior · **Assignee:** docs-writer · **Layer:** tooling docs · **Module contract:** n/a · **[PENDING]**
- **Handoff:** docs-writer -> reviewer(express)

**Goal:** записать причину и обход. **Причина найдена 2026-10-13 (менеджер, прогон):** дело не в двоичности и не
в кодировке. Корневой `.ignore` (конфиг qex, его читает и rg) содержит `**/*.log` и `**/logs/`; rg при обходе каталога
пропускает журналы. Команды и вывод:
`rg -l "liveness-fallback" logs/prototype_2` → 0 файлов (rc=1);
`rg -a -l …` → только `logs/prototype_2\observability.db` (двоичная база; `.log` по-прежнему скрыты);
`rg -uu -l …` → `ProcessManager\messages.log`, `ProcessManager\system.log`.
`rg --debug` называет правило: `ignoring logs/prototype_2\critical.log … .ignore … "**/*.log"`.
Явный путь к файлу ищется (184 вхождения в `system.log`), каталог — нет. Заметка в R-21 «искать только с `-a`» неверна:
`-a` нашёл базу, а не журналы. Тот же фильтр прячет `data/logs/console/*.log` из 6.4. Инструмент `Grep` агентов
построен на rg — вероятно, ловушка та же (не проверено).

**Files:**
- `docs/claude/TOOLING_NOTES.md` — раздел «Поиск по журналам: `rg -uu` или `scripts/log_digest`»
- `.claude/skills/project-rules/SKILL.md` — одна строка в §8 (поиск по журналам) — только по слову владельца (О-5)

**Acceptance criteria:**
- [ ] Три команды выше с выводом — в заметке; проверка `Grep` агента на `logs/` — результат записан (найдено / 0).
- [ ] Строка R-21 в `plans/queue/defects.md` исправлена лидом (файл сейчас правит другая сессия — не трогать из задачи).

**Out of scope:** правка `.ignore` (она задаёт область индекса qex); `.rgignore` с возвратом `*.log` — развилка О-5.

---

### Task 6.14 — Живой стенд Ф6 и приёмка фазы

**Level:** Senior · **Assignee:** teamlead (стенд), reviewer, cto (приёмка фазы) · **Layer:** — · **Module contract:** n/a · **[PENDING]** (после 6.1–6.13)
- **Handoff:** teamlead(стенд, числа) -> reviewer(фаза) -> cto(S7)

**Goal:** стенд `run_sim_all.ps1` (оба режима `-Recipe`) и один запуск без скрипта (`python multiprocess_prototype/run.py`).
Проверки: выделение текста в окне + `topology.apply`; триггер дампа; искусственный застой; смена рецепта.
`log_digest` до и после фазы: база шаблонов снимается здесь.

**Files:**
- `plans/observability-closure/stand-phase-6.md` — отчёт
- `scripts/log_digest/baseline/prototype.json`

**Acceptance criteria:**
- [ ] Таблица «голос из R-21 → где он теперь» по каждому из пяти голосов — файл и `rg -uu` с выводом.
- [ ] Консоль каждого процесса: число файлов `console.log` = числу процессов топологии.
- [ ] Застой: дамп в `hang/` за ≤ `stall_sec` + `check_sec`; тревога в readback PM.
- [ ] `log_digest` прогона 2 против базы прогона 1: NEW = 0 на одинаковом сценарии (или каждый NEW объяснён).
- [ ] `/core:quality:observability-acceptance` — строки новых ручек (`stall_watchdog`, `console_capture`, очередь консоли) с ценой в выключенном.

**Out of scope:** приёмка R-8 (stand-recipe-switch 1.5).
