# Plugins/sim/robot_host — хост Modbus TCP-симулятора робота

Task 1.1 плана [`plans/line-sim/phase-1-vertical-slice.md`](../../../plans/line-sim/phase-1-vertical-slice.md).

## Назначение

Тонкий плагин `ProcessModulePlugin` (`GenericProcessApp`) над
[`Services.robot_comm.server.sim_robot.SimRobotServer`](../../../Services/robot_comm/server/sim_robot.py)
— форма пары «сервис в `Services` / плагин в `Plugins`», как у
[`Plugins/io/otel_export`](../../io/otel_export/README.md). Поднимает Modbus
TCP-сервер (симулятор робота линии) в процессе `robot` приложения
`apps/line_sim`, считает записи обмена и отдаёт статус командой.

## Конфиг (`pipeline.yaml`)

| Ключ | Дефолт | Смысл |
|---|---|---|
| `host` | `127.0.0.1` | адрес слушателя |
| `port` | `5021` | Modbus TCP порт |
| `unit_id` | `2` | Modbus unit id робота |
| `auto_start` | `true` | поднять сервер в `start()` |
| `belt_mm_s_at_max_freq` | нет (сырой режим) | Task 2.3a: калибровка ленты на старте (см. §Команды ленты) |
| `jog_timeout_ms` | `500` | Task 2.3a: dead-man `belt.jog` — таймаут без подкачки |
| `jog_freq_hz` | `10.0` | Task 2.3a: частота `belt.jog` по умолчанию, если клиент её не передал |
| `scene_process` | `camera` | Task 3.5: процесс сцены, куда уходит событие «задание выполнено» |
| `job_ms` | нет (`RobotSimCore` дефолт `job_ticks=2`) | Task 5.3b: длительность задания в мс — `job_ticks = max(1, round(job_ms / (TICK_INTERVAL_S*1000)))`, `TICK_INTERVAL_S` из `Services.robot_comm.server.sim_core`. Разбор — в `configure()`, отказ (не число > 0, `bool` не считается числом) наблюдается на попытке поднять сервер (`_start_server` → `_fail`, `state="error"`), процесс живёт |

## Команда

`sim_robot.status` → `{running, host, port, unit_id, writes_seen, state, world, journal}`,
где `journal` — снимок `SimJournal.counters()` (`{}`, если сервер не поднят).

## Журнал заданий (line-sim Ф5.1)

`_start_server` заводит `SimJournal()` ДО поднятия `SimRobotServer` и передаёт
ей оба колбэка ядра: `on_write` каждого доступа (чтения тоже — журнал сам
считает их отдельно) форвардится из `_on_write`, `RobotSimCore(on_event=...)`
получает `journal.on_event`. Мотив (владелец, 2026-09-23): на живой линии
робот забирал одну деталь трижды — журнал отвечает, СКОЛЬКО заданий пришло от
прототипа и ПОЧЕМУ повтор, а не только факт дубля. Подробности причин
(`dups_same_capture`/`dups_tracked`) — README `Services/robot_comm/server`.
Третья причина 5.1 (`repeats_frozen_xy`, «те же X/Y с новым энкодером») ушла
из журнала в задаче 5.1b — считается на стороне сцены, `TruthLedger.
false_alarm_frozen_xy` (`Services/line_sim/core/truth.py`).

| Команда | Ответ |
|---|---|
| `sim_robot.journal` | `{status: "ok", counters: {...SimJournal.counters()}, recent: [≤50 {t, side, text, tag}, старые первыми]}`; без сервера — `{status: "error", message: ...}` |
| `sim_robot.journal_reset` | `SimJournal.reset()` + очистка `recent` → `{status: "ok"}`; без сервера — `{status: "error", ...}` |

