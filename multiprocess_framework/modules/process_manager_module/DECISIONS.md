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

**Последствия:** Карточки получают живые FPS/latency и health без новых путей доставки (reuse существующего heartbeat→StateStore). Семантика max задокументирована в docstring `_publish_process_aggregate`. ~~broken_wires остаётся заглушкой до интеграции WireStatus.~~ **Обновлено (Ф3.5, ADR-PMM-012):** `broken_wires` больше НЕ заглушка — считается из `ProcessManager._active_wires` + OS-liveness endpoint'ов.

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

## ADR-PMM-011: self-reported ready через per-process mp.Event (вне message-loop)

**Статус:** принято
**Дата:** 2026-07-08
**Refs:** plans/2026-07-06_constructor-master/plan.md (Ф3.2), f3.2-self-reported-ready.md

**Контекст:** Ребёнок не сообщал PM о завершении `initialize()`. switch-барьер `_wait_started_ready` был death-watch: здоровое переключение ВСЕГДА ждало весь settle-window `start_ready_timeout_s` (дефолт 0.5с), `True` означал «не умер», а НЕ «готов». Boot-барьера не было вовсе — PM выставлял `_system_ready_event` сразу после своего `initialize()`, хотя дети могли ещё инициализироваться (докстринг `system_launcher` прямо выносил это в Ф3.2). Требовалось: switch/boot закрывается по факту готовности, а не по таймеру.

**Жёсткое ограничение (дедлок):** heartbeat/любое IPC-сообщение и `topology.apply` обрабатываются ОДНИМ `message_processor`-потоком PM. Блокирующе ждать IPC-`ready` в барьере НЕЛЬЗЯ — поток заблокировал бы сам себя (комментарий `process_manager_process.py`).

