# process_manager_module — архитектурные решения (ADR)

## ADR-PMM-001 (was ADR-PM-001): Per-process stop events (2026-04-10)

- **Контекст:** Все дочерние процессы получали один `stop_event`; `stop_process("A")` останавливал всех.
- **Решение:** У каждого дочернего процесса свой `multiprocessing.Event`; `ProcessRegistry` хранит `Dict[str, Event]`. `stop_all()` выставляет все события; `stop_one(name)` — только одно.
- **Следствие:** Возможны `restart_process` и точечное управление.

## ADR-PMM-002 (was ADR-PM-002): Минимальный ProcessSpawner (2026-04-10)

- **Контекст:** Spawner создавал ConfigManager, LoggerManager, ErrorManager, не передаваемые в дочерние процессы.
- **Решение:** Spawner поднимает только `SharedResourcesManager` и `_ProcessLogger`; полный стек — в `ProcessManagerProcess`.
- **Следствие:** Меньше дублирования и проще bootstrap.

## ADR-PMM-003 (was ADR-PM-003): Bundle contract (2026-04-10)

- **Контекст:** Bundle-словарь собирался в реестре и разбирался в runner без явного контракта.
- **Решение:** `core/bundle_contract.py` — `build_bundle()`, `validate_bundle()`; runner проверяет bundle при входе.
- **Следствие:** Один формат и явные обязательные ключи (`queues`, `config`).

## ADR-PMM-004 (was ADR-PM-004): Heartbeat / liveness в ProcessMonitor (2026-04-10)

- **Контекст:** Монитор смотрел только на состояние из ProcessStateRegistry.
- **Решение:** Дополнительно `process.is_alive()`; при выходе без актуального state — `stopped` (exitcode 0) или `crashed` (иначе), обновление PSR и broadcast.
- **Следствие:** Видны внезапные падения без участия кода дочернего процесса.

## ADR-PMM-005 (was ADR-PM-005): Расслоение process_runner (2026-04-10, обновлено 2026-04-12)

- **Контекст:** Один крупный файл совмещал загрузку класса, memory, SRM, console, lifecycle.
- **Решение:** `runner/class_loader.py`, `bundle_builder.py`; публичный API — `run_process_function` без изменений смысла.
- **История:** `console_redirect.py` был создан как отдельный модуль (2026-04-10) для переадресации stdout/stderr в очередь, но позднее удалён при рефакторинге `console_module` (2026-04-12).
- **Следствие:** Меньшие файлы и ясные границы; console redirection теперь управляется через `console_module.ConsoleManager`.

## ADR-PMM-006 (was ADR-PM-006): stop_event оркестратора вне bundle (2026-04-10)

- **Контекст:** После удаления `stop_event` из `custom` в bundle spawner всё должен передавать тот же Event в `ProcessManagerProcess`.
- **Решение:** Spawner передаёт Event третьим аргументом в `run_process_function`; runner кладёт его в `process_data.custom` перед конструктором процесса.
- **Следствие:** Bundle остаётся pickle-safe и без лишних полей; сигнал завершения с main-процесса сохраняется.

## ADR-PMM-007 (AD-8): Router endpoint для ProcessManagerProcess (2026-04-22)

- **Контекст:** ProcessManagerProcess принимал runtime-команды (`process.create/start/stop/restart`) только через внутренний CommandManager. Другие процессы в системе не могли запросить spawn/stop через Router-сообщения, что ограничивало динамическое управление (например, добавление камер в runtime).
- **Решение:** При `initialize()` регистрируется `register_message_handler("process.command", _handle_process_command)`. Handler извлекает из `msg["data"]` вложенную команду (`cmd`), делегирует в `command_manager.handle_command()` и отправляет ответ `process.command.response` с `correlation_id` обратно через Router. Добавлена команда `process.create` для создания процессов из inline-конфига.
- **Отклонённые альтернативы:** (1) Прямой вызов методов `start_process/stop_process` без CommandManager — теряется единообразие и метрики. (2) Отдельный endpoint на каждую команду (`process.start`, `process.stop`) — избыточное количество handlers, сложнее расширять.
- **Следствие:** Любой процесс может динамически управлять другими через стандартный Router. ACL whitelist — отложен (можно добавить позже без изменения контракта).

## ADR-PMM-008: Command args helper + public API cleanup

**Статус:** принято  
**Дата:** 2026-05-09

**Контекст:** 6+ command-методов дублировали блок `if isinstance(data, dict): kwargs.update(data)` для слияния Dispatcher args и inline dict. Методы `pause()` / `resume()` содержали ~30 дублирующихся строк. Приватные методы `_get_status()` / `_broadcast_full_status()` вызывались публично из других модулей. SHM размеры (`frame_shape`, `dtype`) хардкодились (480×640×3) вместо чтения из `shm_config`.

