# Аудит фундамента — опись, 2. Лишние слои и дубли механизмов

Часть описи [2026-10-26_foundation-audit-inventory.md](2026-10-26_foundation-audit-inventory.md) (вход, метод съёма и «Что я оставил открытым»). Только факты, вердикт за CTO.

Обозначения: [F] — тело только пересылает вызов; [F+] — пересылка плюс мелочь (предохранитель `if not self.x`, `setdefault`, обёртка в список, `> 0`); [L] — своя логика. Счёт вызывающих подстрочный (`git grep -F ".имя("`), поэтому это верхняя граница: «всего / вне тестов».

### 2.1 Звенья-пересыльщики

| id | цепочка | тип | вызовы всего / вне тестов | сверено |
|---|---|---|---|---|
| F1 | `ProcessRegistry.stop_one` (process_registry.py:339) → `_stop_many([name])[name]` | [F+] | 20 / 1 | да (docstring и сигнатура) |
| F2 | `ProcessRegistry.stop_many` (:358) → `_stop_many` | [F], docstring ~25 строк | 17 / 3 | да |
| F3 | `ProcessRegistry.stop_all` (:492) → `stop_many` → `_stop_many` | [F+] собирает имена, считает выживших | 39 / 4 | по отчёту |
| F4 | `PM._cmd_process_stop` → `PM.stop_process` (process_manager_process.py:3827) → `registry.stop_one` → `_stop_many` → `ChildProcessStop` | 4 звена; `stop_process` [F+]: is_alive + таймаут из конфига | 11 / 3 | да |
| F6 | `ProcessModule.send_message` (process_module.py:1187) → `ProcessCommunication.send_message` (communication/process_communication.py:290, «алиас send_to_process») → `send_to_process` | 2 звена [F+], [F] | 46 / 18 | да |
| F8 | `ProcessModule.send` (:1228) → `ProcessCommunication.send` → `RouterManager.send` (router_manager.py:552) → `_do_send(_to_dict(...))` | [F+], [L], [F+] | 6 / 3 | да (RouterManager.send) |
| F10 | `ProcessModule.broadcast_message` (:1193) → `ProcessCommunication.broadcast_message` (:294) → `broadcast(...) > 0` | [F+], [F+] | 12 / 3 | да |
| F11 | `ProcessModule._log_info` (:1126) → `ObservableMixin._log_info` → `_log_checked` → `_call_manager_result` | [F+] `setdefault("module", self.name)`; сигнатура `-> None`: возврат базы (bool) теряется | 351 / 249 | да |
| F13 | `LoggerCore.info/warning/error/debug/critical` (logger_core.py:1921…) → `LoggerCore.log` (:1478) | [F+] подстановка scope/level | — | да |
| F14 | `LoggerManager(LoggerCore)` (logger_manager.py, 99 строк): своих методов два — `__init__` (ставит `_instance`) и `_on_shutdown`; реэкспорт 4 имён | класс-обёртка | — | да |
| F15 | `ProcessIO.send_data/command/event` (process_io.py:53, 57, 73) → `ProcessModule.send_message` (= F6) | [F+] собирает конверт | — | по отчёту |
| F16 | `RouterAdapter.send` (router_adapter.py:53) → `manager.send`. `ProcessCommunication` его не использует, идёт в `router_manager` напрямую | [F+] | 1 место создания в проде | да (тело) |
| F17 | `SRM.get_process_data` (shared_resources_manager.py:394) → `_process_state_registry.get_process_data` | [F] | 79 / 37 | да |
| F18 | `SRM.get_all_process_data`, `get_process_names`, `get_process_config`, `has_process` | [F] | 7/3; 60/19; 12/4 | по отчёту |
| F20 | `RouterManager.start_listening/stop_listening` (:1708, :1711) → `_receiver.start/stop` | [F] | 14 / 1 | да |
| F21 | `RouterManager.register_message_scenario` (:1847) → `event_dispatcher.create_scenario` | [F] | — | да |
| F22 | `ObservabilityHub.drain_logs/errors/stats/observations` (observability_hub.py:320–329) → `_<x>_channel.drain()` | [F] | 15 / 1 | да (drain_logs) |
| F23 | `WorkerManager.has_worker` (worker_manager.py:370) → `_worker_registry.has` | [F] | 20 / 3 | да |
| F24 | `ProcessAdapter.stop` (process_adapter.py:89) → `manager.stop()` + `manager.shutdown()` | [F+] try/except | — | да |
| F25 | `SystemLauncher.shutdown` (system_launcher.py:604) → `stop()`, «Алиас для stop()» | [F] | — | да |

Таблица неполна по state_store, chain, command, message: регулярка поиска форвардеров дала 0, вручную эти модули не просматривались.

### 2.2 Три сквозных пути, по звеньям