`recent` наполняется ТОЛЬКО тактом паблишера (`_publish_once` → `journal.drain()`,
только строки с тегами `job`/`dup`/`done` — служебные `""`/`"flag"`
отбрасываются). `drain()` разрушающий: тик паблишера — единственный владелец,
`_on_write` в журнал только пишет, никогда не читает и не чистит. Уровни на том
же такте: `jobs_seen`, `dups_seen`, `dups_same_capture`, `dups_tracked`,
`jobs_done` (`ctx.publish_metric`, объявлены в `configure` через
`declare_metric`). `repeats_frozen_xy` ушёл из этого списка в 5.1b.

## Событие «задание выполнено» (Task 3.5)

`_start_server` строит `RobotSimCore(on_job_done=self._on_job_done)` и отдаёт его
`SimRobotServer(..., core=core)`. Ядро зовёт колбэк в потоке тикера сервера ровно
один раз на завершённое задание с `{index, x_mm, y_mm, ecap, t}`; плагин пересылает
его `DeviceHubClient(ctx, target_process=scene_process).send_fire_and_forget(
"scene.job_done", event)` — неблокирующая постановка в очередь, ответа не ждёт.
Колбэк **не бросает**: исключение клиента или `False` →
`ctx.health.report_error(..., context="sim_robot_host.job_done", throttle=30.0)`,
тикер робота живёт дальше. **`False` бывает только без роутера или без `send_async`.**
Переполненная очередь `AsyncSender` и остановленный отправитель возвращают `True`
(замер ревью: очередь на 1, три отправки → `[True, True, True]`, `dropped: 2`, ошибок
health 0) — такую потерю видно только по `AsyncSender.dropped`, warning-логу роутера и
пропуску `index` в `scene.status` → `recent`. Плагин сцены этот модуль не импортирует — только имя
процесса в конфиге.

## Команды ленты (Task 2.3a)

Пять команд `belt.*` — командная поверхность ленты процесса `robot`, единая для
трёх клиентов (прототип через боевой `VfdClient`/мост, веб-пульт Task 2.3b,
ручной `send_command`). Все, кроме `calibrate`/`status`, пишут mailbox ПЧ ТЕМ ЖЕ
путём, что Modbus-запись инспектора (`RobotSimCore.command_vfd`), и применяются
на ближайшем тике Motion-цикла (`SimRobotServer._ticker`, период
`TICK_INTERVAL_S`=10 мс) — **не немедленно**: команда пишет mailbox и
возвращает статус сразу, он может ещё не отражать её (до ~12 мс), клиенты
опрашивают `belt.status`.

| Команда | Аргументы | Действие |
|---|---|---|
| `belt.run` | `freq_hz` (обяз., `[0, freq_max_hz]`), `reverse` (bool, default `false`) | `command_vfd(run=True, freq_hz, reverse)`; снимает jog безусловно |
| `belt.stop` | — | `command_vfd(run=False)` — пишет ТОЛЬКО RUN, частоту не трогает; снимает jog безусловно |
| `belt.jog` | `direction` (обяз., `+1`/`-1`), `freq_hz` (default `jog_freq_hz`) | `command_vfd(run=True, freq_hz, reverse=direction<0)`; ставит/продлевает dead-man дедлайн `jog_timeout_ms` |
| `belt.calibrate` | `mm_s_at_max_freq` (обяз., `>=0`, конечное) | `core.belt.set_calibration(...)` под её собственным локом; mailbox НЕ трогает |
| `belt.status` | — | ничего не пишет, только читает |

Ответ: `{ok: True, run, freq_hz, reverse, mm_s, encoder, jogging, mm_s_at_max_freq}` —
`run`/`freq_hz`/`reverse` из **эффективного** состояния ленты (`core.belt.state`),
не последней команды КОНКРЕТНО этого плагина: один mailbox, два мастера
(боевой мост и `belt.*`), арбитраж — «последний записавший побеждает», как у
реального ПЧ с двумя мастерами; замков/приоритетов между ними нет. Ошибки:
`{ok: False, error: "bad_args: <текст>"}` (нет обязательного поля, не число,
`freq_hz` вне диапазона, `direction` не `±1`, отрицательная/NaN калибровка) или
`{ok: False, error: "server_not_running"}` (`self._server is None`) — без
исключения наружу.