**Решение:**
1. `_merge_cmd_args(dispatcher_kwargs: dict, data: Optional[dict]) -> dict` — module-level helper для унификации слияния kwargs (используется 6+ раз)
2. `_send_worker_command(worker_id: int, cmd: str, **kwargs)` — helper для IPC-команд к воркерам (pause/resume/set_interval/etc)
3. `ProcessStatusMonitor._get_status()` → `get_status_for_process(pid: int)` — public метод (module-level), убрана подчёркивание
4. `ProcessMonitor._broadcast_full_status()` → `broadcast_full_status()` — public метод, обновляет процесс в реестре и broadcasting
5. SHM `frame_shape` / `dtype` читаются из `self.shm_config` вместо хардкода `(480, 640, 3)` / `np.uint8`
6. `hasattr`-guards убраны из `shutdown()` — гарантируется, что все компоненты созданы в `__init__()`

**Отклонённые альтернативы:**
- (1) Оставить `_merge_cmd_args` микро-логикой в каждом методе — дублирование кода и усложнение поддержки при изменении контракта
- (2) Сохранить `_get_status()` приватным, добавить wrapper — лишний уровень indirection

**Последствия:**
- LOC `ProcessManagerProcess`: 917 → ~800 (снижение на 117 строк за счёт удаления дублирования)
- Дублирование кода: ~90 строк → 0 (pause/resume и другие методы используют единый `_send_worker_command`)
- Новые `_cmd_*` методы: 3-4 строки вместо 8-10
- Public API чище: внешние модули вызывают явные public методы `get_status_for_process()`, `broadcast_full_status()`
- SHM конфигурация динамична: изменение размеров в `shm_config` автоматически применяется без правок в коде

## ADR-PMM-009: Семантика агрегата телеметрии процесса (state.fps/latency_ms) + system.health

**Статус:** принято
**Дата:** 2026-06-04
**Refs:** plans/telemetry-delivery-simplification.md (Task 3.1, Task 3.2)

**Контекст:** Карточки вкладки «Процессы» подписаны на `processes.{name}.state.fps`, `state.latency_ms` и `system.health.active/avg_fps/broken_wires`, но издателя этих путей не было (метрики показывали «—», «Активно: 0»). ProcessMonitor уже публиковал per-worker `effective_hz`/`cycle_duration_ms` из heartbeat, но не агрегировал их до уровня процесса/системы.

**Решение:**
1. **`processes.{name}.state.fps` = max(`effective_hz`)** по running-воркерам процесса. max выбран, т.к. у процесса обычно есть «ведущий» loop-воркер (source/pipeline), задающий темп; среднее или сумма размывались бы фоновыми воркерами (idle ~2 Гц, heartbeat). Воркеры в event-режиме (`effective_hz=None`/0) и не-running — пропускаются. Если ни один воркер не дал hz — путь НЕ публикуется (карточка остаётся «—», а не «0»).
2. **`processes.{name}.state.latency_ms` = max(`cycle_duration_ms`)** — худшая (самая медленная) итерация как консервативная оценка latency.
3. **`system.health.active`** = число running-процессов; **`avg_fps`** = среднее `state.fps` по running-процессам с известным fps (кэш `_process_fps`, guard деления на ноль — не публикуется если данных нет); **`broken_wires`** = 0 (источник WireStatus/topology runtime-у ProcessMonitor недоступен; TODO до появления реестра WireStatus в ProcessManager — данные НЕ выдумываются).
4. Тайминг цикла обобщён с IdleWorker на остальные generic loop-раннеры (`SourceProducer`/`PipelineExecutor`/`DataReceiver`) через общий `CycleMetricsRecorder` (единый контракт ключей). `pipeline_executor` переведён с lambda-target на bound-метод `run()`, иначе `WorkerManager.get_worker_status` не находил `get_cycle_metrics` через `target.__self__`.

**Отклонённые альтернативы:**
- (1) `state.fps` = sum(hz) — отвергнута: сумма по всем воркерам не отражает воспринимаемый FPS конвейера, раздувается фоновыми воркерами.
- (2) `state.fps` = hz конкретного «data»-воркера по имени — отвергнута: имена воркеров зависят от плагина, нет универсального признака «главного» воркера; max устойчивее.
- (3) Публиковать 0 при отсутствии hz — отвергнута: «0» вводит в заблуждение (выглядит как «работает, но 0 кадров»); «—» честнее отражает «метрика недоступна».

**Последствия:** Карточки получают живые FPS/latency и health без новых путей доставки (reuse существующего heartbeat→StateStore). Семантика max задокументирована в docstring `_publish_process_aggregate`. broken_wires остаётся заглушкой до интеграции WireStatus.