Диаграммы: [paths-lifecycle-message-log.mmd](../diagrams/foundation-audit/paths-lifecycle-message-log.mmd).

**Путь 1 — рестарт и стоп ребёнка** (вход: `backend_ctl/driver.py:1255`, команда `process.restart`):
1. `PM._cmd_process_restart` [F+]: `_merge_cmd_args` и проверка `process_name`.
2. `PM.restart_process` (:3846) [L]: стоп, удаление, регистрация, `_drain_process_queues`, `_bump_incarnation` (:3889, только при смене identity очередей), `create_and_register`, `start()`, `_instance_restarts` += 1 (:3906), ожидание готовности, переиздание проводов, бамп routing-epoch, broadcast refresh, публикация identity, replay телеметрии.
3. `PM.stop_process` (:3827) [F+].
4. `ProcessRegistry.stop_one` (:339) [F+].
5. `_stop_many` (:455) [L]: область `pm/stop`.
6. `ChildProcessStop` (child_process_stop.py:44) [L]: `request_stop`, `join_until`, `kill`.
7. Ребёнок: `_run_lifecycle` (process_runner.py:192–193) смотрит два события, вызывает `process_instance.stop()`.
8. `ProcessModule.stop` (:1394) [L].

Итого 8 звеньев, из них 3 [F+].

Рядом есть ещё классы группы остановки: `_ChildrenGroupStop` (process_registry.py:523) и `SystemLauncher.stop → ProcessSpawner.stop` (spawner.py:180) со своей эскалацией terminate/kill.

**Путь 2 — сообщение процесс → Router → другой процесс:** `ProcessIO.send_*` [F+] → `ProcessModule.send_message` [F+] → `ProcessCommunication.send_message` [F] → `send_to_process` [L] → `RouterManager.send` [F+] → `_do_send` [L] → `_resolve_channels` (:2145) [L] → `_deliver_by_targets` (:675) [L] → `QueueRegistry.send_to_queue` (queues/core/manager.py:269) [L] → `put_nowait`. Это 9 звеньев, 4 из них [F]/[F+]. Сторона приёма не прослежена.

**Путь 3 — лог процесса → файл:** `ProcessModule._log_info` [F+] → `ObservableMixin._log_info` [F+] → `_log_checked` [F+] → `_call_manager_result` [L] → `LoggerCore.info` [F+] → `LoggerCore.log` [L] → `ChannelRoutingManager._write_record_to_channels` (channel_routing_manager.py:1043) [L] → `FileChannel.write` (log_channel.py:993) [L] → `_SafeRotatingFileHandler`. Это 9 звеньев, 4 из них [F+]. Отдельного процесса-писателя в прочитанном коде нет: каждый процесс пишет сам. Агент это предположил и не проверил. `observability_wiring` (дрейн ребёнок → PM) не прослежен.

### 2.3 Несколько механизмов на одну задачу

**L1. Счётчики рестарта: три в PM, четвёртый с тем же именем в worker.** Сверено по коду.

| | `incarnation` | `instance_restarts` | `restart_count` (монитор) | `restart_count` (worker) |
|---|---|---|---|---|
| хранение | `PM._incarnations` (process_manager_process.py:119) | `PM._instance_restarts` (:136) | `len(ProcessMonitor._restart_history[name])` (process_monitor.py:120, вывод :1745) | `worker_info["restart_count"]` (worker_registry.py:72) |
| запись | `_bump_incarnation` (:2105): из `restart_process` (:3889, только при смене identity очередей) и из `_topology_provision` (:4444) | только `restart_process` (:3906), безусловно после успешного старта | метка в `_restart_history` (:1336) только у планового краш-рестарта монитора; сброс `reset_restart_count` (:1570) после окна стабильности | worker_lifecycle.py:114, 235; лимит `max_restarts` (:233) |
| читатели | supervision-снимок, `bundle_builder` (routing_incarnation), fence (`builtin_commands.py`), `message_module/fencing/token.py`, телеметрия, `Services/otel_export`, backend_ctl | supervision-снимок, backend_ctl `process_restart_verified` | supervision-снимок, backend_ctl | `worker_manager.py:321, 360` |
| появился | 2026-07-08 (586d62183, ADR-PMM-010) | 2026-07-23 (1dd83ac0e, Task 2.1) | `_restart_history` 2026-07-08 (0ab424951) | ≤ 2026-04-30 |
| очередь | ORDER 6а, defects:21 | ORDER 6а, defects:12, 21 | ORDER 6а | — |

Когда счётчики расходятся (по чтению кода):
- ручной рестарт через backend_ctl или GUI: растёт `instance_restarts`, `restart_count` не растёт;
- рестарт с переиспользованием очередей (по умолчанию): `incarnation` не растёт;
- induced-рестарт группы (rest_for_one / one_for_all): метки в `_restart_history` нет (process_monitor.py:1426);
- `_topology_provision`: растёт только `incarnation`;
- сброс: `restart_count` обнуляется по окну, `instance_restarts` чистится с хвостами PM, `incarnation` не чистится намеренно (:1439).

