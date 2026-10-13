# Ф6 — Ничего мимо: консоль каждого окна, зависший поток со стеком, сводка прогона

> **ОТЛОЖЕНО владельцем 2026-10-13** (фокус на роботе и симуляторе). Ревью плана, итерация 1 — CHANGES REQUESTED: [`reports/ph6.review-plan-r1.md`](reports/ph6.review-plan-r1.md); при возврате к фазе — сначала правки по нему, потом итерация 2.

> **Ф6 этого плана — не «гейт Ф6 этапа 6»** из Task 5.4 (`telemetry-stage6`). Совпадение номеров случайное.

**Откуда.** Запрос владельца 2026-10-13: «максимальный контроль, ничего не упустить». Нужно видеть все журналы,
консоль каждого запущенного окна и всё, что идёт мимо логгера. Поводы — дефекты `plans/queue/defects.md`:
R-8 (гипотеза H1), R-14, R-15 (только как пример голоса), R-18, R-19, R-20, R-21.
Разбор H1 — `docs/maps/recipe-switch.md`, раздел «R-8: ведущая гипотеза H1».
Метод дампа без прав администратора — `plans/2026-10-12_stand-recipe-switch/reports/1.1.investigation.md` (`uvx py-spy dump`).

**Почему фаза этого плана, а не новый план.** Правило `CLAUDE.md`: «Один активный план на модуль; новая работа — фазой».
Основной модуль фазы — `logger_module`. У него уже есть активный план — этот: открыты 4.17 (одна дорога к писателю)
и 4.18 (R-14). Отдельный план дал бы второй активный план на `logger_module` и разрезал бы класс «голос мимо журнала»
на два плана.

**Граница.** Смена рецепта (задача смены, готовность, устройства, `recipe.activate`, apply не на потоке сообщений) —
план [`2026-10-12_stand-recipe-switch`](../2026-10-12_stand-recipe-switch/plan.md), здесь её нет.
Живая проверка H1 — Task 1.1b того плана, здесь не повторяется.
**Тот план зависит от Task 6.1 и 6.2:** без 6.1 у R-8 нет починки класса H1; без 6.2 следующий
застой придётся ловить вручную через py-spy.

**Правила исполнения (наследуются).** Для каждого механизма слепой тестер пишет тесты до кода
(`.claude/CLAUDE.md` «Test authorship»). Лид делает break-injection. На живом стенде — числа, а не «работает».
Ревьюер — после каждой задачи. Лимит — 2 итерации, затем `ESCALATION -> teamlead`.

**Пересечение с полосой Ж** (`plans/2026-10-03_lifecycle-owner-scope`). Ж 1.2b-2 переводит кодмодом
`LoggerCore.shutdown` (`logger_core.py:483`) и `ChannelRoutingManager.shutdown` (`channel_routing_manager.py:486`) на шаблон
`_on_shutdown`. Ж 1.3 (на заморозке) — `WorkerManager`. Задачи ниже, которые касаются `process_module`,
`process_runner`, `topology_manager` или `shutdown` этих двух менеджеров, помечены **«согласовать с полосой Ж»**,
и в них названы функции.

## Порядок

Волна 1 (нужна плану stand-recipe-switch): 6.1 → 6.2 → 6.3. Параллельно — 6.4: только скрипт стенда, файлы не пересекаются.
Волна 2 (голоса и консоль, файл [`phase-6b-voices-and-digest.md`](./phase-6b-voices-and-digest.md)): 6.5 → 6.6 → 6.7 → 6.8.
Волна 3 (сводка и шум): 6.9; затем 6.10, 6.11, 6.12, 6.13 в любом порядке.
Приёмка фазы: 6.14.

---

### Task 6.1 — [VERTICAL SLICE] Запись журнала не блокирует вызывающего: у консоли свой поток-писатель

**Level:** Senior+ · **Assignee:** teamlead · **Layer:** framework · **Module contract:** public-api-change (новые поля схемы канала и новые счётчики readback) · **[PENDING]**
- **Handoff:** tester(RED, слепой, по критериям ниже) -> teamlead(GREEN) -> reviewer; лид — инъекции, живой стенд

**Goal:** вызов журнала на любом потоке возвращается за ограниченное время, даже когда консоль Windows заморожена
(выделение текста, QuickEdit) или труба stdout не читается. Консольная запись идёт отдельным потоком-писателем
через ограниченную очередь. Переполнение очереди отбрасывает запись и увеличивает счётчик. Файловые стоки
остаются синхронными: запись на диске к моменту возврата, по ADR-LOG-008.