## ADR-PMM-010: routing-epoch — гибрид данные-refresh (switch) + стабильные очереди (restart)

**Статус:** принято
**Дата:** 2026-07-08
**Refs:** plans/2026-07-06_constructor-master/plan.md (Ф3.1), f3.1-routing-epoch.md

**Контекст:** Каждый дочерний процесс получает при спавне **замороженный снимок** routing_map (свои Queue-ссылки соседей из bundle). После `restart_process`/`apply_topology` PM создавал НОВЫЕ Queue-объекты, а выжившие соседи (protected: `gui`, `devices`; при инкрементальном diff — любой не тронутый) оставались со стейл-ссылками на осиротевшие очереди убитых процессов. `put_nowait` в мёртвую очередь возвращает успех → **тихая потеря** peer→peer трафика (задокументировано в docstring `_cmd_process_relay`). Fallback'и router'а (мост 1.1b, hub-relay 1.7) срабатывают ТОЛЬКО при ОТСУТСТВИИ очереди — а у стейл-соседа она есть (мёртвая). Жёсткое ограничение: `multiprocessing.Queue` не пиклится вне spawn → `routing.refresh` не может нести Queue-объекты, только данные.

**Решение (гибрид A+B):**
- **B (restart) — переиспользование очередей.** `SharedResourcesManager.register_process(reuse_queues=True)` создаёт только недостающие qtype; существующие Queue сохраняют `id()`. Новый инстанс наследует те же очереди через bundle, стейл-ссылки соседей остаются ВАЛИДНЫМИ, hot-path кадров не деградирует. Мусор прошлой жизни дренируется (`get_nowait` до Empty, НЕ `clear_queue` — тот спит ~0.2с/очередь). Откат: конфиг `restart_reuse_queues: false`.
- **A (switch) — декларативный refresh.** Пере-провижининг поднимает `incarnation` процесса (`_bump_incarnation`). После исполнения топологии (успех ИЛИ rollback — оба пересоздают очереди) PM поднимает монотонный `epoch` и рассылает `routing.refresh` (`communication.broadcast`, exclude_self). Payload — ПОЛНЫЙ авторитетный снимок `{epoch, hub, processes: {имя: incarnation}}` (не дельта): повторная/потерянная рассылка самовосстанавливается. Выживший ребёнок сверяет снимок со своей PSR: имя вне снимка ИЛИ incarnation ≠ локальной → `drop_process_queues` → последующий send не найдёт очередь → упадёт в существующий hub-relay (Ф1.7) → PM со свежим PSR доставит. Идемпотентно (guard `epoch ≤ last_seen → ignore`). Bundle несёт `routing_meta` — новые дети рождаются с актуальными epoch/incarnation. Гейт: конфиг `routing_refresh_enabled` (дефолт True) + env `FW_ROUTING_REFRESH != "0"`.

**Окно гонки (осознанно вне scope):** сообщения, уже лежащие в мёртвых очередях или отправленные ДО обработки refresh, теряются (окно ≈ switch + один цикл message-loop получателя; плюс краткий race, когда только что пересозданный ребёнок получает refresh раньше регистрации своего handler'а — безвредно, у него свежие очереди). Sender-side epoch-check на КАЖДОМ send — сознательно отвергнут: это hot-path кадров (`send_to_queue`), проверка epoch на каждый put недопустима. Потерянный refresh лечится следующим (полный снимок). Переполнение system-очереди рассылкой — тема Ф3.3.

**Граница с wire/SHM (Ф3.5):** routing-epoch управляет ТОЛЬКО in-process mp.Queue routing_map. SHM/wire-каналы (`wire.configure`/`wire.teardown`, FrameShmMiddleware) живут отдельным жизненным циклом и пере-issue при switch — ответственность Ф3.5, вне scope этого ADR. `routing.refresh` их не трогает.

**Отклонённые альтернативы:**
- (C) Manager-proxy очереди (сокет-раундтрип на каждый put) — недопустимо на пути кадров.
- Sender-side epoch-check на каждом send — hot-path (см. «Окно гонки»).
- Нести Queue-объекты в refresh — невозможно (`mp.Queue` не пиклится вне inheritance).
- Всегда сажать соседей на hub-relay после restart — все кадры через system-очередь PM (бутылочное горло).

**Последствия:** peer→peer send выжившего процесса после switch/restart доставляется (было — тихо терялось). Наблюдаемость: `relayed_to_hub` (окольная доставка), `routing_epoch`/`routing_refresh_applied` в `introspect.router_stats`. Полный откат к поведению main — двумя флагами (env/конфиг). Диагностический `routing.probe` даёт детерминированное воспроизведение дыры без реального железа.