**Решение:** `ready` — НЕ IPC-сообщение, а per-process `multiprocessing.Event`.
- PM создаёт event при спавне (`ProcessRegistry.create_and_register`), кладёт его в bundle `custom["ready_event"]` (inheritance при spawn — легально, как `stop_event`; bundle никогда не ре-сериализуется на стороне PM), хранит ссылку у себя (`_ready_events`, `get_ready_event`).
- Runner ставит event сразу после успешного `initialize()`, ДО `_run_lifecycle` (guard None → фолбэк на death-watch для SRM-mode/старых bundle).
- Барьер (`_wait_processes_ready`, общий для switch/boot/restart) поллит 0.05с: event set → `True` немедленно (ранний выход); процесс мёртв → `False`; живой-без-event на дедлайне → `True` + WARNING «liveness-fallback» (прежнее поведение, mock без event тоже сюда).
- **switch:** `_wait_started_ready` — window `start_ready_timeout_s` (0 → выкл).
- **boot:** `_wait_boot_ready` в `initialize()` PM ПЕРЕД `_system_ready_event.set()` — window `boot_ready_timeout_s` (дефолт 5.0с; 0 → выкл). Это initialize-поток, НЕ message_processor → блокировка допустима. По таймауту система стартует ВСЁ РАВНО (boot не блокировать навсегда) + WARNING.
- **restart:** свежий event на каждый (пере)спавн (новый объект, НЕ `.clear()` — у прежнего инстанса могла остаться ссылка на старый); после start — барьер на один процесс.
- `ready_event` в `_CUSTOM_EXCLUDE_KEYS` монитора (mp.Event не пиклится через Queue при broadcast'е состояния).

**Отклонённые альтернативы:**
- (1) IPC-сообщение `ready` от ребёнка + блокирующее ожидание в барьере — **дедлок** message_processor (heartbeat и topology.apply — один поток).
- (2) Первый heartbeat как признак готовности — тот же дедлок (heartbeat обрабатывается message_processor'ом).
- (3) `ready_event` отдельным Process-аргументом (как stop_event) — рабочий, но лишний позиционный аргумент top-level функции; bundle custom проще и уже несёт connection-данные (inheritance для custom-values так же валиден).

**Последствия:** здоровый switch/boot закрывается по факту готовности, а не по фиксированному settle-window; медленный ребёнок (ML-веса) не ломает boot (liveness-fallback + WARNING). Обратная совместимость: bundle без `ready_event` и mock-реестр без `get_ready_event` → чистый фолбэк на прежнее death-watch поведение (существующие тесты зелёные без правок). Полный откат: `start_ready_timeout_s: 0` (switch-барьер выкл) + `boot_ready_timeout_s: 0` (boot как на main) — event-механика пассивна без потребителей.

## ADR-PMM-012: wire-статусы first-class — re-issue при рестарте + honest broken_wires

**Статус:** принято
**Дата:** 2026-07-08
**Refs:** plans/2026-07-06_constructor-master/plan.md (Ф3.5), f3.5-wire-status.md

**Контекст (два независимых SHM-механизма кадров — НЕ путать):**
- **A. generic data-path** (живой поток камеры): `FrameShmMiddleware` в конструкторе
  процесса; receiver берёт `shm_actual_name`/`owner` per-frame из каждого сообщения.
  **Самовосстанавливается** при рестарте (middleware пересоздаётся, имя едет в каждом
  msg) — это территория routing-epoch Ф3.1 (ADR-PMM-010).
- **B. wire.\* абстракция** (PM-управляемые «провода»): статический `FrameShmMiddleware`,
  подключаемый через `wire.configure`, трекается в дочернем `_wire_middlewares`.
  Заводится **ТОЛЬКО из GUI** (`TopologyBridge.connect_wire` → `wire.setup`) — в
  headless-рецепте путь B пуст (`_active_wires == {}`). При рестарте новый инстанс
  рождается с ПУСТЫМ `_wire_middlewares` → провод B висит на мёртвом процессе. Это баг.

`broken_wires` был захардкожен `0` (ProcessMonitor не имел источника истины);
GUI/telemetry не видели оборванных проводов.

**Решение:**
1. **Wire re-issue (путь B).** `ProcessManager._reissue_wires_for(process)` перебирает
   `_active_wires`, где процесс — source или target, и переигрывает `wire.configure`
   **только в перезапущенный инстанс** (роль sender/receiver, сохранённый `shm_config`).
   Партнёр не трогаем: он читает per-message `shm_actual_name` и остаётся валиден.
   SHM-регион owner-scoped и переживает рестарт (`restart_process` зовёт
   `register_process(reuse_queues)`, а НЕ `unregister_process` — SHM не освобождается),
   поэтому переаллокация SHM не требуется. Вызовы: в `restart_process` после
   `_wait_processes_ready`, в `apply_topology` success-ветке после readiness-барьера.
   Ортогонально epoch/ready (Ф3.1/Ф3.2) — инварианты не тронуты. Гейт: конфиг
   `wire_reissue_enabled` (дефолт True).
2. **Honest broken-marking.** `_mark_wires_broken_for(process)` помечает задетые провода
   `status="broken"` ДО пересоздания инстанса (в restart — после `remove_process`; в
   switch — на входе, по snapshot). После успешного re-issue → `"active"`. Даёт
   `broken_wires ≠ 0` в момент разрыва (acceptance).
3. **Реальный broken_wires + system.wires.\*.** `ProcessMonitor._publish_wires` публикует
   per-wire `system.wires.<key>.status` (active/broken/pending) и агрегат
   `system.health.broken_wires`. Провод broken, если `status=="broken"` ИЛИ endpoint
   не `is_alive`. **Liveness — через `ProcessRegistry.is_alive` (OS-факт), НЕ status-снимок
   state-дерева:** после graceful stop/restart монитор не всегда промотирует
   `stopped→running` (whitelist промоушена), из-за чего живой процесс ложно выглядел бы
   мёртвым endpoint'ом и `broken_wires` застревал ≠0.

**Граница A vs B (live-верификация):** «кадры снова идут» после рестарта проверяется
на пути A (`test_routing_epoch_live` — peer→peer доставка после restart; A и так
самовосстанавливается через routing-epoch). Ф3.5-специфику (honest broken_wires +
re-issue провода B) — на **синтетическом** wire (`test_wire_status_live`: `wire.setup`
devices→preprocessor, `process.stop` peer → `broken_wires≥1`, `process.restart` →
re-issue → `0`). Реального B-провода в headless-рецепте нет — не выдумываем.

**Отклонённые альтернативы:**
- Liveness endpoint'ов через status-снимок state-дерева — отвергнут: stale `stopped`
  у живого процесса после restart → ложный broken, acceptance не восстанавливался.
- Переаллокация SHM при каждом re-issue — не нужна: регион переживает рестарт (нет
  `unregister_process`).
- Re-issue `wire.configure` в оба endpoint'а — избыточно: партнёр не терял middleware,
  читает per-message `shm_actual_name`.

**Последствия:** GUI-провода (путь B) восстанавливаются после рестарта/switch (было —
висели на мёртвом инстансе); `broken_wires` честный (≠0 в разрыв, 0 при живой топологии,
а не безусловная константа). Полный откат: `wire_reissue_enabled: false`. Замечание:
монитор оставляет stale `state.status="stopped"` у пере-restart'нутого процесса
(отдельная латентная проблема промоушена статуса) — на broken_wires не влияет благодаря
is_alive-liveness.

## ADR-PMM-013: Supervisor v2 — окно стабильности, per-process policy, health=failed, fault-injection (2026-07-08)

- **Контекст (Ф3.6/3.7/3.8):** авто-рестарт (ADR-PMM-004) имел ПОЖИЗНЕННЫЙ счётчик
  попыток (`_restart_counts:int`) — редкие краши за всё время системы копились к
  give-up даже у здорового процесса. Политика была ГЛОБАЛЬНОЙ (одна на монитор), нельзя
  включить рестарт точечно. Give-up писал только `state.status="failed"`, а acceptance
  и вкладка «Процессы»/QoS читают `health.status`. И — латентный баг: путь монитор→
  авто-рестарт живьём никогда не гонялся (юнит-тест ловил лишь факт отправки IPC).

- **Решение:**
  1. **Окно стабильности N/T.** `_restart_counts:int` → `_restart_history:list[float]`
     (метки `time.monotonic()` — важна монотонность, не системные часы). `count` = число
     меток В ОКНЕ `RestartPolicy.window_sec`; give-up при `count >= max_retries` в окне.
     Протухшие метки отбрасываются (защита от вечной flap-петли и от преждевременной
     сдачи). `window_sec=0` → пожизненный счётчик как раньше (обратная совместимость).
  2. **Reset при стабильной работе.** `_running_since` (monotonic) — процесс держит
     "running" дольше `window_sec` → `reset_restart_count`. `window_sec=0` → авто-reset
     выключен (осознанный пожизненный счётчик).
  3. **Per-process policy.** `_resolve_policy(name)` резолвит `restart_policy` из
     `ProcessManager._process_configs[name]` (верхний уровень proc_dict, рядом с
     `protected`) — непустой dict перекрывает глобальную `self.restart_policy`, пустой/
     битый → фолбэк на глобальную. Монитор читает live `_process_configs` (как
     `_active_wires` в ADR-PMM-012), без своей копии. Gates `_handle_dead_process`/
     `_check_heartbeat_timeout` тоже резолвят per-process → рецепт включает source/hub
     при выключенной глобальной (дефолт `enabled=False` — прод безопасен).
  4. **Blueprint-канал.** `ProcessConfig.restart_policy` (blueprint) + `ProcessLaunchConfig.
     restart_policy` → `build()` выносит непустой на верхний уровень proc_dict (пустой не
     меняет форму). Рецепт задаёт политику per-process.
  5. **health=failed при give-up.** Give-ветка публикует `processes.<name>.health.status=
     "failed"` + `degraded_reason` + `updated_at` (контракт `process_module/health/schema.py`).
     `state.status` оставлен (обратная совместимость). Не конфликтует с honest
     `broken_wires` Ф3.5 (`system.wires.*` — иное поддерево).
  6. **Fault-injection.** `pid` в `introspect.status` (`os.getpid()` внутри процесса —
     честная наблюдаемость) + `BackendHarness.kill_child(name)` = SIGKILL по pid.
     Постоянная фикстура `test_fault_injection_live` (порт 8783): boot camera_0 с
     per-process policy → SIGKILL → авто-рестарт → новый pid. SIGKILL (crash), а НЕ
     `process.stop` (graceful → exitcode 0 → рестарт не триггерится).
  7. **Фикс self-IPC рестарта.** `_dispatch_due_restarts` слал `type="system"` c обёрткой
     `process.command`, но после регистрации `process.command` как CM-команды (P4.4.1 B2)
     kind-router зовёт CM только при `type="command"` → авто-рестарт молча не срабатывал.
     Теперь монитор шлёт прямую `process.restart` (`type="command"`, форма как
     `build_command_message` — доказанно рабочий driver-путь `test_routing_epoch_live`).

- **GATE G1 (владелец 2026-07-08: ДА).** RestartPolicy включён per-process для source/hub
  (`camera_0` phone_camera/hikvision) в обоих рецептах; gui/devices — protected, монитор
  их и так skip. Митигация рисков прода: give-up виден в health-дереве, окно N/T ловит
  flap, откат = флаг в рецепте.

- **Отклонённые альтернативы:**
  - Копия `_process_configs` в мониторе — отвергнута: live-чтение исключает рассинхрон.
  - Сохранить `process.command`-обёртку (с `type=command`) для self-IPC — отвергнута:
    прямая `process.restart` проще и совпадает с рабочим driver-envelope.
  - Пожизненный счётчик оставить дефолтом — отвергнут: копил give-up у здоровых.

- **Валидация Ф3.8.** Полный boot hardware-рецептов headless невозможен (блок на
  подключении железа — phone gateway/RTSP/robot TCP → `wait_until_ready` timeout, qt
  недоступен). Проверено вместо boot: recipes load + реальный путь сборки base⊕recipe→
  normalize→`BlueprintAssembler.assemble` даёт валидные proc_dict с `restart_policy` на
  camera_0 top-level; сам механизм смерть→авто-рестарт доказан живьём на эквивалентном
  source (`test_fault_injection_live`).

- **Последствия:** супервизор устойчив к flap (окно), включаем точечно (per-process),
  give-up наблюдаем (health), авто-рестарт де-факто работает (фикс type). Откат: убрать
  `restart_policy` из рецептов (или `enabled:false`); `window_sec=0` возвращает пожизненный
  счётчик.

## ADR-PMM-014: Fencing-token — жёсткий барьер против stale от заменённого инстанса (Ф4.2, 2026-07-08)

- **Контекст.** Требование владельца (2026-07-08): у каждого процесса свой id; при смене
  топологии старые процессы не должны вкидывать данные/сообщения в новую. ADR-PMM-010
  ввёл `incarnation`/`epoch`, но применял их лишь к CLEANUP очередей (выживший сбрасывает
  стейл-очередь) и к самому `routing.refresh` (guard `epoch<=last_seen`). Оставалось
  задокументированное ОКНО ГОНКИ: билет, отправленный старым инстансом до пересоздания,
  мог проскочить в handler.

- **Решение.** Fence поверх конверта в receive/send-pipeline (тот же, что реестр
  контрактов Ф4.2). Код фабрик — `message_module/fencing/` ([ADR-MSG-009]
  (../message_module/DECISIONS.md)); здесь — интеграция с routing-epoch и семантика.
  1. **Штамп (send-mw).** Каждый control-plane билет получает `_fence={sender, inc, epoch}`,
     где `inc`/`epoch` — из своей PSR-записи (`routing_incarnation` проставлен при spawn
     в `bundle_builder`; `routing_epoch` растёт с применёнными refresh). Data-plane (кадры)
     НЕ штампуется (горячий путь). Свой incarnation неизвестен → не штампуем (fail-open).
  2. **Дроп (receive-mw).** Билет отбрасывается, если `_fence.inc < PSR[sender].
     routing_incarnation` — прислал СТАРЫЙ инстанс отправителя (его заменил новый с
     incarnation+1). Получатель знает текущий incarnation соседа из `routing.refresh`.
  3. **Проводка** — `BuiltinCommands._register_message_guards` за флагом `FW_FENCE`
     (дефолт ON, откат `FW_FENCE=0`). Счётчик `fence_dropped` в router-stats.

- **КЛЮЧЕВОЙ УРОК (live e2e, как в Ф3.7): дроп по incarnation, НЕ по epoch.** Первая
  реализация дропала по глобальному epoch (`epoch < known`). Юниты зелёные, но
  `test_routing_epoch_live` покраснел: epoch — счётчик поколения ВСЕЙ топологии, растёт
  на любой switch/restart; в переходном окне ТЕКУЩИЙ процесс, ещё не применивший refresh,
  штампует отставший epoch, и получатель с новым epoch ложно дропает его легитимный
  state/telemetry. Incarnation же меняется ТОЛЬКО при пересоздании очередей КОНКРЕТНОГО
  процесса (`_bump_incarnation`: restart-no-reuse `ids_before!=ids_after`, provision при
  switch) → устаревший инстанс отличим точно, текущий (даже отставший по epoch) не
  трогается. Мораль: юнит «сообщение отброшено» ≠ доказательство корректной семантики;
  истину вскрыл только живой прогон с реальной сменой топологии.

- **Композиция с ADR-PMM-010.** Fence — ужесточение epoch-guard'а с одного сообщения
  (`routing.refresh`) до всех control-plane, но по incarnation. Cleanup-очередей остаётся
  (закрывает «очередь мертва»); fence закрывает «старый инстанс ещё шлёт». Два слоя, не
  дубль. `restart-reuse` (incarnation НЕ меняется) корректно НЕ фенсится — сообщения
  старого инстанса летят в ту же переиспользованную очередь, что читает новый.

- **Валидация.** `backend_ctl/tests/test_fencing_live.py` (порты 8790/8791): restart с
  `restart_reuse_queues=false` бампит incarnation `preprocessor` → умирающий старый инстанс
  шлёт heartbeat/state.set с `inc=0` → ProcessManager (знает `inc=1`) дропает (наблюдали
  11 дропов), `fence_dropped>=1` (GREEN); при `FW_FENCE=0` те же билеты проходят
  (`fence_dropped==0`, RED). `routing_epoch_live` зелёный (нет ложных дропов). Юниты:
  `message_module/tests/test_fencing.py` + `process_module/tests/test_message_guards.py`.

- **Последствия / откат.** Жёсткая гарантия «заменённый инстанс не вкидывает в новую
  топологию». Откат — `FW_FENCE=0` (hot-path не затронут ни в каком режиме — data-plane
  не штампуется). Data-plane fence — Ф7 G.4 под флагом; `epoch` остаётся в штампе для
  диагностики и Ф4.9 (StateStore-ревизии — тот же монотонный счётчик).

- **Отклонено:** дроп по глобальному epoch — ложные дропы легитимного control-plane в
  переходном окне (см. урок). Sender-side epoch-check на каждом send для data-plane —
  отвергнут ещё в ADR-PMM-010 (горячий путь кадров).

- **Известная граница (ревью 2026-07-10, PLAUSIBLE).** Restart с `reuse_queues=True`
  (дефолт) осознанно НЕ бампит incarnation (`ids_before == ids_after`) — и в edge-случае,
  когда `stop_process` не добил старый инстанс (зомби), два инстанса штампуют ОДИНАКОВЫЙ
  incarnation: fence их не различит. Fence и не помог бы — очереди общие (переиспользованы),
  оба пишут в один канал. Защита от зомби — уровень ProcessTreeGuard/stop-подтверждения
  (topology-switch-hardening: ensure-stopped + подтверждение смерти), не fencing. Фиксируем
  как границу дизайна, чтобы будущий диагноз «stale после restart-reuse» не искал дыру
  в fence там, где её нет.

## ADR-PMM-015: Авто-рестарт ВСЕХ процессов по умолчанию + громкие supervisor-события (Ф4-добор, 2026-07-09)

- **Контекст.** Требование владельца (2026-07-08): конвейер работает только целиком —
  частичная живучесть = ложная надёжность. Сделать ВСЕ процессы автовосстанавливаемыми
  (не только source/hub из G1), а не точечно per-recipe. Механизм Ф3.6 (per-process
  policy, окно N/T, give-up, health) уже готов — включить = в основном конфиг. Риск
  маскировки багов авто-рестартом СНЯТ решением владельца «громко ВСЕГДА»: каждое
  падение/рестарт/восстановление/give-up громко видно, баг не прячется.

- **Решение (две части).**
  1. **Default-on.** PM при отсутствии `restart_policy` в конфиге строит глобальную
     `RestartPolicy(enabled=True)` (было `None`→`enabled=False`). Все non-protected
     процессы без своего рецепт-флага теперь авто-рестартятся. Protected (gui/PM) монитор
     всё равно skip (`_try_auto_restart`); per-process рецепт перекрывает; окно give-up
     Ф3.6 (`max_retries`/`window_sec`) ловит crash-loop. Дефолт `RestartPolicy` dataclass
     остаётся `enabled=False` (юниты с явным `RestartPolicy()` не затронуты). Откат:
     env `FW_AUTORESTART=0` или `restart_policy.enabled` в конфиге.
  2. **Громкие supervisor-события.** `ProcessMonitor._emit_supervisor_event` публикует
     `processes.<name>.supervisor.{event,reason,attempt,at}` в StateStore (GUI/подписчики)
     + громкий лог. События: `crashed` (`_handle_dead_process`), `unresponsive`
     (`_check_heartbeat_timeout`), `restarting` k/N (`_try_auto_restart` план), `gave_up`
     со счётчиком (give-up), `recovered` (`_check_heartbeats` alive-ветка). **Детект
     «recovered» — по ВОЗВРАТУ heartbeat**, не по статус-переходу: `_last_heartbeat`
     сбрасывается при рестарте (`_dispatch_due_restarts`), первый heartbeat нового
     инстанса — однозначный сигнал живости (после рестарта `prev_status="crashed"` не
     проходит промоушен в «running», поэтому статус-переход ненадёжен). Реестр
     `_pending_recovery` (add при план-рестарте, discard при recovered/give-up/forget).

- **Дедуп crash-loop.** Окно give-up само схлопывает всплеск: ≤`max_retries` событий
  `restarting` + одно `gave_up` со счётчиком «N рестартов за Tс», а не поток из десятков
  строк. Отдельный throttle не нужен — это и есть «счётчик, а не 47 строк» из требования.

- **Валидация.** Юниты `test_process_monitor.py::TestSupervisorEvents` (crashed/restarting/
  attempt/gave_up/recovered/forget через реальный StateStoreManager). Live
  `backend_ctl/tests/test_autorestart_all_live.py`: SIGKILL `preprocessor` (non-source, БЕЗ
  per-process policy) → GREEN воскрешение с новым pid + событие `recovered`; RED
  `FW_AUTORESTART=0` → тот же kill НЕ воскрешает (дефолт выключен). Как Ф3.7: юнит «событие
  опубликовано» ≠ доказательство воскрешения по глобальному дефолту — нужен живой kill.

- **Последствия.** Все процессы живучи по умолчанию, каждый переход громко наблюдаем
  (state-путь → GUI; в Ф5 заберёт ObservabilityHub-панель, Ф5.15/5.16). Chain-level health
  (агрегат «конвейер здоров/деградировал» + факт что данные ТЕКУТ) — Ф5. Нюансы (потеря
  in-memory состояния при рестарте ML/калибровки; лавина при смерти общей зависимости →
  `depends_on` 3.9) — оставлены на Ф5. Откат — `FW_AUTORESTART=0`.

- **Отклонено:** dev/prod-флаг авто-рестарта (владелец: «громко ВСЕГДА» вместо тихого prod —
  наблюдаемость важнее приглушения). Смена дефолта `RestartPolicy.enabled` на уровне
  dataclass — отвергнута (сломала бы юниты с явным `RestartPolicy()`); флип на уровне
  композиции PM изолирован и env-откатен.

## ADR-PMM-016: SystemBlueprint/ProcessConfig/Wire переехали в topology/ (C6 c)

**Статус:** принято
**Дата:** 2026-07-11
**Refs:** plans/2026-07-06_constructor-master/c6-pipeline-engine-design.md §1.4/§5(c), docs/audits/2026-07-10_module-responsibility-duplication-map.md (реверс PM→generic.blueprint)

**Контекст:** `SystemBlueprint`/`ProcessConfig`/`Wire` — чертёж ВСЕЙ системы (много процессов + wires), но физически жил в `process_module/generic/blueprint.py` — модуле ОДНОГО процесса. Систему собирает `process_manager_module` (оркестратор), и он уже импортировал `generic.blueprint` напрямую (`process_manager_process.py:835`, `tests/conftest.py`) — ФАКТИЧЕСКИЙ реверс-паттерн «PM лезет во внутренности чужого модуля за системным артефактом», отмеченный аудитом. Предусловие снято C6 рычагом 1: `ProcessConfig.extras` развязал перенос топологии от переноса домена.

**Решение:**
1. `blueprint.py` → новый подпакет `process_manager_module/topology/blueprint.py` (git mv, история сохранена). Дом — оркестратор системы. Отдельный подпакет (не слияние с `process/topology_manager.py`): topology_manager — runtime-логика ПРИМЕНЕНИЯ топологии, blueprint — schema-модель (SchemaBase), разные ответственности.
2. Импорты перенесённого файла: `port`/`registry`/`generic_process_config` → `...process_module.*` (framework-internal L9→L8: process_manager_module → process_module разрешено, это НЕ реверс правила №9, которое про framework→Services/Plugins/prototype). `GenericProcessConfig`/`PluginConfig` (per-process конфиг) ОСТАЛИСЬ в `process_module`.
3. `process_manager_process.py:835` — реверс-импорт `generic.blueprint` заменён на `topology.blueprint` (причина переноса устранена).
4. Back-compat: `process_module/generic/blueprint.py` — переходный ре-экспорт-шим. Пакетный re-export в `generic/__init__.py` СНЯТ (создавал runtime-цикл generic→topology→plugins→generic; 0 импортёров символов из пакета generic, только из `.blueprint`-подмодуля). Все call sites (framework + prototype, ~13 файлов) мигрированы отдельными follow-up коммитами на `topology.blueprint`; `grep generic.blueprint` в коде вне шима = 0.

**Отклонения от дизайна:** нет (дизайн-дефолт Q3 — `topology/blueprint.py` — принят).

**Последствия:**
- Системный артефакт живёт у своего владельца (оркестратора); реверс-паттерн PM→внутренности process_module снят.
- `process_manager_module` импортирует `process_module` (L9→L8) для per-process конфига — прямой разрешённый framework-internal путь, а не «лазание внутрь».
- sentrux: quality 7086→7089, dsm above_diagonal=0 (clean layering), check_rules 0 нарушений — шим-ребро process_module.generic.blueprint→process_manager не флагается как цикл/реверс.
- Reversible: yes — git mv обратим; шим снимается, когда владелец подтвердит, что переходный период закрыт. Risk: medium — широко трогает порядок импортов, runtime-цикл разрешён декаплингом generic/__init__ (оба порядка импорта проверены, framework 3909 + prototype зелёные).

## ADR-PMM-017: join/inspector — структурный вывод из wires вместо hoist из metadata (Ф4.7, 2026-07-12)

**Статус:** принято
**Дата:** 2026-07-12
**Refs:** plans/2026-07-06_constructor-master/plan.md (Ф4.7), `topology/blueprint.py::SystemBlueprint.infer_missing_inspectors`

**Контекст:** GUI при сохранении рецепта кладёт `inspector` под `metadata` (домен-entity `Process` не имеет типизир. поля `inspector` → `_fold_extra_into_metadata` сворачивает туда), а бэкенд читает `ProcessConfig.inspector` (прямой ключ). До Ф4.7 разрыв чинил `_hoist_inspector_from_metadata` — raw-dict хак в `launch.py::unwrap_recipe`, поднимавший `inspector` из `metadata` в прямой ключ ДО `SystemBlueprint.model_validate` (`extra="ignore"` иначе молча роняет всю `metadata`). Хак — чистое перемещение поля: не знал ПОЧЕМУ узлу нужен join, не проверял его против графа, был вшит в один конкретный loader (`unwrap_recipe`), а не в сам сборщик (`BlueprintAssembler`).

**Решение:**
1. **Правило.** Процесс получает `{mode: join, inputs, primary}` автоматически, если получает REQUIRED-порт(ы) (`Port.optional is False`) от **≥2 разных процессов-источников** (считаем процессы, не wires/порты — один источник может слать несколько полей одним item, см. docstring `infer_missing_inspectors`). Опциональные порты (триггеры/best-effort сигналы) в счёт не идут — иначе false-positive join там, где раньше был legitimate fanin (живой пример: `layout`/`points` — 2 источника, но входы optional → остаются fanin).
   - **Граница правила:** это НЕОБХОДИМОЕ структурное условие «нужна корреляция по seq_id», но не гарантия семантической полноты — правило не знает, ПОЧЕМУ вход required, только ЧТО он required у ≥2 источников.
2. **Escape-hatch: явный `inspector` отключает вывод.** Прямой typed-ключ `inspector` ИЛИ `extras["inspector"]` на процессе — приоритетнее и вывод из wires НЕ применяется (`infer_missing_inspectors` проверяет это первым, до подсчёта источников). Выразительность fanin НЕ отрезана: легитимный multi-source fanin (например, узел с несколькими required-источниками, которым НЕ нужна join-корреляция, а нужен именно fanin) обязан объявить `inspector: {mode: fanin}` явным прямым ключом в рецепте — тогда структурный вывод не сработает.
3. **Известный edge (a): тег входа = source-порт, совпадает с runtime `data_type` только по конвенции.** Тег входа берётся из имени SOURCE-порта wire (`item.setdefault("data_type", "frame")`, конкретные плагины переопределяют своим output-портом — `line_filter.overlay`), а не из target-порта получателя (см. `center_crop.trigger_in` ← источник `line_filter.overlay`, тег "overlay"). Это работает, ПОТОМУ ЧТО в кодовой базе действует конвенция «имя output-порта плагина == emitted `data_type`» — конвенция, не проверяемый инвариант. Плагин, чей output-порт называется иначе, чем `data_type`, который он реально ставит в item (например порт `"mask"`, но `item["data_type"] = "overlay"`), даст **расхождение** `inputs` ↔ реальная корреляция: `JoinInspectorManager` будет ждать `data_type`, который никогда не придёт под этим именем → вторичный вход НЕ сольётся. Деградация — НЕ крэш: по `timeout_sec` join эмитит то, что успел собрать (как минимум `primary`), т.е. молчаливый passthrough одного primary-входа вместо полного join — тот же класс тихой деградации, который Ф4.7 должен был устранить для «правильно расположенного» `inspector`, но здесь источник иной (несоблюдение конвенции именования портов у плагина, а не расположение поля в рецепте).
4. **Известный edge (b): два источника с одинаковым тегом → join с ОДНИМ входом.** Если оба источника, feeding один target, дают ОДИНАКОВЫЙ тег (например, две камеры, у обеих source-порт `"frame"` — дефолт `data_type`), `unique_tags` схлопывается в один элемент (`{"frame"}` после `set()`). Узел всё равно получает `mode: join` (≥2 процессов-источников), но `inputs=["frame"]` — `JoinInspectorManager` эмитит, как только ПЕРВЫЙ прибывший item даёт `data_type="frame"`, не дожидаясь второго источника. **Это меняет runtime-поведение относительно прежнего дефолта:** раньше (без explicit inspector) такой узел был plain fanin — каждый item от каждого источника форвардился независимо, без seq_id-буферизации/ожидания. Теперь — join с вырожденным `inputs`, который ждёт (до `timeout_sec`) хотя бы один item с тегом `"frame"`, что по факту ближе к "любой из двух" вместо "оба". Митигация — тот же escape-hatch (п.2): рецепт с двумя одноимённо-тегированными источниками, которому НУЖЕН честный fanin, обязан объявить `inspector: {mode: fanin}` явно.
5. **Escape-hatch должен переживать GUI round-trip: `inspector` едет через `extras`, не `metadata` (AU-2, 2026-07-12).** Escape-hatch из п.2 работает, только если явный `inspector` доезжает до `SystemBlueprint` как прямой typed-ключ ИЛИ `extras["inspector"]`. Домен-entity редактора (`multiprocess_prototype/domain/entities/process.py::Process`, `extra="forbid"` + `_fold_extra_into_metadata`) НЕ типизирует `inspector` и раньше сворачивал плоский `inspector:` в `metadata` — а `infer_missing_inspectors` читает `metadata.inspector` только как источник ТОНКОЙ НАСТРОЙКИ (`timeout_sec`/…); `mode`/`inputs`/`primary` авторитетны из wires (п.3). Следствие: первый же GUI-save стирал авторитетность ручного `{mode: fanin}`, и узел деградировал в структурный вывод. **Фикс:** домен-entity `Process` получил typed-поле `extras` (симметрия `ProcessConfig.extras`, ADR-PM-014/рычаг C6a) и роутит framework-shorthand ключи (`inspector`/`source_target_fps`/`io_peek`) в `extras`, а не `metadata` — так `inspector` переживает `to_dict`/`from_dict` и остаётся escape-hatch'ем (`_EXTRAS_SHORTHAND_KEYS`, приоритет явного `extras`/`metadata` + conflict-warning). **Задокументированная деградация случая (б):** legacy-рецепт с `metadata.inspector: {mode: join}` на узле БЕЗ структурного join (< 2 required-источников — напр. один required + optional-порты) тихо остаётся `fanin`: вывод не срабатывает, а тонкая настройка подмешивается только внутри join-ветки, поэтому `mode` из `metadata` теряется целиком. `metadata`-mode НЕ авторитетен ни при наличии, ни при отсутствии структурного join — это граница, не баг; митигация — перенести `inspector` в прямой ключ/`extras` (после фикса AU-2 GUI делает это сам).

**Отклонённые альтернативы:**
- **Оставить `_hoist_inspector_from_metadata`.** Отвергнуто: (1) чинил СИМПТОМ (метаданные не там), не делал join самопроверяющимся свойством графа — рецепт без ЛЮБОЙ inspector-декларации (ни прямой ключ, ни metadata) молча оставался fanin, хотя wires однозначно требовали join; (2) жил в `launch.py::unwrap_recipe` — прототип-специфичном raw-dict loader'е, ВНЕ `BlueprintAssembler` (framework-чистого сборщика) — корректность зависела от того, что КАЖДЫЙ путь построения blueprint dict (boot, switch/hot-apply, будущие вызовы) не забудет вызвать именно эту функцию первой; assembler же гарантированно проходит через `SystemBlueprint.model_validate` независимо от вызывающей стороны; (3) чистое перемещение поля — не сверялось с графом wires, поэтому устаревший/неверный `metadata.inspector` (например, после правки топологии без пересохранения GUI) тихо переживал бы рассинхрон с реальными связями сколь угодно долго; структурный вывод самокорректируется при каждой сборке.
- **Дропать неоднозначные случаи (например, тег-коллизию п.4) с ошибкой валидации вместо тихой деградации.** Отвергнуто для Ф4.7: усложнило бы `check()` эвристикой «это плохой join или нормальный» без доп. данных от рецепта; эскейп-хетч (явный `inspector`) уже даёт автору рецепта детерминированный способ обойти вывод. Зафиксировано как известная граница (п.4), не как TODO — если понадобится строгая валидация, это отдельная задача.

**Последствия:** join — структурный факт графа wires, не зависящий от того, куда/попал ли вообще `inspector` в рецепт; `_hoist_inspector_from_metadata` удалён (не закомментирован). Оба известных edge (п.3/п.4) — не баги, а задокументированные границы конвенции «имя source-порта == data_type»; выход за них требует явного `inspector` в рецепте. Полный откат — не предусмотрен отдельным флагом (в отличие от ADR-PMM-010/014/015): вывод чисто аддитивен (срабатывает только при ОТСУТСТВИИ явного `inspector`), откат для конкретного узла — явно объявить `inspector` в рецепте.