**Сквозной срез:** канал `ConsoleChannel` (фреймворк) → счётчики в `introspect.observability` (readback, backend_ctl) →
стенд: выделить текст в окне `prototype` → `topology.apply` через backend_ctl → ответ PM приходит.

**Files:**
- `multiprocess_framework/modules/logger_module/channels/log_channel.py` — `ConsoleChannel.__init__`, `ConsoleChannel.write`, `ConsoleChannel._warn_sink_stuck`, `ConsoleChannel.close`
- `multiprocess_framework/modules/logger_module/configs/logger_manager_config.py` — `LoggerChannelSchema`: поля очереди консоли
- `multiprocess_framework/modules/channel_routing_module/core/channel_routing_manager.py` — сбор счётчиков стока в readback (рядом с `sink_writes_dropped_by_channel`)
- `multiprocess_framework/modules/logger_module/DECISIONS.md` — новый ADR
- `multiprocess_framework/modules/logger_module/tests/test_console_writer_thread.py` — новый
- `multiprocess_framework/modules/logger_module/README.md`

#### Task 6.1 — дизайн

Решает лид; спорное — к CTO до старта (развилка О-1).

1. Консоль — вид, а не запись: доказательная запись живёт в файле. Поэтому поток-писатель заводится только у консоли
   (и у любого будущего стока с флагом «медленный», например HTTP). Файловые стоки не трогаются.
   Это сужает отказ ADR-LOG-009 («очередь writer'а умирает вместе с процессом»): довод верен для файла, для консоли — нет.
2. Очередь — `queue.SimpleQueue` или `deque` с потолком из схемы (`queue_max`, дефолт — решает teamlead, число в ADR).
   Производитель кладёт запись без ожидания. Очередь полна → дроп + `sink_writes_dropped` (имя прежнее, ADR-LOG-009).
3. Поток-писатель — daemon, один на канал, имя `console-writer-<канал>`. При `close()` дренирует очередь со сроком.
   Срок — из `stop_budget`, если доступен, иначе литерал в ADR. Шаблон `shutdown` Ж 1.2b-2 не трогать: остановка
   идёт через `ConsoleChannel.close()`, его уже зовёт `ChannelRoutingManager.shutdown`. **Согласовать с полосой Ж**
   порядок `close()` в `_on_shutdown` после кодмода.
4. Голос «консоль не принимает» нельзя писать в stderr синхронно. Сегодня он идёт `_warn` → `emergency_log` →
   stdlib lastResort → тот же замёрзший stderr: голос о застое сам встаёт в застой. Новый адрес — запись
   через `LoggerCore` в файловые каналы, с исключением консоли (или счётчик плюс голос с потока-писателя после
   разморозки). Выбор — teamlead, запись в ADR.
5. Поток-писатель — деталь стока внутри канала, не второй `LoggerCore` (правило «один писатель»).

#### Task 6.1 — шаги и приёмка

**Steps:**
1. Тестер (слепой, только по критериям ниже) пишет красные тесты. Замёрзший сток моделируется `StreamHandler`
   на объекте, у которого `write()` ждёт `threading.Event`. Каждый тест с риском зависания зовёт `log()`
   в daemon-потоке с дедлайном на `join`.
2. teamlead пишет ADR и код, затем прогоняет радиус: `pytest -q multiprocess_framework/modules/logger_module multiprocess_framework/modules/channel_routing_module`.
3. Инвентарь (шаг для haiku, после кода): все синхронные пути в stderr на потоке сообщений PM, которые остаются
   после правки (`emergency_log`, `print(..., file=sys.stderr)`, `warnings`, lastResort). Число и строки `файл:строка`
   идут в отчёт задачи. Их починка — Task 6.5–6.7, не здесь.
4. Лид делает инъекции: (а) вернуть синхронный `emit` в `ConsoleChannel.write` → тест «возврат < 50 мс при замёрзшей консоли» краснеет;
   (б) убрать потолок очереди → тест «дроп со счётчиком» краснеет.
5. Живой стенд (`scripts/run_sim_all.ps1 -Recipe pult_demo -NoBrowser -NoRobotView`):
   выделить текст в окне `prototype` → 3 вызова `topology.apply` через backend_ctl → ответ PM на каждый;
   `introspect.observability` показывает рост дропа консоли; снять выделение → консоль догоняет, новые строки идут.

**Acceptance criteria:**
- [ ] Замёрзшая консоль: 1000 вызовов `log()` с одного потока возвращаются за ≤ 1 с суммарно; поток не висит (тест с дедлайном).
- [ ] Очередь полна → `sink_writes_dropped` консоли растёт ровно на число отброшенных; файловый канал того же логгера получает все 1000 записей.
- [ ] Консоль размораживается → поток-писатель продолжает; первые записи после разморозки видны; счётчик дропа не сбрасывается молча.
- [ ] `close()` при замёрзшей консоли возвращается в срок (литерал в ADR) и не оставляет живого потока `console-writer-*`.
- [ ] Голос о застое консоли попадает в файл процесса (`system.log` или `errors.log` — по ADR) и НЕ пишется синхронно в stderr.
- [ ] Цена в выключенном / в здоровом режиме: замер p50/p99 вызова `log()` с консолью до и после правки (бенч рядом с ADR-LOG-008), разброс по 3 прогонам.
- [ ] Живой стенд: при выделенном тексте 3 из 3 `topology.apply` получают ответ ≤ 10 с; без правки (контроль) ответ не приходит. Если контроль не воспроизводит зависание — так и записать, H1 остаётся гипотезой (её проверка — stand-recipe-switch 1.1b).

**Out of scope:** файловые стоки (синхронны по ADR-LOG-008); apply вне потока сообщений (stand-recipe-switch 1.2); перехват сырого stderr (6.8).

---

### Task 6.2 — Сторож зависшего потока в каждом процессе: дамп всех стеков в файл и тревога

**Level:** Senior+ · **Assignee:** teamlead · **Layer:** framework · **Module contract:** public-api-change (ручка схемы `observability`, поле heartbeat) · **[PENDING]** (после 6.1 — тревога не должна встать в замёрзшую консоль)
- **Handoff:** tester(RED, слепой) -> teamlead(GREEN) -> reviewer; лид — инъекции, стенд

**Goal:** в каждом процессе, не только в PM, поток сообщений отмечает каждый такт цикла. Если отметки нет дольше N с,
сторож сам пишет дамп всех потоков (`faulthandler.dump_traceback(all_threads=True)`) в файл
`<log_dir>/<процесс>/hang/<время>.txt` и поднимает тревогу. Тревога — запись CRITICAL и счётчик `stalls`
в heartbeat/readback. Ручка вкл/выкл. В выключенном режиме потока сторожа нет, а отметка цикла — одна запись атрибута (замер).

**Files:**
- `multiprocess_framework/modules/logger_module/core/stall_watchdog.py` — новый (рядом с процессными хуками, ADR-LOG-011)
- `multiprocess_framework/modules/logger_module/core/process_hooks.py` — `install_process_hooks`: поднять сторож по ручке
- `multiprocess_framework/modules/process_module/threads/system_threads.py` — `SystemThreads._message_processing_loop`: одна строка отметки такта. **Согласовать с полосой Ж** (поток — воркер `WorkerManager`, Ж 1.3)
- `multiprocess_framework/modules/process_module/heartbeat/process_heartbeat.py` — `ProcessHeartbeat`: поле застоя в payload. **Согласовать с полосой Ж**
- `multiprocess_framework/modules/logger_module/tests/test_stall_watchdog.py` — новый
- `multiprocess_framework/modules/logger_module/DECISIONS.md`

**Design:**
1. Ручка: `observability.stall_watchdog: {enabled, stall_sec, check_sec, max_dumps}`. Дефолт выключен во фреймворке;
   стенд прототипа включает её в `system.yaml` (решение О-2). Переключение — на любой границе, по правилу
   владельца: процесс (L1/L2 существующих слоёв ручек), без рестарта.
2. Сторож — один daemon-поток на процесс. Он читает отметки «имя потока → monotonic». Дамп пишется прямо в fd файла
   (`faulthandler`), без логгера и без локов: если застрял сам логгер, дамп всё равно ляжет.
3. Один застой даёт один дамп. Следующий дамп — только после возобновления отметок. Всего дампов за жизнь
   процесса — не больше `max_dumps`. Это защита от заполнения диска при вечном застое.
4. Тревога через логгер — лучшая попытка. Если поток держит лок файлового стока, запись тревоги отбросит
   лесенка ADR-LOG-009, поэтому главное доказательство — файл дампа. Счётчик `stalls` и
   `last_stall_thread` идут в heartbeat, и PM видит застой ребёнка без участия ребёнка.
5. Отметка — публичный вызов `beat(name)` хуков процесса, чтобы воркер плагина мог отмечаться тоже.
   В этой задаче отмечается только поток сообщений.

**Steps:** тестер — красные тесты (поток сообщений «застрял» на `Event` → файл дампа содержит имя функции застоя; выключено → потока нет)
→ teamlead — код и ADR → радиус `pytest -q multiprocess_framework/modules/logger_module multiprocess_framework/modules/process_module/tests`
→ лид, инъекции: (а) отметка не обновляется → ложный дамп в здоровом процессе краснеет тест «здоровый — 0 дампов»;
(б) дамп через логгер вместо fd → тест «застрял сам логгер» краснеет
→ стенд: застой вносится отладочной командой (Task 6.3 даёт триггер) или `py-spy`-проверкой одного случая.

**Acceptance criteria:**
- [ ] Застой потока сообщений на 2×`stall_sec` → ровно 1 файл дампа; в нём имя потока `*_message_processor` и функция застоя.
- [ ] Здоровый процесс 10 мин на стенде → 0 дампов во всех процессах.
- [ ] Застой внутри записи журнала (сток держит лок) → дамп всё равно записан.
- [ ] `enabled: false` → нет потока `stall-watchdog`; цена отметки такта — замер (нс/вызов, 3 прогона), число в ADR.
- [ ] PM видит `stalls > 0` у ребёнка через readback, пока ребёнок застрял.

**Out of scope:** перезапуск застрявшего процесса (решение супервизора, не сторожа); отметки воркеров плагинов (только API).

---

### Task 6.3 — Стек живого процесса по требованию и памятка

**Level:** Middle+ · **Assignee:** developer · **Layer:** framework + docs · **Module contract:** impl-only · **[PENDING]** (после 6.2)
- **Handoff:** developer(REDS в брифе) -> reviewer

**Goal:** взять стек любого процесса стенда одной командой и без прав администратора. Пути два:
(а) внешний — `uvx py-spy dump --pid <pid>`;
(б) внутренний — файл-триггер `<log_dir>/DUMP_NOW`: сторож 6.2 замечает его в пределах `check_sec`, каждый процесс
пишет дамп в свой `hang/`, триггер удаляется. Путь (б) не требует, чтобы поток сообщений PM был жив.
Отладочная ручка периодического дампа `INSPECTOR_STALL_DUMP` из GUI (`multiprocess_prototype/frontend/app.py:81-91`)
переводится на сторож фреймворка. Старый ключ остаётся алиасом с голосом — FREEZE, не KILL.

**Files:**
- `multiprocess_framework/modules/logger_module/core/stall_watchdog.py` — опрос триггера
- `multiprocess_prototype/frontend/app.py` — `INSPECTOR_STALL_DUMP` → алиас ручки
- `docs/tools/hang-stack-dump.md` — новая памятка: py-spy (PID из `backend_ctl capabilities` / `Get-Process`), триггер, где искать дампы, как читать
- `multiprocess_framework/modules/logger_module/tests/test_stall_watchdog.py` — тесты триггера

**Acceptance criteria:**
- [ ] Триггер при живом стенде → дамп от каждого процесса за ≤ `check_sec` + 1 с; триггер удалён.
- [ ] Триггер при застрявшем потоке сообщений PM → дамп PM всё равно есть.
- [ ] Памятка проверена исполнением: агент по одной памятке снимает стек PM через py-spy и через триггер (вывод в отчёте).

**Out of scope:** команда backend_ctl для дампа (идёт через поток сообщений — бесполезна при застое).

---

### Task 6.4 — Стенд: консоль каждого окна в файл, QuickEdit выключен

**Level:** Middle · **Assignee:** developer · **Layer:** tooling · **Module contract:** n/a · **[PENDING]** — можно параллельно с 6.1
- **Handoff:** developer -> reviewer(express)

**Goal:** закрепить смягчение 2026-10-13 (`scripts/run_sim_all.ps1`: тройник в `data/logs/console/<окно>_<время>.log`)
и убрать спуск H1 на стенде: окна стенда стартуют с выключенным QuickEdit (SetConsoleMode без
`ENABLE_QUICK_EDIT_MODE`, P/Invoke в строке запуска окна). Выделение тогда возможно только через меню окна.

**Files:**
- `scripts/run_sim_all.ps1` — `Start-Window`
- `scripts/README.md` — строка о стенде и каталоге консолей

**Acceptance criteria:**
- [ ] Три окна стенда: выделение мышью не замораживает вывод (проверка руками или через ручной сценарий, шаги в отчёте).
- [ ] Файлы консолей есть для всех трёх окон; строка `Error number -138` из ffmpeg (если линия поднята позже прототипа) — в файле `prototype_*.log`.
- [ ] Ошибка запуска Python (неверный путь скрипта) — traceback в файле консоли.

**Out of scope:** перехват консоли вне стенда (6.8). Тройник PowerShell сам может встать: `Write-Host` в замёрзшую консоль
заполнит трубу. Это записывается строкой в README; лечение — 6.8.

---

Продолжение фазы (6.5–6.14) — [`phase-6b-voices-and-digest.md`](./phase-6b-voices-and-digest.md).
