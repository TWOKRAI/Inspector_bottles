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

## Команда

`sim_robot.status` → `{running, host, port, unit_id, writes_seen, state, world}`.
`state` ∈ `configured` / `running` / `error` / `stopped` — свои состояния, не
`PluginState` фреймворка (тот же довод, что у `OtelExportPlugin`: «поднялся, но
не может» его словарём не выразимо). `world` ∈ `ok` / `unavailable`
(`ctx.state_proxy is None` — Task 2.0 не влита).

## Паблишер мира (Task 2.2)

Каждые `publish_ms` (дефолт 50, конфиг `pipeline.yaml`) плагин кладёт энкодер
сервера в дерево `StateStore` по пути `sim.belt.encoder`
(`{value, mm_s, t}` — воркер-луп `sim_robot_world_publisher`, как у
`TelemetrySinkPlugin._sample_loop`) и отдаёт уровни `encoder`/`belt_mm_s`/
`writes_seen` через `ctx.publish_metric`. `mm_s` — производная энкодера МЕЖДУ
тиками публикации (не чтение внутреннего состояния `BeltDrive` — у него нет
публичного аксессора скорости). Потребитель — `Plugins/sim/scene_source`
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