**D2. Каталог операций, два источника (`OP_SPECS`).** В main не найден: `git grep OP_SPECS` пуст. По памяти (`docs/claude/memory/feedback_sonnet_implements_opus_designs_and_reviews.md:29`) он на ветке полосы Р2 (SPI хаба): `OP_SPECS` на драйверах и `DEFAULT_SOURCES` в `spi.py`, `OP_SPECS` в рантайме никто не читает, исправление «один источник истины» идёт в Р2. В main рядом: `OP_SPEC` протокола робота (`Services/robot_comm/core/protocol_v2.py:78`, генерируется из YAML) и таблицы `OPS` / `_OPS` драйверов device_hub (`robot_driver_v2/ops.py:50`, `robot_driver.py:857`, `hikvision_driver.py:167`). Связывающего кода между ними нет.

**D3. Два события остановки у ребёнка.** Своё `stop_event` на процесс (создаётся в `create_and_register`, взводится в `ChildProcessStop.request_stop`) и общее `system_stop_event` (взводит `ProcessSpawner.stop`). Ребёнок проверяет оба (process_runner.py:192–193), `_on_parent_death` (:82–104) взводит оба. `system_stop_event` появилось 2026-06-01 (d338826ab). Очередь: ORDER 6а (1.9b / 1.10 / 1.11). Сверено.

**D4. Три способа достать данные процесса из SRM.** `get_process_data(name)` (:394) [F]; deprecated-свойство `process_state_registry` (:371); `for_process(name)` → `ProcessHandle` (:322); плюс динамический `__getattr__` (:437). Вызовы: 79/37, 97/20, 49/9. Сверено.

**D5. Наследники `ChannelRoutingManager` и их маршрутизация.** Наследники: `LoggerCore` (logger_core.py:269), `RouterManager` (router_manager.py:130), `StatsManager`, `ObservationManager`; `ErrorManager(LoggerCore)` (error_manager.py:180). У `LoggerCore` свой резолв маршрута (`_effective_route` :1450, собственный `_route_cache`), у `RouterManager` свой `register_route` (:1746) и `_resolve_channels` (:2145), в базе — `_resolve_channel` (:1087). Комментарий в `channel_routing_manager.py:708–716`: `forget_channel` зовётся в базе для всех плоскостей, но после снятия `BatchBuffer` не реализован ни у одного оставшегося буфера, `getattr` тихо возвращает `None` — «защита в базе мертва у наследника».

**D6. Функции резолва имени канала (6 штук).** `routing_table.channel_name` (:103), `resolve_channel_kind` (:72), `address_aware_channel.resolve_route` / `resolve_routes` (:65, :85), `RouterManager._resolve_channels` (:2145), `RouterManager._select_queue_type` (:648), `ChannelRoutingManager._resolve_channel` (:1087). Пересекаются ли они по назначению, не выяснялось.

**D7. Два механизма перезапуска с лимитом.** `RestartPolicy` процессов: окно, backoff fixed/exponential, jitter (`restart_policy.py`, `process_monitor._compute_backoff` :1215). `worker_module`: `restart_on_failure` + `max_restarts`, фиксированный `sleep(0.1)`, без окна и backoff (worker_lifecycle.py:233–244).

**D8. Таймеры и планировщики без общего механизма.** `threading.Timer` в `config_module/tools/watcher.py:119` и `state_store_module/persistence/persistence_manager.py:258`. Кроме них: `ActuationScheduler` (process_module/generic/actuation_scheduler.py:36), `_MetricsTimer` (plugins/metrics.py:100), планировщик рестартов монитора (`_dispatch_due_restarts`, process_monitor.py:1475), daemon-flusher `DeltaDispatcher`.

### 2.4 Иерархия базовых классов (graphify, EXTRACTED)

- `BaseManager` — база для 20 классов: ProcessModule, ChannelRoutingManager, CommandManager, SharedResourcesManager, EventManager, MemoryManager, QueueRegistry, StateStoreManager, StateProxy, WorkerManager, ExecutorManager, WorkerPoolExecutor, WorkerPoolDispatcher, LatencyTracker, TopologyManager, PluginManager, RegistersManager, ConsoleManager, Dispatcher.
- Глубина пути логгера: `LoggerManager → LoggerCore → ChannelRoutingManager → BaseManager + ObservableMixin + IChannelRoutingManager`. `ErrorManager → LoggerCore → …`
- PM: `ProcessManagerProcess → ProcessModule → BaseManager + ObservableMixin + IProcessModule`. `GenericProcess → ProcessModule`.

Диаграмма: [class-hierarchy.mmd](../diagrams/foundation-audit/class-hierarchy.mmd).