**Dead-man `belt.jog`.** Без подкачки лента сама останавливается через
`jog_timeout_ms` (дефолт 500 мс) — но ТОЛЬКО если mailbox к этому моменту
всё ещё равен тому, что записал именно этот jog (`VFD_CMD_ADDR`, 3 регистра
RUN/DIR/FREQ, считаются ИЗ АРГУМЕНТОВ команды, не читаются обратно из
mailbox — ревью Task 2.3a, п.2: обратное чтение могло бы принять за «свой»
jog запись другого мастера, попавшую в окно между записью и чтением); если
другой мастер (боевой `VfdClient` или прямая Modbus-запись) переписал mailbox
раньше — jog считается перебитым, флаг снимается, лента НЕ трогается.

Сторож (`_check_jog_watchdog`) исполняется на ДВУХ потоках — воркере
паблишера (`_publish_loop`) и потоке-диспетчере команд (`message_processor`,
через `_belt_status()`) — и на обоих ОДИН и тот же `self._lock` держится на
ВЕСЬ путь сторожа (дедлайн + чтение mailbox + сравнение + `command_vfd`), тем
же куском, каким `cmd_belt_run`/`cmd_belt_stop`/`cmd_belt_jog` держат его
вокруг своего `command_vfd` (ревью Task 2.3a, находка «гонка сторожа jog»:
без единого замка на весь путь `belt.run` с потока диспетчера мог записать
mailbox МЕЖДУ чтением сторожа и его стопом — сторож гасил уже НОВУЮ команду,
воспроизведено стохастически 3/20000, детерминированно —
`tests/test_hazards.py::test_watchdog_holds_lock_across_mailbox_read_and_stop`).
Проверка идёт двумя путями:
1. на каждом тике `_publish_loop` (`publish_ms`, дефолт 50 мс) — зовётся
   КАЖДУЮ итерацию, включая паузу процесса (ревью, п.6): без этого dead-man
   jog не сработал бы, пока пульт держит процесс на паузе и никто не
   опрашивает статус (`tests/test_hazards.py::test_publish_loop_dead_man_while_paused`);
   боевой путь через реальный поток паблишера (не тестовый no-op
   `MockWorkerManager.create_worker`) —
   `tests/test_hazards.py::test_publish_loop_dead_man_stops_belt_for_real`;
2. опортунистически внутри `_belt_status()` — вызывается ПЕРЕД сборкой ответа
   ЛЮБОЙ команды `belt.*`, в т.ч. `belt.status`: клиент, опрашивающий статус
   в цикле, сам выступает "тиком" для watchdog. Добавлено сверх исходного
   DESIGN (только `_publish_loop`) — под `MockProcessServices`/тестовым
   `MockWorkerManager` (`plugins/testing.py`) воркер-луп не выполняется вовсе
   (`create_worker` — no-op запись вызова), а `SimRobotServer._ticker` — уже
   реальный поток независимо от него; без пути (2) `belt.jog` в тестах никогда
   бы не остановился сам.

**Строгие типы аргументов** (ревью Task 2.3a, п.5): `belt.run.reverse` обязан
быть настоящим `bool` (`bool("false")` в Python — `True`, строка отклоняется),
`belt.jog.direction` обязан быть настоящим `int` `±1`, НЕ `bool` (`bool` —
подкласс `int`, `True in (1, -1)` истинно) — оба случая уходят в `bad_args`,
mailbox не трогается.

**Начальная калибровка.** `belt_mm_s_at_max_freq` в `pipeline.yaml` — если
задан, `_start_server` вызывает `set_calibration(v)` И командует
`run=True, freq=freq_max_hz` через mailbox (решение ведущего 2026-09-22):
лента едет с первого тика, как раньше, но зеркало ПЧ и `belt.status`
согласованы с самого старта. Без ключа — «сырой» режим
(`BeltDrive.from_enc_rate`) как до этой задачи.

**Поток исполнения.** Обработчики `cmd_belt_*` вызываются
`RouterManager._dispatch_command` → `CommandManager.handle_command` синхронно
на воркере **`message_processor`** — единственном потоке обработки входящих
сообщений процесса (`multiprocess_framework/modules/process_module/threads/system_threads.py:36-39`,
`SystemThreads._message_processing_loop`, регистрируется как
`worker_manager.create_worker("message_processor", ...)`). Отсюда правило:
`cmd_belt_*` не блокируют — ни `sleep`, ни `router.request` (последнее внутри
приёмного потока — `RouterReentrantRequestError`).
`state` ∈ `configured` / `running` / `error` / `stopped` — свои состояния, не
`PluginState` фреймворка (тот же довод, что у `OtelExportPlugin`: «поднялся, но
не может» его словарём не выразимо). `world` ∈ `ok` / `unavailable`
(`ctx.state_proxy is None` — Task 2.0 не влита).

## Паблишер мира (Task 2.2)

Каждые `publish_ms` (дефолт 50, конфиг `pipeline.yaml`) плагин кладёт энкодер
сервера в дерево `StateStore` по пути `sim.belt.encoder`
(`{value, mm_s, t}` — воркер-луп `sim_robot_world_publisher`, как у
`TelemetrySinkPlugin._sample_loop`) и отдаёт уровни `encoder`/`belt_mm_s`/
`writes_seen` через `ctx.publish_metric`. `mm_s` — точная скорость модели ленты
(`RobotSimCore.belt_mm_s` → `BeltDrive.mm_s`). Уровни публикуются и без
`ctx.state_proxy` — тогда пропускается только запись в мир. Потребитель — `Plugins/sim/scene_source`
(Task 2.2), см. [`apps/line_sim/README.md`](../../../apps/line_sim/README.md#общий-мир-task-22).

## Деградация без `pymodbus`

`SimRobotServer(...)` бросает `ModbusNotAvailableError` (текст содержит слово
«modbus»), если `pymodbus` не установлен. Плагин ловит её в `_start_server`,
уходит в `state="error"`, зовёт `ctx.health.report_error(...)` — факт в
плоскость ошибок (`errors.log`) + строка журнала одним вызовом. Процесс при
этом поднимается: исключение наружу не уходит.

## Занятый порт

`SimRobotServer.start()` не сообщает об ошибке бинда синхронно (сервер поднят в
фоновом daemon-потоке `pymodbus`). Плагин сам биндит пробный сокет на
`host:port` ДО обращения к `SimRobotServer` — занятый порт ловится тут же,
синхронно, той же дорогой (`report_error`, `state="error"`).

На POSIX пробный сокет ставит `SO_REUSEADDR`, как и сам сервер (pymodbus передаёт
`reuse_address=True`): порт в TIME_WAIT после прошлого запуска занятым не считается,
а живой слушатель на том же адресе по-прежнему даёт `EADDRINUSE`. На Windows опция
не ставится — там она разрешает bind поверх живого слушателя. Без этого рестарт сима в течение
~30 с на macOS падал в `error` при никем не занятом порту (стенд Task 1.3,
2026-09-21); тесты — `tests/test_acceptance_time_wait.py`.

## Счётчик записей

`on_write(fc, addr, values)` зовётся `pymodbus` на СВОЁМ потоке. `values is
None` — чтение, не считается. Запись инкрементирует `writes_seen` под
`Lock` (безопасно с любого потока); перенос в `ctx.record_metric("sim_robot.
writes", …)` (плоскость stats, `history_query`) идёт ДЕЛЬТОЙ и только со
штатных потоков плагина (`cmd_status`, `shutdown`) — не с потока `pymodbus`
(подробности и обоснование — докстринг `plugin.py`).

## Границы

Импорт `multiprocess_prototype.*` запрещён (ADR-120, зеркало правила
`examples/*`): плагин — словарь повторного использования между приложениями.

## Out of scope (Task 1.1)

Живая скорость энкодера от команды ПЧ (Ф2.1), канал энкодера в line-процесс
(Ф2.2) — оба решаются внутри `Services/robot_comm`, этот хост их не касается.
