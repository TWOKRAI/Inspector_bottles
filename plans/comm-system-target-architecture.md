# Целевая архитектура коммуникаций фреймворка-конструктора

> Финальный план-документ. Основан на доказательной базе: 13 карт подсистем в каталоге salvage (`envelope-field-mapping`, `statestore-transport`, `ipc-channel-map`, `request-reply boundary`, `lifecycle-bridge`, `prototype-communication-map`, `buses-action`, `pipeline-communication-boundaries`, `Channel Communication Map`, `process_communication_boundary_map`, `comm-systems-census`, `Services Communication Architecture`, `queue-registry-addr-boundary`) + 7 сквозных анализов (concerns) + проверенные вердикты фазы 3. **Подсистемы `process_manager_module`, `shared_resources_module`, `channel_routing_module` (базовый CRM), `data_schema_module`, `registers_module` фигурируют в каталоге как scope находок, а не как отдельные карты — их способности учтены в §9 наравне с остальными.**
> Принципы владельца: **это не переписывание, а сборка уже написанного в ОДНУ систему**; минимальные элегантные ходы; «не используется ≠ не нужно» (удаляем только доказанный дубль); один лучший механизм на сценарий; **простота и debuggability — критерий качества наравне с полнотой**.
> Дата: 2026-06-02.
> **Ревью пройдено (2026-06-02):** независимое мульти-агентное ревью — **B+ / 8 из 10, approve-with-changes** (грани 8/8/8/7/7, 35 проверок по коду, 7 находок ревьюеров опровергнуто). Все M/S/G-правки внесены. Полный вердикт — [`comm-system-target-architecture.REVIEW.md`](comm-system-target-architecture.REVIEW.md).
>
> **Дисциплина статусов (важно для §9):** `preserved`/`absorbed`/`capability`/`intentionally-dropped` описывают, ГДЕ функционал ЖИВЁТ или окажется после унификации. Где функционал ещё НЕ написан в победителе (5 фич ActionBus, persistent SQL-log) — статус **`capability-to-build`** (это план, не текущее состояние), чтобы не выдавать желаемое за факт.

---

## 1. Резюме и вердикт по тезису

**Тезис владельца ВАЛИДЕН — с уточнением границ.** RouterManager действительно ЕДИНЫЙ хаб коммуникаций: только он несёт middleware-цепочку (send+receive), централизованную статистику, request-response и плагинный реестр каналов `IMessageChannel` (Queue/Socket/Modbus регистрируются одинаково, ядро не трогается — доказано кодом). Тезис скорректирован в одном: **хаб = слой МАРШРУТИЗАЦИИ + middleware + контракт канала**; `queue_registry` (физический транспорт `mp.Queue`) и SHM/`MemoryManager` (zero-copy кадры) — НЕ каналы хаба, а оправданные нижние/боковые слои, к которым хаб обращается (гибрид «почта» для команд + «трубы» для кадров — уже зафиксирован P2.2). Реального дубля «одна операция — разные двери» почти нет — это в основном разные уровни ответственности; но есть точечные дубли (broadcast в обход хаба, два `FrameShmMiddleware`, дубль ring-buffer-логики, два undo-движка, два reader'а `process_targets`, два command-пути Modbus, дубль ответа PM `_handle_process_command` vs `reply_to_request`) и мёртвые декларации (`routing_table`, `RouterSchemaAdapter`, `WorkerPoolDispatcher`, `ActionBus`-в-проде).

**Cross-machine — НЕ количественная оценка «90% готов».** `IMessageChannel` (push-модель) архитектурно достаточен для Redis/MCP/контроллеров без правки ядра, и это сильная сторона. Но честных блокеров до cross-machine как минимум ДВА (оба verified): (1) резолв нелокальных адресов не реализован (`routing_table`/`address_aware_channel` задекларированы, не подключены в `_resolve_channels`); (2) `RouterManager.request()` не имеет рантайм-guard на поток-вызыватель — дедлок при вызове из приёмного потока известен только из docstring (критично для cross-machine адаптеров, которые блокируются на ответе). Сегмент адреса `machine.process.worker` в коде/ADR отсутствует. Поэтому формулировка — **«архитектурно готово, два инфраструктурных блокера до первого реального адаптера»**, без процентной оценки.

Задача — **достроить периметр и убрать дубли**, а не строить новые подсистемы.

---

## 2. Карта целевой архитектуры — один канон на сценарий

Слои коммуникации (сверху вниз):
- **Доменный/GUI слой** (in-proc, prototype): EventBus, CommandDispatcherOrchestrator, GuiStateBindings.
- **Хаб маршрутизации** (framework): RouterManager — send/receive/request/broadcast + 2 dispatcher + middleware + реестр `IMessageChannel`.
- **Транспорт** (framework): `queue_registry.send_to_queue` (`mp.Queue` между процессами) + SHM/`MemoryManager` (hot-path кадров) + внешние каналы (Socket/Modbus/Redis/MCP).
- **Контракт груза**: `Message` (Pydantic value object, Dict at Boundary).

| Сценарий | Канонический механизм | Что absorb из проигравших / соседей |
|---|---|---|
| **Команда процессу** | `RouterManager.send(targets=[proc], type="command")` / `send_async` (fire-forget) | из `ProcessCommunication.broadcast` — fan-out свести к `register_broadcast_route`/`targets=["all"]` через хаб (убрать прямой вызов `queue_registry.broadcast_message`) |
| **Команда воркеру/глубже** | `targets=["proc.worker"]` (иерархическая адресация) → `_route_to_worker` + `register_worker_handler` (P2.2, live) | — (механизм уже полноценный) |
| **Синхронный request/reply** | `RouterManager.request()` (correlation_id) + авто-резолв `_resolve_pending` в `receive()`; ответ через дженерик `reply_to_request()` | из PM `_handle_process_command` — перевести bespoke-reply на `reply_to_request` с опцией вложенного `data`-конверта (контракт `process.command.response`) |
| **Кадры / data-поток** | data-путь через `queue_registry` (`{proc}_data`) + единый `FrameShmMiddleware`; приём `receive(channel_types=["data"])` | слить два `FrameShmMiddleware` (~80 строк дубля SHM-fallback) в один; SHM остаётся отдельным hot-path, не каналом хаба |
| **Реактивное состояние / телеметрия** | `StateStore` (`set`/`subscribe` → DeltaDispatcher → `state.changed`); транспорт `GuiStateProxy` (уже маршалит в Qt main thread) | per-field подписки регистров можно мостить в StateStore через `RegistersStateAdapter` (починить `get_field`-баг) |
| **Внутри-GUI событие (факт)** | `domain EventBus` + `QtEventBus` (Qt thread-marshal) | — (typed pub/sub, аналога нет; ActionBus к событиям отношения не имеет) |
| **GUI-команда + undo/redo** | `CommandDispatcherOrchestrator` (snapshot-based) | **to-build** (не absorb готового — фич нет в Orchestrator): `undo_to(id)`, `record()` внешних мутаций, pre-execute RBAC-hook, post-execute audit-callback, персистентный SQL-лог + recovery. Источник переноса — мёртвый `ActionBus` |
| **Доставка worker→main thread** | `DataReceiverBridge` (для frame/command); для state — **напрямую** `GuiStateProxy → GuiStateBindings` (убрать второй no-op hop через bridge) | multi-subscriber listener вместо single-slot `set_*_callback` (убрать closure `_state_multiplexer`) |
| **Логи / ошибки / статистика** | `LoggerManager` / `ErrorManager` / `StatsManager` поверх `channel_routing_module` (база CRM) | LoggerManager — подтверждённый prod-консьюмер RouterManager (`logger_manager.py:401` дублирует лог-записи через роутер). **Убрать мёртвый Dispatcher в LoggerManager** (§11); `StatsManager` НЕ подключён к роутеру (verified) — оставить как capability; буферы — `BatchBuffer` (logger/error, triple-trigger flush) и `AggregationWindow` (stats) реализуют `IBufferStrategy` |
| **Внешний драйвер / сервис / контроллер** | `IMessageChannel`-подкласс в RouterManager (`SocketChannel` push через `on_inbound` — образцовый; `ModbusChannel` двунаправленный для OUTBOUND) | Redis/MCP/OPC-UA добавляются подклассом `MessageChannel` без правки ядра; SQL — исключение (см. §3). **Оговорка по Modbus:** INBOUND-половина (`poll()`) НЕ доходит до хаба из-за prefix-фильтра (см. §3.2) — реальную телеметрию делает `_poll_loop` плагина мимо хаба. Образцом контроллер-канала в хабе считать `SocketChannel` (push), не Modbus, до фикса prefix |

«Главных» по сценариям шесть: **RouterManager** (IPC), **StateStore** (состояние), **SHM** (кадры), **EventBus** (in-proc события) + **CommandDispatcherOrchestrator** (GUI-команды/undo), **LoggerManager/ErrorManager/StatsManager** (наблюдаемость поверх CRM). Остальное — их транспорт/надстройка либо legacy на обсуждение.

---

## 3. RouterManager как универсальный хаб

### 3.1 Контракт `IMessageChannel` (достаточен для cross-machine)
`IMessageChannel(IChannel)`: `name`, `channel_type`, `send(msg: dict) -> dict`, `poll(timeout=0.0) -> list[dict]`, опц. `start_listening(callback)` / `stop_listening()` / `get_info()`. Регистрация: `RouterManager.register_channel()` — тонкий override (type-check + **обязательная** инъекция log-callbacks: `_attach_logger` пробрасывает ошибки канала в `LoggerManager`), **без** правки ядра. Доказано: Queue/Socket/Modbus регистрируются одинаково (`backend_ctl_endpoint.py:99`, `modbus/plugin.py:131`).

> **Контрактное требование (capability `log_injection_into_channels`, §9.1):** любой новый канал (Redis/MCP/SQLChannel) обязан получить log-инъекцию при `register_channel` — без неё ошибки канала уйдут в тишину. Это не опция, а часть контракта подключения.

**Две модели интеграции канала:**
- **Pull (poll)** — для синхронных источников (Queue, Modbus-регистры). Опрашивается в `_poll_all_channels`.
- **Push (`on_inbound`)** — для асинхронных потоков (Socket, Redis-PubSub, MCP-driver). НЕ зависит от polling-цикла и его prefix-фильтра. Это образец для всех будущих cross-machine/контроллер-каналов.

### 3.2 Подключаемые каналы
| Канал | Статус | Модель | Примечание |
|---|---|---|---|
| QueueChannel | live, ядро | pull | физический транспорт под `_deliver_by_targets` |
| SocketChannel | live (dev gate `BACKEND_CTL=1`) | push (`on_inbound`) | headless backend-control, MCP-driver ready |
| ModbusChannel | **OUTBOUND live, INBOUND сломан** | pull (`send`=OUTBOUND работает; `poll`=INBOUND зарегистрирован, но не доходит) | **NEW verified (confirmed):** канал зарегистрирован как `modbus_{unit_id}` БЕЗ префикса процесса → `poll()` не проходит prefix-фильтр `_poll_all_channels` → INBOUND-телеметрия/status/error НЕ идут через хаб; реальную работу делает `_poll_loop` плагина независимо. Для хаба канал жив только на OUTBOUND. Эталоном двунаправленного контроллер-канала считать ПОСЛЕ фикса prefix (§3.2 ниже / §12 P2) |
| Redis / MCP-backend | будущее | push (предпочтительно) | подкласс `MessageChannel`, ядро не трогается. **Pull-модель Modbus как референс для INBOUND не использовать, пока prefix не починен** — push (`on_inbound`) свободен от prefix-фильтра |
| SQL | live, **вне хаба** | — | прямой вызов из CommandManager; ввести `SQLChannel(IMessageChannel)` ТОЛЬКО при cross-machine db-запросе/observability |

> **Следствие для тезиса «двунаправленный эталон»:** до фикса prefix-фильтра Modbus НЕ является честным двунаправленным эталоном в хабе — INBOUND-половина проходит мимо. Тезис «Redis/MCP ложатся в poll()-модель» опирается на pull-путь, который сейчас сломан; для них канон — push, не pull.

### 3.3 Маршрутизация по type + адрес
Две ортогональные оси: **адрес** (`targets` → процесс/воркер/глубже) и **kind груза** (`type`/`command` → канал/очередь). Сейчас kind выводится упрощённо в `_select_queue_type` (`system` для command, иначе `data`); декларативная таблица `MESSAGE_TYPE_TO_CHANNEL` (`routing_table.py`) задекларирована, но **не подключена** в `_resolve_channels` (verified — техдолг P1).

### 3.4 Иерархическая адресация и cross-machine-готовность
`message_module.addressing` (`split_address`/`process_of`/`worker_of`/`normalize_targets`) — чистые JSON-safe функции, backward-совместимы (плоское имя `proc` == `["proc"]`). Провязано в рантайм: P2.1 cross-process (`_deliver_by_targets`) + P2.2 intra-process (`_route_to_worker` + `register_worker_handler`). **Cross-machine сегмент `machine.process.worker` ОТСУТСТВУЕТ** в коде/ADR (verdict PARTIAL: в коде/ADR нет, в planning-доке — только открытый вопрос). **«90% готов» — НЕ подтверждённая количественная оценка; снято.** Честных блокеров cross-machine как минимум два (оба verified confirmed): (1) резолв нелокальных адресов (`address_aware_channel`/`routing_table`, не подключён в `_resolve_channels`); (2) `request()` без рантайм thread-guard — дедлок при вызове из приёмного потока (только docstring), критично для блокирующихся cross-machine адаптеров.

### 3.5 SHM и WorkerPoolDispatcher — НЕ каналы хаба
- **SHM/`MemoryManager`** — оправданный отдельный hot-path: zero-copy numpy через `memoryview` (pickle кадров дорог). Кадры едут топологией in-process очередей («трубы»), команды/конфиг — через хаб («почта»). Хаб **управляет конфигурацией** SHM (через `wire.configure` middleware), но не поглощает транспорт. **Гибрид зафиксирован — оставить.**
- **WorkerPoolDispatcher** — мёртвый параллельный механизм (verified: 0 prod-потребителей, нет реализации `IRemoteExecutable`, явный запрет реанимации в `plans/processes-workers-runtime-debts.md`). Его роль (cross-process dispatch) при необходимости реализуется как `worker-handler routing` поверх того же хаба. **Не реанимировать.**

### 3.6 process_manager_module — подсистема управления процессами поверх хаба
PM (`ProcessManagerProcess`/`ProcessMonitor`) — крупнейшая подсистема-консьюмер хаба (карта с ~19 capabilities). НЕ канал, а **управляющий узел**: владеет реестром процессов, шлёт команды и broadcast'ы через RouterManager, отвечает на request'ы. Подтверждённый дефект — **дубль ответа**: `_handle_process_command` строит bespoke-response вручную (`process_manager_process.py:894-907`, success/result задублированы в envelope И в `data.*`), параллельно существует дженерик `reply_to_request`. Судьба всех 19 capabilities — в §9 (новый блок «process_manager»): спектр от `preserved` (spawn/status_broadcast/uptime/builtin-команды) до `absorbed` (bespoke-reply → `reply_to_request`). **`replace_blueprint` с snapshot-rollback — единственная atomic горячая замена процессов, прямо относится к recipe-driven launch (приоритет владельца) → preserved, НЕ потерять.**

### 3.7 shared_resources_module — единая точка ресурсов (ADR-018)
SRM (`SharedResourcesManager`/`QueueRegistry`/`ProcessStateRegistry`/`MemoryManager`/`EventManager`/`ConfigStore`) — фундамент транспорта. Ключевые capabilities и их судьба — в §9. **Подтверждённые нюансы (в §11/§12):**
- **`register_process` — фасад единой точки (ADR-018)**; обход касается именно фасада (S2 уточнение, verdict partial): `bundle_builder` обращается к `ProcessStateRegistry`/`ConfigStore` напрямую (`bundle_builder.py:63,68`), а сами очереди создаёт `process_registry._create_process` в родителе — `bundle_builder` лишь `add_queue`. → привести регистрацию к фасаду `register_process`.
- **`reinitialize_in_child` — НЕ gap (исправлено по ревью M1, verdict refuted-against-plan, high):** метод **вызывается в проде** — `process_runner.py:130-131` (`isinstance(bundle, dict)`) → `_build_shared_resources_from_bundle()` → `bundle_builder.py:128`. `else`-ветка без вызова — только тестовый SRM-mode. Статус → `preserved`. *ADR-020 устарел:* формулировка «вызывается в `ProcessModule.initialize()`» неверна — фактически делегировано в `bundle_builder`; синхронизировать ADR.
- **`release_process_memory` — отсутствует РЕАЛИЗАЦИЯ на `MemoryManager`** (M2, confirmed high): caller в PM уже готов (`process_manager_process.py:608` + warning 614-617), но метода нет (`memory/core/manager.py` имеет `release_memory`/`close_memory`/`close_all`; не объявлен и в `IMemoryManager`). Последствие реально: при `replace_blueprint` SHM остановленного процесса не очищается (утечка, только warning). P2: добавить `release_process_memory(process_name)` (итерация handles + `close_all`/`release_memory`) + абстрактный метод в `IMemoryManager`.
`system_stop_event` через `Process` inheritance, `EventManager` dual-notification (in-proc + IPC), `ProcessStateRegistry` как single source of truth для очередей — `preserved`.

### 3.8 channel_routing_module (база CRM) — инфраструктура каналов + наблюдаемость
CRM — общая база под `RouterManager`, `LoggerManager`, `ErrorManager`, `StatsManager` (thread-safe `ChannelRegistry`, `normalize_config`, `IBufferStrategy`). Ортогонален реактивности (verified: 0 связей со StateStore). **Подтверждённые проблемы (в §11):**
- **Мёртвый Dispatcher в LoggerManager** — экземпляр диспетчера создаётся, но не используется (убрать).
- **Путаница двух конфигов** `ChannelRoutingConfig` vs `ChannelRoutingManagerConfig` (похожие имена, разные роли) — задокументировать/переименовать.
- **`AsyncSenderBuffer.flush()` — no-op** (не сбрасывает буфер фактически) — починить или задокументировать как умышленный.
- **`LoggerManager` — мёртвый router-wire УДАЛЁН (M5 done 2026-06-03):** в проде `_router_manager` всегда был `None` (приёмника LOG нет), путь был чистый overhead/dead traffic. Физически убраны `enable_router_routing`/`router_manager`-параметры, `observable_config["router_routing"]`, `_router_manager`, стат `messages_routed`, `_route_via_router`, `LoggerAdapter.set_router_routing`, проброс в `ErrorManager`, `enable_router_routing=True` в `process_managers`. Логирование теперь строго in-process (CRM-каналы + BatchBuffer). Тесты 286 зелёные. **`StatsManager`**: dead wire уже убран ранее (`d684387a`, §9.7).

---

## 4. Унификация диспетчеризации key→handler

**Один движок:** `dispatch_module.Dispatcher`. CommandManager, `RouterManager.message_dispatcher`, `RouterManager.channel_dispatcher` — это ЭКЗЕМПЛЯРЫ/обёртки того же класса (composition/reuse), а НЕ конкурирующие реализации. Межсистемного дубля движка нет — заменять нечем.

> **Уточнение относительно исходного анализа (verdict PARTIAL/refuted в части «суженный контракт»):** `RouterManager.register_message_handler` — это **полный relay** в `message_dispatcher` (пробрасывает все 6 параметров без сужения), а НЕ «частичная копия с урезанным контрактом», как предполагала фаза-1. Это тонкая обёртка-делегат, не самостоятельная реализация. (Флаг `expects_full_message` — **НЕ vestigial**, исправлено по ревью M4 (refuted high): реально ветвит поведение — см. §11 п.19. Асимметрия default-ов: `register_message_handler`→`True`, `Dispatcher.register_handler`→`False`.)

| Компонент | Судьба | Обоснование |
|---|---|---|
| `Dispatcher` (EXACT_MATCH) | **канон** | O(1) lookup, 99% вызовов в проде |
| PATTERN_MATCH / FALLBACK_MATCH | **capability конструктора** | zero prod, но рабочие + протестированы, не дублируются нигде; ценны для regex/efficiency-маршрутизации в распределённых системах; пометить `@experimental` |
| CHAIN_MATCH / Scenarios | **capability** (только `ScenarioManager`-версия) | reserved-for-pipeline (vision/processing); **удалить мёртвый дубль** `ChainMatchStrategy.scenarios` (verified: заполняется только в тестах, `dispatch()` использует `ScenarioManager`) |
| `CommandManager` (prod) | **оставить** как доменный фасад (конвенция command/data + timing-метрика) | живой горячий путь, 7+ потребителей; absorb: name-returning-handler как документированный режим Dispatcher |
| `RouterManager.message_dispatcher` | **оставить** (incoming IPC) | точка диспетчеризации всех входящих |
| `RouterManager.channel_dispatcher` + `register_broadcast_route` | **оставить** (outgoing routing) | живой fan-out камер/displays |
| `RouterManager` scenario-методы (`register_message_scenario` и др.) | **обсудить** | verified: 0 prod callers; оставить тонкими relay до Phase 8 ИЛИ удалить |
| `BaseCommandManager` | **слить** | verified: test-only, дублирует `BaseDispatcher` — канонизировать `BaseDispatcher` |
| `CommandAdapter.execute_via_message` | **удалить путь** | verified: dead (ссылается на несуществующие `process.message_manager`); сам `CommandAdapter` (setup/get_stats) живёт |
| `resolve_dispatch_targets` | **НЕ трогать** | verified: это адресация процессов (register/field → `list[str]`), НЕ key→handler — другой concern |
| `update_handler_*` хардкод `default_strategy` | **fix** | verified: добавить параметр `strategy` или задокументировать ограничение |

---

## 5. Унификация команд / undo

**Вердикт: один undo-движок — `CommandDispatcherOrchestrator`** (snapshot-based, единственный живой; Ctrl+Z привязан к нему — `app.py:557`). По существу лучше `ActionBus`: snapshot+pure-apply даёт implicit rollback и не требует ручных revert-патчей (которые на сложных domain-объектах легко рассинхронить). Field-level coalescing у него **работает в проде** (verified `presenter.py:189-191` — фаза-1 ошибочно считала это уникальным для ActionBus).

`ActionBus` в production **мёртв** (verified: 0 живых `execute()`-вызовов). Доказательная база уточняет: `_legacy_action_bus` создаётся, но retained-but-unbound (`app.py:433`); `RolesPanel` получает `bus=None`, а signal `permissions_changed` подключается только `if self._bus is not None` (`roles_panel.py:110-112`) → даже формально присутствующий `execute()` в `roles_panel.py:206` **недостижим** (правки прав молча теряются); `FormContext` инстанцируется только в тестах. **Важно:** исходный claim «RolesPanel — единственный/1 живой execute()» — **REFUTED**; верное утверждение — «0 живых execute() во всём проде, включая roles_panel». Держать два undo-движка нельзя.

`CommandManager` — **НЕ участвует** в конкурсе: это IPC-слой команд процессу (worker.create, process.stop), без какого-либо undo. Совпадает только слово «Command». Слияние было бы ошибкой категорий.

**5 фич ActionBus — это `capability-to-build`, НЕ `absorbed`.** Verdict подтверждает: `undo_to(id)`, `record()` внешних мутаций, pre-execute RBAC-hook, post-execute audit-callback, персистентный SQL-лог + `ActionLogRecovery` — **отсутствуют в `CommandDispatcherOrchestrator`** (genuine features to absorb). Поэтому статус — «фичу нужно написать в победителе», а не «уже там живёт». Дополнительно:
- **RBAC-точки в Orchestrator сейчас НЕТ** (concern прямо отмечает RBAC field-edit дыру) — pre-execute hook придётся именно создавать.
- **persistent SQL-log + `ActionLogRecovery`** — у самого ActionBus dead-in-prod (0 prod), переносить нечего работающего; `ActionLogRecovery` к тому же **нарушает инкапсуляцию** (`bus._handlers` — private; verdict confirmed). Корректная судьба — `capability-to-build` при реальной потребности в crash-recovery (открытый вопрос §13), а не молчаливый перенос.

До решения absorb код `ActionBus` физически не удалять (источник переноса/референс контракта). Сам класс `ActionBus` остаётся во framework как конструктор-блок (patch-based undo с RBAC/audit для других приложений), но **выводится из живой GUI-проводки прототипа**.

---

## 6. Унификация pub/sub и состояния — два канона

Это **пять разных осей pub/sub** (разграничение задокументировано ADR-SS-001/006/012, ADR-RM-006, ADR-CRM-001), НЕ дубли:
1. **StateStore** — реактивное СОСТОЯНИЕ cross-process (дерево + дельты).
2. **EventBus/QtEventBus** — типизированные in-proc СОБЫТИЯ-факты GUI.
3. **RegistersManager** — типизированные КОНФИГИ плагинов + per-field observers + GUI `FieldInfo`.
4. **channel_routing_module** — ИНФРАСТРУКТУРНАЯ маршрутизация каналов (логи/ошибки/стат/сообщения) — ортогонален реактивности (verified: 0 связей с state_store).
5. **`Config._change_callbacks`** (пятая ось, ранее упущена) — pub/sub на уровне класса `Config` (`config_module`). Verdict уточнил: `subscribe`-механизм принадлежит классу `Config`, а НЕ `ConfigManager`/`ConfigStore` (отдельный набор `_change_callbacks`). Это самостоятельный контракт «подписка на изменение конфига», не сводимый к четырём выше.

**Два канона:** реактивное состояние = **StateStore**; in-proc события = **EventBus + QtEventBus**. Слить их нельзя — состояние «что есть сейчас» и события «что произошло» — фундаментально разные абстракции (Redux store vs event emitter). RegistersManager НЕ сливать в StateStore (ADR-RM-006 — разные задачи), но починить мост и убрать мёртвые двери. `channel_routing_module` и `Config._change_callbacks` — другие concern'ы, не трогать (каждый — `capability`, см. §9).

**Что убрать/слить (конкретно):**
- **Один dispatch регистров** — оставить прямой `CommandSender` (live); `send_register_message`/`build_routing_map` (verified: 0 prod) и `send_callback`-путь (`send_callback=None` в v3) — мёртвые двери.
- **Починить `RegistersStateAdapter.get_field`** — verified: вызов несуществующего метода (`registers_adapter.py:109`), `sync_domain_to_state()` молча падает в `except`. **При починке НЕ задеть `StateAdapterBase` с anti-loop `_pending_paths`** — это ядро всех адаптеров (Recipe/Service/Display/Camera/Registers), механизм защиты от петли domain↔state; его сохранность отдельной строкой в §9.
- **Один reader `process_targets`** — `extract_process_targets(FieldMeta|dict)` с полной 4-уровневой цепочкой; вызывают и `CommandCatalog`, и `resolve_dispatch_targets` (verified: два независимых reader'а с разными fallback'ами).
- **Хардкод `queue_type` в DeltaDispatcher** — НЕ протечка абстракции (verified refuted: это поле конверта), но при унификации kind-каналов (P3) свести к общему хелперу.

---

## 7. GUI signal-слой

Пять ортогональных направлений, каждое со своим каноном:

| Направление | Канон | Carve-out во framework | Лишнее (убрать) |
|---|---|---|---|
| (а) backend→GUI телеметрия | `GuiStateProxy` (транспорт, уже в framework) → `GuiStateBindings` (последняя миля) | **`GuiStateBindings`** — generic (нет app-типов), сильный кандидат | второй no-op hop через `DataReceiverBridge` для state (verified: `GuiStateProxy` уже маршалит в Qt main thread) |
| (б) внутри-GUI событие | `EventBus` + `QtEventBus` | **`EventBus`** (zero-Qt) — кандидат | — |
| (в) GUI-команда + undo | `CommandDispatcherOrchestrator` | требует дженерификации (привязан к `Project`/`ProjectCommand`) — отдельная работа | второй undo-движок `ActionBus` (мёртв) |
| (г) worker→main thread | `DataReceiverBridge` (frame/command) | generic IPC→Qt bridge — обсудить (Qt-завязка) | single-slot `set_*_callback` → multi-subscriber; closure `_state_multiplexer` (`app.py:249-257`) |
| (д) адресация команды плагину | `CommandSender` + резолвер `plugin_name`→register (`app.py:509-533`) | **резолвер `plugin_name`→register — кандидат во framework (`message_module`)**: активный prod-путь (`_on_plugin_config_changed` → `register_update`), universal по оценке salvage; нужен любому потребителю, не только Inspector | непоследовательность: address resolution живёт в event-listener'е, а не в `CommandSender` (вынести в резолвер при carve-out) |

**Лишние абстракции (verified):**
- `frontend/bridge.py` — **мёртвый shadow-файл**: пакет `bridge/` затеняет файл (Python отдаёт приоритет пакету); `bridge.py` никогда не импортируется, содержит расходящуюся версию (`QueuedConnection` vs `AutoConnection` в `bridge_impl.py`). **Удалить.**
- `glob_match.py` — **ручная копия** `subscription_manager._match_pattern`. Заменить импортом ПОСЛЕ публикации строкового API во framework (сейчас framework экспортирует `(tuple, tuple)`, prototype использует `(str, str)` с dot-нормализацией — прямая замена сломает `bindings.py:191`).

---

## 8. Канонический конверт сообщения

`Message` (Pydantic SchemaBase, `model_fields` = source of truth, Dict at Boundary) — единый контракт; RouterManager — единственный интерпретатор транспортных хинтов. Унификация = легализация внесхемных полей + чистка дублей.

**Минимальный контракт:** `type` (command|event|response|system|data|...), `sender`, `targets` (dotted `proc[.worker]`), `data`, `request_id`, `channel` (явный override, опц.).

**Что сделать:**
- **`request_id` — единое имя корреляции.** `data.correlation_id` оставить только как backward-shim чтения в `_extract_correlation_id` (verified: намеренный dual-write, значение всегда идентично). Новые отправители пишут `request_id`.
- **`queue_type`** — verified refuted («хардкод обходит `_select_queue_type`»): на деле `_select_queue_type` читает явный `queue_type` ПЕРВЫМ клозом. НО `event`/`response` нуждаются в `system`, а правило сейчас даёт `system` только для `command` — **расширить правило** (event/response→system) ПЕРЕД любой попыткой убрать явные хардкоды в DeltaDispatcher/PM (иначе сломается доставка). Опционально объявить `queue_type` как `Optional` поле schema (типизация когда задан, вывод из type по умолчанию).
- **`channel="data"/"system"/"queue"`** — verified refuted («чисто vestigial, удаление безопасно»): значения **активно ставятся в проде** (`source_producer.py:129`, `pipeline_executor.py:177`, `MESSAGE_TYPE_DEFAULTS['queue']`) и лечатся guard'ами (`process_communication.py:210`, `_resolve_channels:877`). Удаление — **комплексный рефактор** (убрать setters + guards + sentinel `queue` + спец-case), не точечная правка.
- **`routers`** — **удалить** (verified: 0 prod-читателей, только пишется validator'ом и исключается из LOG `to_dict`). Обновить ADR-MSG-004.
- **`subtype`** — **удалить** (verified: внесхемное, 0 prod-диспетчеризации; heartbeat роутится по `command`, broadcasts по `type`). Скорректировать `test_broadcast_status_change_message_format`.
- **`IMessageFactory`** — **удалить** из `__all__` (verified: 0 реализаций; роль выполняет MessageAdapter).
- **`data_type`** — verified partial: дублирует `command` ТОЛЬКО в командном конверте (намеренно, для wire-совместимости GUI+driver), НО самостоятелен как discriminator для типа DATA (frame_ready/state_delta/register_update, где `command` нет). **НЕ удалять** без синхронного обновления всех потребителей — задокументировать как осознанное наследство. Явная судьба способности «`data_type` как dispatch-key для DATA» зафиксирована в матрице §9.9 (статус preserved), а не только текстом здесь.
- **`MessageAdapter.create_message` в `plugin_orchestrator.py:273,325`** — verified: несуществующий метод (будет AttributeError), но в мёртвой else-ветке (`io` всегда передаётся). Починить (`MessageAdapter(sender).create(...)`) или удалить ветку.

---

## 9. Матрица сохранности функционала

Статусы: **preserved** (живёт там же), **absorbed** (влит в победителя — функционал УЖЕ перенесён/существует у победителя), **capability** (сохранить как задел конструктора), **capability-to-build** (фичу НУЖНО написать в победителе — её там пока НЕТ; это план, не текущее состояние), **intentionally-dropped** (осознанно убрать, дубль/мёртвый).

> **Дисциплина (исправление по критику):** ранее 5 фич ActionBus и persistent SQL-log были помечены `absorbed`, что выдавало будущее за состояние. Verdict подтверждает их отсутствие в `CommandDispatcherOrchestrator` → корректный статус `capability-to-build`.

### 9.1 Транспорт и хаб
| Способность | Откуда | Где живёт после унификации | Статус |
|---|---|---|---|
| sync_send / send_async (priority queue) | RouterManager | RouterManager | preserved |
| request/reply (correlation_id) + авто-резолв `_resolve_pending` | RouterManager | RouterManager (ядро) | preserved |
| `request()` thread-guard (анти-дедлок) | — (только docstring) | RouterManager — добавить рантайм-проверку потока | capability-to-build (блокер cross-machine) |
| дженерик `reply_to_request` (no-op без cid) | RouterManager + process_lifecycle | RouterManager; PM bespoke-reply absorbed сюда | preserved + absorbed |
| broadcast / fan-out | ProcessCommunication.broadcast | `register_broadcast_route` / `targets=["all"]` через хаб | at-risk → preserved (через хаб) |
| иерархическая адресация proc.worker | message_module.addressing + RouterManager | без изменений | preserved |
| worker-handler routing (control-plane «почта») | RouterManager P2.2 | без изменений | capability (фундамент для live-control) |
| log-инъекция в каналы (`_attach_logger` при `register_channel`) | RouterManager | RouterManager — **обязательная часть контракта `IMessageChannel`** при вводе Redis/MCP/SQLChannel | preserved (capability контракта) |
| EXACT_MATCH dispatch | Dispatcher | Dispatcher | preserved |
| PATTERN/FALLBACK strategies | Dispatcher | Dispatcher | capability (@experimental) |
| CHAIN/Scenarios (исполнение) | Dispatcher (ScenarioManager) | ScenarioManager; дубль в ChainMatchStrategy удалить | capability + intentionally-dropped (дубль) |
| ScenarioBuilder (fluent-фасад) + `dispatch_scenario` (данные между stage) | dispatch_module | ScenarioManager-стек | capability (reserved-for-pipeline; НЕ удалять при чистке ChainMatchStrategy) |
| доменная конвенция команд + timing | CommandManager | CommandManager (фасад) | preserved |
| `register_message_handler` (полный relay в message_dispatcher) | RouterManager | RouterManager | preserved (relay, не дубль) |

### 9.2 SHM / кадры
| Способность | Откуда | Где живёт после унификации | Статус |
|---|---|---|---|
| SHM zero-copy кадров (memoryview) | MemoryManager | отдельный hot-path слой (не канал хаба) | preserved |
| единый SHM↔numpy fallback | 2× FrameShmMiddleware | один FrameShmMiddleware | absorbed (2→1) |
| ring-buffer слотов кадров | встроенный `%` (generic, live) **vs** `RingBufferWriter` (класс, unused) | один путь: live встроенный ИЛИ канонизировать `RingBufferWriter` | capability + intentionally-dropped (дубль) |
| третий путь к `write_images` (RingBuffer) | shared_resources_module/buffers | свести к единому SHM-write | intentionally-dropped (дубль пути) |
| `release_process_memory` (освобождение SHM при replace) | caller в PM готов (`process_manager_process.py:608`); реализации на MemoryManager НЕТ | MemoryManager — **добавить метод** + объявить в `IMemoryManager` (иначе утечка SHM при `replace_blueprint`) | capability-to-build (M2, §3.7) |
| `reinitialize_in_child` (наследование SHM в дочернем) | shared_resources_module | **вызывается в проде** (`bundle_builder.py:128`) — без изменений | preserved (M1: ложный GAP исправлен) |

### 9.3 Внешние каналы / сервисы
| Способность | Откуда | Где живёт после унификации | Статус |
|---|---|---|---|
| Modbus OUTBOUND (`send`) | ModbusChannel | RouterManager | preserved |
| Modbus INBOUND (`poll`: telemetry/status/error) | ModbusChannel (**сейчас мимо хаба**, prefix-баг) | RouterManager после фикса prefix (`modbus_{unit}` → `{proc}.modbus_{unit}`) ИЛИ перевод на push | at-risk → capability-to-build (фикс prefix, §12 P2) |
| Modbus command-путь | `ModbusChannel.send` **vs** `cmd_*()` плагина (дубль) | один путь через канал | intentionally-dropped (дубль) |
| headless backend-control (TCP) + fan-out на всех клиентов + PID-specific teardown | SocketChannel + backend_ctl | RouterManager | preserved |
| SocketBridgeAdapter (`request` в read-потоке) | backend_ctl/driver | reference-паттерн cross-machine sync-over-async | capability (канонический рецепт) |
| SQL execute_command | SQLManager | прямой вызов (исключение, документировать); опц. SQLChannel | intentionally-dropped (из хаба) |
| cross-process dispatch тяжёлых задач | WorkerPoolDispatcher | worker-handler routing хаба | intentionally-dropped (запрещён к реанимации) |

### 9.4 process_manager_module (19 capabilities — крупнейшая карта)
| Способность | Откуда | Где живёт после унификации | Статус |
|---|---|---|---|
| spawn_processes | ProcessManagerProcess | PM | preserved |
| **replace_blueprint + snapshot-rollback** (atomic горячая замена) | ProcessManagerProcess | PM — **прямо для recipe-driven launch (приоритет владельца)** | preserved (НЕ потерять) |
| protected_processes (защита от удаления, напр. gui) | ProcessManagerProcess | PM | preserved |
| auto_restart по `RestartPolicy` | ProcessMonitor | PM | preserved |
| graceful_shutdown_cascade | ProcessManagerProcess | PM | preserved |
| status_broadcast / process_full_status | ProcessMonitor | `_publish_state` (live); legacy `process_full_status` в heartbeat — мёртв | preserved + intentionally-dropped (мёртвая ветка) |
| priority_management | PM | PM | preserved |
| uptime_telemetry | ProcessMonitor | PM | preserved |
| wire_management / topology_management | PM | PM | preserved |
| 17 builtin-команд (worker.*, wire.*, introspect.*) | CommandManager + PM | через `register_commands_with_router` (double-call идемпотентен, задокументировать) | preserved |
| bespoke-reply `_handle_process_command` (дубль success/result в envelope+data) | PM | перевести на `reply_to_request` | absorbed (дубль ответа) |

### 9.5 shared_resources_module
| Способность | Откуда | Где живёт после унификации | Статус |
|---|---|---|---|
| `register_process` (фасад единой точки, ADR-018) | SRM | SRM — привести регистрацию к фасаду (обход фасада: PSR/ConfigStore напрямую `bundle_builder.py:63,68`; очереди создаёт `process_registry`, не bundle_builder — S2) | preserved + capability-to-build (фикс обхода фасада) |
| `ProcessStateRegistry` (single source of truth очередей) | SRM | без изменений | preserved |
| `queue_registry.send_to_queue` (физический транспорт) | SRM | нижний слой хаба | preserved |
| `system_stop_event` через Process inheritance | SRM | без изменений | preserved |
| `EventManager` dual-notification (in-proc + IPC) | SRM | без изменений | preserved |
| `ConfigStore` | SRM | без изменений | preserved |
| `Config._change_callbacks` (5-я ось pub/sub) | config_module | без изменений | capability |

### 9.6 Состояние / pub/sub / undo
| Способность | Откуда | Где живёт после унификации | Статус |
|---|---|---|---|
| cross-process delta pub/sub | StateStore | StateStore | preserved |
| transactions с `coalesce()` (сжатие промежуточных дельт) | StateStore | StateStore | capability (нетривиально, не растворять) |
| selectors / middleware / persistence / recipes / health | StateStore | StateStore | capability |
| `StateAdapterBase` с anti-loop `_pending_paths` | StateStore (фундамент всех адаптеров) | StateStore — **ядро при починке `RegistersStateAdapter`** | preserved (не задеть) |
| per-pattern фильтрация callbacks на клиенте (ADR-SS-012) | StateProxy | сохранить при упрощении state-пути (GuiStateProxy→Bindings) | preserved (безопасный контракт доставки) |
| GuiStateProxy: маршалинг в Qt main thread | GuiStateProxy | без изменений | preserved |
| GuiStateProxy: дедупликация дельт + локальный кэш | GuiStateProxy | без изменений | preserved (отдельные capabilities) |
| undo/redo + coalescing (field-level) | CommandDispatcherOrchestrator | без изменений | preserved |
| undo_to(id) | ActionBus (источник) | CommandDispatcherOrchestrator — **написать** | capability-to-build |
| record() внешних мутаций | ActionBus (источник) | CommandDispatcherOrchestrator — **написать** | capability-to-build |
| pre-execute RBAC hook | ActionBus (источник); **в Orchestrator точки нет** | CommandDispatcherOrchestrator — **написать** (закрыть RBAC field-edit дыру) | capability-to-build |
| post-execute audit callback | ActionBus (источник) | CommandDispatcherOrchestrator — **написать** | capability-to-build |
| персистентный SQL-лог + ActionLogRecovery | ActionBus (dead-in-prod) + Services/sql | CommandDispatcherOrchestrator — **написать при потребности** (ActionLogRecovery нарушает инкапсуляцию `bus._handlers` — переписать) | capability-to-build (открытый вопрос §13) |
| patch-based undo (память) | ActionBus | — (snapshot заменяет; ActionBus сохраняется во framework как класс) | intentionally-dropped (из GUI-проводки) |
| typed in-proc события + Qt thread-marshal | EventBus / QtEventBus | без изменений | preserved |
| реактивные widget-bindings (glob-path) | GuiStateBindings | carve-out во framework | preserved |
| резолвер `plugin_name`→register (CommandSender) | prototype `app.py:509-533` | carve-out в `message_module` (universal) | preserved → capability (carve-out) |
| per-field + global observers регистров | RegistersManager | RegistersManager; мост к StateStore починить | preserved |
| get_fields/get_categories → FieldInfo для GUI | RegistersManager | RegistersManager | preserved (уникально) |

### 9.7 Наблюдаемость (логи / ошибки / статистика)
| Способность | Откуда | Где живёт после унификации | Статус |
|---|---|---|---|
| LoggerManager → router (НЕ дублирует записи; M5) | `logger_manager.py:401` (в проде `_router_manager=None`) | при `enable_router_routing=True` без приёмника — overhead/dead traffic, не дублирование | intentionally-dropped (dead path) |
| мёртвый Dispatcher в LoggerManager | LoggerManager | — | intentionally-dropped (§11) |
| StatsManager (агрегация) | channel_routing_module | StatsManager (к роутеру НЕ подключён — verified) | capability |
| BatchBuffer (triple-trigger flush) — logger/error | channel_routing_module | реализация `IBufferStrategy` | capability (доказательство extension-point) |
| AggregationWindow — stats | channel_routing_module | реализация `IBufferStrategy` | capability (доказательство extension-point) |
| `IBufferStrategy` (все 4, вкл. AsyncSenderBuffer) | channel_routing_module | точка расширения буферизации | capability |

### 9.8 Schema-driven маршрутизация (data_schema_module / registers)
| Способность | Откуда | Где живёт после унификации | Статус |
|---|---|---|---|
| 4-уровневый dispatch priority chain | resolve_dispatch_targets | единый `extract_process_targets` | preserved + absorbed |
| FieldRouting.process_targets (адрес доставки) | data_schema_module | через `extract_process_targets` (live: CommandCatalog) | preserved |
| RegisterDispatchMeta (class-level fan-out) | data_schema_module | в `extract_process_targets` (3-й приоритет) | capability (прод-доступность) |
| FieldRouting.channel (декларативный канал) | data_schema_module | `@experimental` до kind-хаба (ADR-COMM-001 P4/P5) | capability (at-risk) |
| RouterSchemaAdapter (schema→маршруты) | router_module | `@experimental` (точка построения маршрутов для kind-хаба) | capability |
| send_register_message + error-коды | registers_module | transmitter мёртв (дубль CommandSender); error-коды absorb в живой send | intentionally-dropped + absorbed |
| FieldRouting.transform | data_schema_module | — | intentionally-dropped (0 потребителей) |
| schema-to-channel introspection | SchemaMixin | SchemaMixin (для /channel-map) | capability |

### 9.9 Конверт сообщения
| Способность | Откуда | Где живёт после унификации | Статус |
|---|---|---|---|
| `request_id` единая корреляция | Message | Message; `data.correlation_id` — backward-shim чтения | preserved |
| `data_type` как dispatch-key для типа DATA (frame_ready/state_delta/register_update) | Message | Message — **сохранить** (самостоятелен там, где нет `command`); задокументировать как наследство | preserved (verdict partial — не удалять) |
| `routers` | Message | — | intentionally-dropped (0 prod-читателей) |
| `subtype` | Message / heartbeat | — | intentionally-dropped (0 prod-диспетчеризации) |
| `IMessageFactory` | interfaces | — (роль у MessageAdapter) | intentionally-dropped (0 реализаций) |
| `channel="data"/"system"/"queue"` (vestigial) | продюсеры | удалить через комплексный рефактор (setters+guards+sentinel) | intentionally-dropped (НЕ точечно) |

### 9.10 Heartbeat / GUI-bridge / незамкнутые тракты
| Способность | Откуда | Где живёт после унификации | Статус |
|---|---|---|---|
| ProcessHeartbeat workers_status телеметрия (effective_hz/cycle_duration_ms, без metrics — экономия трафика) | process_heartbeat | без изменений — **не задеть при чистке конверта heartbeat (§11 п.3 трогает только `subtype`)** | preserved |
| IPC→Qt bridge (frame/command) | DataReceiverBridge | DataReceiverBridge | preserved |
| worker→main для state | DataReceiverBridge (2-й hop) | GuiStateProxy→GuiStateBindings напрямую | preserved (короче путь) |
| routing_table (kind→канал декларация) | message_module | подключить в `_resolve_channels` (P1) | at-risk → capability-to-build |
| system_events канал (EventManager→канал) | ProcessCommunication | ждёт первого подписчика | capability (at-risk, незамкнут) |
| **PreviewWindow** (подписан на `display.*`, продюсера кадров нет, Phase 4 placeholder) | prototype | ждёт продюсера кадров ИЛИ удалить как незамкнутый тракт | capability (at-risk, незамкнут) — см. §13 |
| cross-machine адрес machine.proc.worker | — | НЕ существует (нереализованная цель) | intentionally-dropped (открытый вопрос §13) |

### 9.11 Прочие фасады и тракты (добавлено по ревью G1–G4)
| Способность | Откуда | Где живёт после унификации | Статус |
|---|---|---|---|
| `local_channel` (`{proc}_local`, `QueueChannel` на `ThreadQueue(256)` в каждом процессе) | `process_communication.py:99-109` | **0 потребителей** (grep, G1) — registered-but-never-consumed dead-end | решить (§13): убрать ИЛИ capability (intra-process fast-path) |
| `PluginContext` — канонический comm-фасад плагина (ADR-120: `send_message`/`receive_message`/`router_manager`/`state_proxy`) | plugin context | без изменений — плагины общаются ТОЛЬКО через него | preserved (G2, enforcement-point) |
| `ProcessIO` фасад (GenericProcess/PluginOrchestrator I/O) | `process_io.py` | без изменений | preserved (G3) |
| back-pressure / flow control | AsyncSender `PriorityQueue(512)` drop+warn · `IBufferStrategy` · DataReceiver Q6 · WorkerPool drop-oldest · SHM RingBuffer · mp.Queue bounded | реализован системно (G4: claim «отсутствует» — refuted) | preserved |
| `events_queue` fallback без `maxsize` (потенц. unbounded при деградации SRM) | `process_communication.py:119` | добавить `maxsize` — единственный реальный gap back-pressure | capability-to-build (G4) |

**Все перечисленные способности имеют явную судьбу.** Где статус `capability-to-build` — это означает «решено сохранить функционал, но он ещё не написан в победителе» (не выдаём план за состояние).

---

## 10. Что оставить как capability конструктора (не удалять)

Доказанный принцип «не используется ≠ не нужно» — удаляем только подтверждённый дубль. Оставить:
- **FieldRouting.process_targets + RegisterDispatchMeta** — живая SSOT-декларация адреса доставки (CommandCatalog читает в проде); совпадает с целевой осью адресации. Для cross-machine/множественных воркеров декларативный адрес на схеме экономит ручной wire-up.
- **FieldRouting.channel + RouterSchemaAdapter + build_routing_map** — `@experimental` до реализации kind-хаба (ADR-COMM-001 явно отложил удаление на P4/P5 «только после обсуждения с владельцем» — verified). Готовая точка построения маршрутов из деклараций.
- **PATTERN/FALLBACK/CHAIN strategies + Scenarios** — слой исполнения/маршрутизации для vision/processing-pipeline; не дублируются нигде в живом коде. Сохранять конкретно: **`ScenarioBuilder` (fluent-фасад) + `dispatch_scenario` с передачей данных между stage + Scenario CRUD `ScenarioManager`** — при чистке дубля `ChainMatchStrategy.scenarios` НЕ снести эти живые части. Пометить reserved.
- **IBufferStrategy (все 4)** — настоящая точка расширения буферизации. Конкретные доказательства, которые НЕ растворять: **`AggregationWindow` (stats)** и **`BatchBuffer` (logger/error, triple-trigger flush)** + `AsyncSenderBuffer`; резерв для back-pressure/batch при высокочастотной телеметрии контроллеров.
- **`transactions.coalesce()` StateStore** — сжатие промежуточных дельт; отдельная нетривиальная способность, не сводить к общей строке «transactions».
- **`StateAdapterBase` + anti-loop `_pending_paths`** — фундамент всех адаптеров (Recipe/Service/Display/Camera/Registers); беречь при починке моста.
- **SocketBridgeAdapter (`request` в read-потоке)** — канонический рецепт sync-over-async для cross-machine адаптеров.
- **`Config._change_callbacks`** — пятая ось pub/sub (подписка на конфиг); самостоятельный контракт.
- **system_events канал** — тракт не замкнут (0 читателей через хаб), но это первый кандидат для cross-process событийной шины; ждёт подписчика.
- **PreviewWindow** — незамкнутый тракт того же класса (подписан на `display.*`, продюсера нет, Phase 4 placeholder); либо дать продюсера, либо убрать (открытый вопрос §13).
- **chain_module DAG/Chain движки** — слой исполнения pipeline (граф-движок), ортогонален транспорту; framework-движок без дубля.
- **InMemoryRouter** — публичный тест-helper (ADR-SS-010), критичен для синхронного детерминированного тестирования state-кода.
- **worker-handler routing (P2.2)** — фундамент для per-process инкрементального live-control.

---

## 11. Мелкие проблемы / быстрые победы (1-5 строк, сразу чище и отлаживаемее)

Все verified кодом:

1. **Мёртвый shadow-файл** — удалить `multiprocess_prototype/frontend/bridge.py` (затенён пакетом `bridge/`, никогда не импортируется; расходится с `bridge_impl.py` по `ConnectionType` — ловушка при чтении).
2. **Мёртвое поле `routers`** — удалить из `Message`, `LogMessageSchema`, `CommandMessageSchema` (`message.py:68`; 0 prod-читателей).
3. **Мёртвое поле `subtype`** — убрать из heartbeat/broadcast-конвертов (`process_heartbeat.py:67`, `process_monitor.py:534,580`; 0 prod-диспетчеризации).
4. **Мёртвая абстракция `IMessageFactory`** — убрать из `__all__` (`interfaces.py:74`; 0 реализаций).
5. **`RolesPanel` bus=None** — `_sections.py:119` передаёт `bus=None`, правки прав ролей молча теряются (Save no-op без обратной связи). Либо мигрировать ROLE_UPDATE на CommandDispatcher-команду, либо явно отключить кнопку Save.
6. **Сломанный `get_field`** — `registers_adapter.py:109` зовёт несуществующий метод; `sync_domain_to_state()` всегда падает в `except`. Заменить на `getattr(self._rm.get_register(reg), field)`.
7. **Мёртвый relay** — `PluginOrchestrator` шлёт `register_changed`/`register_schemas` в PM, где нет хендлера (silent dead letter). Удалить relay-блок.
8. **Битый `MessageAdapter.create_message`** — `plugin_orchestrator.py:273,325` зовёт несуществующий метод (AttributeError в мёртвой else-ветке). Починить или удалить ветку.
9. **Дубль хранилища сценариев** — удалить `ChainMatchStrategy.scenarios`/`create_scenario`/`dispatch_scenario` (заполняются только в тестах; `dispatch()` использует `ScenarioManager`).
10. **`console_adapter` help сломан** — `get_commands().items()` на `List[Dict]` (`console_adapter.py:128`), ошибка глушится `except: pass`, help не показывает команды. Заменить на итерацию по списку.
11. **`update_handler_*` хардкод `default_strategy`** — `dispatcher.py:506-530` не принимают `strategy`; handler в PATTERN/FALLBACK нельзя обновить. Добавить параметр или задокументировать.
12. **Расходящийся дефолт `queue_type` в broadcast** — `process_communication.py:238` фиксирует `system`, `_select_queue_type` даёт `data` для не-command (`router_manager.py:253`). Свести broadcast к каноническому правилу.
13. **`silent pass` в bindings** — `GuiStateBindings._on_state_msg` глушит ошибку setter'а (`bindings.py:202-203`), нарушает правило 5 (логировать ошибки). Добавить `_logger.debug(...)`.
14. **Мёртвый `DispatcherConfig`** — объявлен, не подключён к `Dispatcher.__init__`. Подключить (from_config) или убрать. (`CommandManagerConfig` — НЕ мёртв, verified: используется через ManagersConfig.) Судьба `DispatcherConfig` доведена и до §9.1 (строка dispatch).
15. **`closure _state_multiplexer`** — `app.py:249-257` скрытый fan-out state_delta в TopologyBridge через перехват single-slot callback. Заменить на явный `add_state_listener` (multi-subscriber).
16. **Мёртвый Dispatcher в LoggerManager** — экземпляр диспетчера создаётся, но не используется (channel_routing-карта). Удалить.
17. **Путаница двух CRM-конфигов** — `ChannelRoutingConfig` vs `ChannelRoutingManagerConfig` (похожие имена, разные роли) — переименовать/задокументировать, чтобы не путать при подключении новых каналов.
18. **`AsyncSenderBuffer.flush()` — no-op** — не сбрасывает буфер фактически. Починить либо задокументировать как умышленный (чтобы не ловить «потерянные» сообщения при остановке).
19. **`expects_full_message` — НЕ vestigial (исправлено по ревью M4, refuted high)** — флаг реально ветвит поведение (`dispatcher.py:402`, `base_dispatcher.py:130`, `chain_match.py:207`, `scenarios.py:146`). Асимметрия default-ов: `Dispatcher.register_handler`→`False`, `RouterManager.register_message_handler`→`True`. Builtin worker-команды (`worker.create/remove/update/start/stop/restart`, `builtin_commands.py:77-118`) регистрируются с default=False и получают только `data`. **НЕ убирать** — оставить флаг, задокументировать асимметрию, рассмотреть унификацию (единый default или запрет регистрации без явного указания).

**Active-bug находки из salvage (потеря сообщений / нарушение контрактов — исправлено по ревью S1: пп.20-21 НЕ «бесшумны», они логируют warning; баг в ПОТЕРЕ/нарушении контракта, не в отсутствии лога):**

20. **`_route_to_worker` — потеря сообщения при ошибке handler** (`router_manager.py:552-571`; логирует `_log_warning` на :570 — НЕ бесшумно, S1) — при исключении в worker-handler сообщение помечается consumed (`return True`), но НЕ обработано. **Критично для `process.stop`/`worker.pause`** (control-plane команды теряются). Чинить ПОТЕРЮ: пробрасывать в error-handler / retry, не помечать consumed при провале.
21. **`GuiStateProxy._dispatch_via_qt` — деградация в worker-thread** (`gui_state_proxy.py:106-133`; логирует `_log_warning`/`_log_error` на :125-133 — НЕ бесшумно, S1) — при сбое `invokeMethod`/отсутствии PySide6 колбэки выполняются в worker-потоке, **нарушая контракт main-thread доставки** (риск Qt-краша). Чинить НАРУШЕНИЕ КОНТРАКТА: не выполнять GUI-колбэк вне main-thread (очередь/отказ), а не просто логировать.
22. **`ProcessModule._init_state_proxy` в `finally`** (`process_module.py:178-179`) — при исключении ДО присвоения `router_manager` регистрация state.changed молча пропускается (guard `return`). Перенести в конец успешного `initialize` или задокументировать exception-safety.
23. **Heartbeat стартует до готовности приёмника PM** (`process_module.py:613`; исправлено по ревью S5, partial) — гонка структурно есть, НО окно = spawn+initialize **<2s** (не «~5s»: 5s — интервал между heartbeat'ами), и **false-positive UNRESPONSIVE НЕТ** — `process_monitor.py:380` `if last_hb is None: return` даёт бесконечный grace. Реальный эффект — **задержка телеметрии ~5s** при потере первого heartbeat. Зафиксировать порядок старта — низкий приоритет.
24. **EventBus: порядок ВНУТРИ bucket `TopologyReplaced`** (исправлено по ревью S6, исходный claim refuted) — bucket-ы изолированы по типу события (`event_bus.py:99-120`), поэтому порядок `TopologyReplaced` vs `PluginConfigChanged` семантически **нейтрален** (прежний claim неверен). Реальный инвариант — порядок подписчиков ВНУТРИ bucket `TopologyReplaced`: `topology_bridge` (`app.py:477`) до `PipelinePresenter` (`presenter.py:121`), сейчас соблюдён. Защитить тестом на порядок внутри bucket / комментарием-инвариантом.

---

## 12. План этапами P0 → P3

> **Инвариант приёмки каждого этапа:** Pipeline (камера→обработка→дисплей) работает. Проверка — `/run-proto` + Qt-smoke: кадры идут, телеметрия не регрессирует. Паритет горячего пути кадров/heartbeat — не ломать.

### P0 — быстрые победы + разблокировать телеметрию (последовательно)
Параллельность: нет (часть трогает горячий путь). Риск: низкий для §11, средний для телеметрии.
- Все мелкие правки §11 пп. 1-4, 7, **8**, 9, **11**, 13, **14**, 16-19 (мёртвый/битый код, shadow, relay, мёртвый Dispatcher Logger, CRM-конфиги, битый `MessageAdapter.create_message`, хардкод `update_handler_*`, мёртвый `DispatcherConfig` — нулевой риск; **M3: пп.8/11/14 добавлены — раньше выпадали из этапов**). П.19 — задокументировать асимметрию `expects_full_message` (НЕ убирать, M4).
- **Fix подписки GUI на телеметрию** — **[2026-06-03] ГИПОТЕЗЫ a/б ОПРОВЕРГНУТЫ рантайм-probe'ом.** Инструментация запущенного прототипа (`QT_MCP_PROBE=1`, `print(flush=True)` в 4 точках) доказала: весь путь сервер→IPC→GUI РАБОТАЕТ — `ProcessMonitor._publish_state` 780×, `DeltaDispatcher.dispatch`→`stats={'gui':1}` 150×, `GuiStateProxy.on_state_changed` 300× (GUI получает дельты, гонит в Qt main thread). (а) request_id и (б) `{gui}_system` vs `["data"]` — НЕ причина. **РЕАЛЬНЫЙ остаток — рассогласование путей в `widgets/tabs/processes/_panels.py:295-349` (`_connect_bindings`):** карточки подписаны на `processes.{name}.state.fps` (издателя НЕТ — FPS публикуется как `workers.*.effective_hz`), `state.latency_ms` (издателя НЕТ), `system.health.active/broken_wires/avg_fps` (издателя НЕТ); `state.status` издаётся, но разовой дельтой на старте (нужен initial-state replay на subscribe). Фикс — свести контракт publish↔bind + health-агрегаты + replay; plan-level, не 1-строчник. Детали — memory `project_telemetry_subscription_bug`.
  > ⚠️ Урок измерения: probe через `self._log_info` объектов StateStore/DeltaDispatcher/GuiStateProxy НЕ писал в файл (логгер не подключён) → дал ложное «dispatch=0». Доверять только `print(flush=True)`/`self.process._log_info`.
  > **Выбор владельца 2026-06-03: Option A — бэкенд публикует ожидаемые пути** (GUI остаётся декларативным). Прогресс:
  > - ✅ **process-level initial replay (`16e14084`)** — `handle_state_subscribe` шлёт новому подписчику снимок текущих листьев (`_replay_initial_state`), +3 теста, 479 зелёных. Решает race process-level подписки.
  > - ⏳ Осталось (verify-done: GUI ещё «—»): (1) **widget-level late-binding** — вкладка `LazyTabWidget`, карточки биндятся ПОСЛЕ статус-дельт; нужен replay при `GuiStateBindings.bind()` из кэша (контракт `StatusIndicator.set_state("running")`→зелёный ВЕРНЫЙ); (2) **FPS нет источника** — heartbeat не несёт `workers.*.effective_hz` (воркеры не репортят hz; `get_worker_status` без него); нужно: воркер→hz→ProcessMonitor агрегирует в `state.fps`; (3) **latency_ms** нет издателя; (4) **system.health.active/avg_fps/broken_wires** нет издателя (ProcessMonitor: active=кол-во running). Детали — memory `project_telemetry_subscription_bug`.
  > - 🔑 **[2026-06-03] РАНТАЙМ-РАССЛЕДОВАНИЕ нашло ЕДИНУЮ точку обрыва GUI-стороны:** `_StateDeltaEmitter._on_state_deltas` (Qt slot, переход IO→Qt через `QMetaObject.invokeMethod(...QueuedConnection)`) **FIRED 0 раз** — молча не доставляет. При этом кадры через ТОТ ЖЕ `DataReceiverBridge._deliver` (Signal+AutoConnection+emit) пересекают поток успешно. → **Упрощение: убрать выделенный emitter+invokeMethod, гнать state-дельты через проверенный bridge-механизм кадров** (реализует §7(а) «убрать второй no-op hop» + §9.10). Детальный план доставки/fail-loud/издателей метрик/late-binding вынесен в **[`telemetry-delivery-simplification.md`](telemetry-delivery-simplification.md)** (4 Phase, 6 задач Task 1.1–4.1). Принцип приёмки — qt-mcp скриншот вкладки «Процессы»: индикаторы зелёные, FPS/Latency числа, «Активно: N».
  > - 🧭 **[2026-06-03] АУДИТ КОММУНИКАЦИИ ([`comm-system-communication-audit.md`](comm-system-communication-audit.md)):** на вопрос владельца «не перенести ли телеметрию на RouterManager-хаб» — **отклонено как сформулировано: телеметрия УЖЕ на хабе** (`state.changed` через `register_message_handler`, серверная публикация через `router.send_async`). Разрыв — внутрипроцессный IO→Qt-хоп, который Qt-free хаб по дизайну не пересекает (это роль `DataReceiverBridge`). Вариант A (reuse bridge) — единственный, кто **минус один механизм** (устраняет дубль D1). `RouterManager.request()` = **0 prod-потребителей**. В аудите: инвентаризация 13 механизмов, карта дублей D1-D6, список канонов и порядок устранения.
  > **Противоречие с памятью проекта (зафиксировать перед правкой):** memory-запись `telemetry_subscription_bug` утверждает «серверная логика ОК; чинено отдельно: registry `initializing→running`, кнопки→PM». Salvage-находка (high confidence) описывает оба разрыва как активные. **Возможно, часть уже исправлена.** Поэтому первым шагом Debugger подтверждает РАНТАЙМ-точку обрыва (DEBUG в 3 точках) и сверяет с тем, что уже сделано по memory-записи, и только затем fix. См. `plans/processes-tab-telemetry.md`.
- **[2026-06-03] ТРЕТИЙ разрыв телеметрии — СЕРВЕРНЫЙ (найден probe'ом, root-cause подтверждён чтением кода).** Помимо GUI-стороны (а/б выше), `state.*` ломаются ещё и на стороне ProcessManager: `state.subscribe`/`state.get` дают **timeout даже для headless-драйвера, который шлёт корректный `request_id`** (`introspect.*` при этом отвечают). Причина — **конфликт двух путей регистрации хендлеров в одном `message_dispatcher`**:
  - `StateStoreManager.initialize()` (`state_store_manager.py:98`) безусловно зовёт **RAW** `register_message_handlers(router)` → кладёт `handle_state_subscribe` напрямую. RAW-хендлер возвращает dict, но **не зовёт `reply_to_request`** → инициатор request/reply не получает ответ;
  - параллельно идёт **wrapped**-путь (`register_commands` → `register_commands_with_router` → `_make_command_handler`, который **отвечает**);
  - `base_dispatcher.register_handler` (`dispatch_module/core/base_dispatcher.py:39`) — **«первая регистрация побеждает»** (`if key in self.handlers: return False`). RAW регистрируется раньше wrapped (в `initialize()` до `register_commands_with_router`) → RAW «прилипает», wrapped молча отвергнут → reply нет → timeout.
  - `introspect.*` живут **только** в CommandManager (builtin_commands) → всегда wrapped → отвечают. Отсюда асимметрия «introspect ✅ / state.* ❌», которую раньше списывали на RAW-vs-wrapped, но **точная причина — порядок+конфликт регистрации, а не сам факт wrapping**.
  - **Фикс (P0, low-risk, ПРИМЕНЁН + VERIFIED headless):** флаг `StateStoreManager(auto_register_ipc=False)` — отключает RAW-регистрацию из `initialize()`, оставляя **единственного владельца ключей state.* — CommandManager+wrapped** (single-ownership, конфликт устранён). router у менеджера сохранён — нужен `DeltaDispatcher` для push дельт `state.changed`. Дефолт `True` сохраняет legacy (тесты/`in_memory_router`). Файлы: `state_store_manager.py` (флаг), `multiprocess_prototype/orchestrator.py` (`auto_register_ipc=False`). Тесты: `test_state_store_manager.py` (+2: opt-out не регистрирует RAW; дефолт=True цел).
  - **Верификация (`backend_ctl/telemetry_probe.py`, 2026-06-03):** ДО — `state.subscribe`/`state.get` → `success=False (timeout)`. ПОСЛЕ — `state.subscribe` → `success=True, sub_id=…`; `state.get(processes)` → `success=True` + полное дерево (camera_0/preprocessor/region_splitter/… все `running`, с fps/uptime). **Побочно подтверждено: `ProcessMonitor` ПУБЛИКУЕТ телеметрию** (дерево не пустое) → backend OK. Значит остаточный симптом GUI «—» (если есть) — **только GUI-сторона** (пункты а/б выше: `StateProxy.subscribe` request_id + `state.changed` `_system` vs `["data"]`), серверная часть закрыта. (`introspect.status(<child>)` timeout — отдельный вопрос reply от дочернего процесса внешнему драйверу, не телеметрия.)
  - **Связь с P2 (авто-reply):** это интерим. Когда P2 внесёт **авто-reply по `request_id` в `receive()`/`message_dispatcher`** (см. ниже), ответ станет ответственностью **транспорта**, а не обёртки `_make_command_handler` → асимметрия RAW/wrapped исчезнет полностью, и даже RAW-путь начнёт отвечать. Тогда флаг `auto_register_ipc` сведётся к защите от двойной регистрации (single-ownership ключа), а не к «кто умеет reply». **Канон ответственности:** «ответить на request/reply» принадлежит транспорту (RouterManager.receive), регистрация хендлера — CommandManager (через один bridge `register_commands_with_router`); RAW `register_message_handlers` остаётся только для контекстов без CommandManager (тесты).
- **RolesPanel bus=None** (§11 п.5), **get_field** (§11 п.6), **console help** (§11 п.10).
- **Потеря сообщений / нарушение контрактов** (§11 пп. 20-22; S1 — НЕ «бесшумные», пп.20-21 логируют warning): `_route_to_worker` (критично — теряются `process.stop`/`worker.pause`), `GuiStateProxy._dispatch_via_qt` (нарушение main-thread контракта, риск Qt-краша), `_init_state_proxy` в `finally` (единственный реально silent skip). Низкий риск правки, высокий эффект на debuggability.

### P1 — единый путь отправки + чистка конверта (framework, осторожно)
Параллельность: нет (hot data-path). Риск: высокий. Обширные тесты роутера + integration кадров.
- Свести `send_to_process`/`_deliver_by_targets`/`broadcast` к одному `_dispatch(targets, msg)`; публичные API — фасады. Прикладной код не зовёт `queue_registry` напрямую.
- Расширить `_select_queue_type` (event/response→system) ПЕРЕД любым касанием хардкодов qtype.
- Подключить `routing_table.resolve_channel_kind` в `_resolve_channels` (kind→канал) — снимает vestigial guard `queue`.
- Конверт: `request_id` как единое имя (shim для `data.correlation_id`); удалить vestigial `channel` у продюсеров (комплексно: setters + guards + sentinel).

### P1.5 — порядок старта и хрупкие инварианты (низкий риск, до hot-path)
Параллельность: да. Риск: низкий.
- **Heartbeat race** (§11 п.23) — зафиксировать порядок старта heartbeat относительно регистрации handler в PM.
- **EventBus order** (§11 п.24) — явный приоритет/тест на порядок `TopologyReplaced` → `PluginConfigChanged`.
- **bundle_builder обход ADR-018** (§3.7) — привести создание очередей к единой точке `register_process`.

### P2 — дженерик request/reply + сервисы к правилам (framework + Services)
Параллельность: частично (worktree — SQL-channel и FrameShm-merge независимы). Риск: средний.
- Авто-reply по `request_id` в `receive()`/`message_dispatcher`; перевести PM `_handle_process_command` на `reply_to_request` (с опцией вложенного `data`-конверта). **После этого** RAW-хендлеры тоже начнут отвечать → P0-интерим `StateStoreManager(auto_register_ipc=False)` (см. P0, серверный разрыв телеметрии 2026-06-03) сведётся к защите от двойной регистрации; пересмотреть, не вернуть ли RAW-путь как единственный (один владелец ключа). **Двойной reply недопустим:** при переносе reply в транспорт — убрать reply из `_make_command_handler`, иначе ответ уйдёт дважды.
- Перевести `StateProxy.subscribe` на `router.request()` (фикс telemetry + первый реальный GUI-потребитель request; **проверить дедлок-контракт — добавить thread-guard в `request()`**, §11/§9.1).
- Слить 2× `FrameShmMiddleware` → 1 (общий SHM-fallback в utils); свести дубль ring-buffer (`RingBufferWriter` vs встроенный `%`).
- **Modbus INBOUND → push** (решение Q9, S3): перевести inbound на `on_inbound` (push в хаб), убрать зависимость от prefix-фильтра `_poll_all_channels`. Командный путь — **убрать дубль `cmd_*` плагина в пользу `ModbusChannel.send`** (S3: «слить», единая формулировка). До перевода Modbus НЕ заявлять двунаправленным эталоном в хабе.
- **SHM-утечка** (§3.7, M2): добавить реализацию `release_process_memory(process_name)` на `MemoryManager` + объявить в `IMemoryManager` (caller в PM `process_manager_process.py:608` уже готов). `reinitialize_in_child` — **уже вызывается в проде** (M1), не трогать.
- SQL: обернуть `execute_command` в `IMessageChannel` ИЛИ задокументировать исключение.
- Единый `extract_process_targets` (один reader).

### P3 — undo-консолидация, GUI carve-out, legacy (обсудить, не удалять)
Параллельность: да. Риск: низкий-средний.
- **Написать 5 фич в `CommandDispatcherOrchestrator`** (`capability-to-build`, не absorb готового — фич в Orchestrator нет): `undo_to`, `record()`, pre-execute RBAC-hook (закрыть RBAC field-edit дыру), post-execute audit-callback, persistent SQL-log (последнее — только при подтверждении потребности, §13). Вывести ActionBus из GUI-проводки (класс оставить во framework как референс контракта).
- Carve-out во framework: GUI-подписка на StateStore (helper `GuiStateProxy.subscribe_telemetry`), `EventBus` (zero-Qt), `GuiStateBindings`, **`DataReceiverBridge` → опц. `frontend`-слой framework (Q6, Qt-завязка изолирована, ядро Qt-free)**, **резолвер `plugin_name`→register в `message_module`** (§7 (д)); убрать второй hop state через bridge; `_state_multiplexer` → multi-subscriber. **Беречь `StateAdapterBase._pending_paths` и per-pattern фильтрацию (ADR-SS-012) при упрощении пути.**
- Дженерификация CommandDispatcherOrchestrator (отвязка от `Project`/`ProjectCommand`) — после стабилизации.
- `@experimental`-пометки: FieldRouting.channel, RouterSchemaAdapter, dispatch strategies, scenarios (беречь `ScenarioBuilder`/`dispatch_scenario`), IBufferStrategy (`AggregationWindow`/`BatchBuffer`).
- Унификация терминологии, suffix-парсинг каналов в утилиту, документировать double `register_commands_with_router`.

### P-этапы: тестирование, rollback, зависимости (G6)
- **Граф зависимостей:** P0 (независим) → P1 (после P0) → P1.5 (можно параллельно P1) → P2 (после P1 единый `_dispatch`) → P3 (после P2 request/reply).
- **Acceptance на каждый этап:** инвариант Pipeline (камера→обработка→дисплей) зелёный — `/run-proto` + Qt-smoke (кадры идут, телеметрия не регрессирует) + `python scripts/run_framework_tests.py` без новых fail.
- **P1 — rollback-план (hot-path кадров, высокий риск):** правки изолированным коммитом / за флагом; перед merge — integration-тест потока кадров (FPS, отсутствие drop) vs baseline; при регрессии FPS — откат одним revert.
- **Тест-стратегия по фазам:** P0 — unit на каждый fix + smoke; P1 — расширенный регресс роутера + integration кадров; P2 — контрактные тесты request/reply + канал-тесты (Modbus push, SQLChannel); P3 — undo/redo сценарии + carve-out import-тесты.

### Трекинг (S8 — для `/plan-status`)
- [ ] **P0** — quick-wins §11 пп.1-19 (вкл. 8/11/14) + телеметрия + потеря/контракты пп.20-22
- [ ] **P1** — единый `_dispatch` + чистка конверта + `routing_table` в `_resolve_channels`
- [ ] **P1.5** — heartbeat-порядок + EventBus-инвариант (внутри bucket) + `bundle_builder`→фасад
- [ ] **P2** — авто-reply + `StateProxy.subscribe`→`request()` + FrameShm 2→1 + Modbus push + SHM `release_process_memory` + SQLChannel + единый `extract_process_targets`
- [ ] **P3** — 4 фичи undo (undo_to/record/RBAC/audit) + carve-out (§15) + дженерификация Orchestrator + `@experimental`-пометки

---

## 13. Решения владельца (зафиксировано 2026-06-02)

Открытые вопросы согласованы. Канон закреплён в [`COMMUNICATION_ARCHITECTURE.md`](../multiprocess_framework/docs/COMMUNICATION_ARCHITECTURE.md) — этот план остаётся как «почему + миграция».

| # | Вопрос | Решение |
|---|---|---|
| Q1 | Cross-machine адрес | **Заложить machine-сегмент сейчас** в `process_of`/`worker_of`/`split_address` (без рантайм-резолва) — чтобы не переписывать worker-routing позже |
| Q2 | SQL в хаб | **Ввести `SQLChannel(IMessageChannel)`** (P2); до этого прямой `execute_command` — документированное отклонение |
| Q3 | FieldRouting.channel / RouterSchemaAdapter / routing_table | **Оживить как декларативный kind-слой**, `@experimental` (FieldRouting декларирует kind/priority, не произвольную channel-строку) |
| Q4 | dispatch strategies + scenarios | **Оставить `@experimental`** (reserved для vision/processing-pipeline); сценарии беречь приоритетно |
| Q5 | system_events | **Оставить, ждать первого подписчика** (задел под cross-process событийную шину) |
| Q6 | DataReceiverBridge carve-out | **Вынести в опц. `frontend`-слой framework** (рядом с `frontend_module`, L11; Qt-завязка изолирована, ядро Qt-free). P3 |
| Q7 | persistent SQL-log + undo recovery | **Отложить** до реальной потребности; 4 другие фичи undo (`undo_to`/`record`/RBAC-hook/audit) — писать в Orchestrator (P3) |
| Q8 | PreviewWindow | **Оставить** как продуктовый задел превью кадров; подписку `display.*` не удалять, продюсера дать при реализации фичи |
| Q9 | Modbus INBOUND | **Push в хаб (`on_inbound`)** как канон контроллеров; pull у ПЛК внутри плагина остаётся (природа протокола), но в хаб данные толкаются push |

**Остаётся открытым (одно):**
- **`local_channel`** — фигурировал в первом аудите, в v2 не переисследован → доразобрать (что это, нужен ли). Статус-кандидат в §9.11 (0 потребителей).

**Архитектурные открытые вопросы (добавлено по ревью):**
- **Cross-machine — оставшиеся блокеры (чтобы не недооценить объём):** SHM локален (нет транспорта по сети), нет service discovery, bundle передаётся через process inheritance (не по сети), `mp.Event` stop_event in-process (нет remote-stop). Q1 (machine-сегмент) — лишь адрес, не транспорт. Полный cross-machine deployment — отдельная веха после первого адаптера.
- **G5 — версионирование конверта `Message`:** для cross-machine/long-lived нет `schema_version` → невозможен graceful upgrade конверта между нодами разных версий. Зафиксировать при первом cross-machine адаптере.
- **Latency/perf budget hot-path:** overhead middleware-цепочки при 30+ FPS не измерен — нужен бюджет/бенчмарк перед P1.
- **Distributed tracing:** `correlation_id` есть, span propagation между процессами/машинами — нет. Заложить для отладки распределённых сценариев.

---

## 14. Cleanup-чеклист (S7)
После принятия target-плана — судьба временных/устаревших файлов:
- [ ] `_salvage_digest.md` (корень, untracked) — удалить (сырьё перенесено).
- [ ] `plans/comm-system-consolidation.md` (v1) — оставить как историю ИЛИ удалить после принятия target.
- [ ] `plans/comm-system-consolidation-v2.md` (помечен SUPERSEDED) — удалить.
- [ ] `plans/_wf_comm_arch_v2.js`, `plans/_wf_comm_review.js` — служебные скрипты прогонов; оставить для воспроизводимости ИЛИ убрать.

## 15. Carve-out prototype→framework — единый список (G7)
Восстановленная фокусная таблица (в v1 была §6, в target была размазана по §7/§9/§12 P3):

| Компонент | Текущий путь (prototype) | Целевой модуль framework | Зачем universal |
|---|---|---|---|
| GUI-подписка на StateStore (helper) | `frontend/process.py` (subscribe `processes.**` + retry) | `state_store_module` (`GuiStateProxy.subscribe_telemetry`) | любое GUI подписывается на телеметрию одинаково |
| `EventBus` (zero-Qt typed pub/sub) | `domain/event_bus.py` | framework (опц. слой) | типизированные in-proc события нужны любому app |
| `GuiStateBindings` (дельта→виджет, glob-path) | `frontend/.../bindings.py` | framework frontend-слой | generic, нет app-типов |
| `DataReceiverBridge` (worker→main Qt) | `frontend/bridge/` | опц. `frontend`-слой framework (Q6) | любому Qt-app; Qt-завязка изолирована |
| Резолвер `plugin_name`→register | `app.py:509-533` | `message_module` (адресация команды плагину) | нужен любому потребителю, не только Inspector |
| `CommandDispatcherOrchestrator` (undo/redo snapshot) | `adapters/dispatch/command_dispatcher.py` | framework (после дженерификации от `Project`/`ProjectCommand`) | generic undo для любого GUI |

**Остаётся app-specific:** topology/recipe-модель, доменные команды Inspector, ConnectionMap, конкретные виджеты/привязки.
**Беречь при выносе:** `StateAdapterBase._pending_paths` (anti-loop), per-pattern фильтрация (ADR-SS-012).

---

*Документ опирается на верифицированные вердикты фазы 3 (в evidence ровно столько verdicts; часть из них refuted/partial — на них выводы НЕ строятся, см. ниже). Ключевые refuted/partial-claims учтены явно:*
- *`actions_module`/`FieldRouting`/`chain_module` — статус DEAD (0 prod), не «partial».*
- *`queue_type` НЕ протекает абстракцию и НЕ обходит `_select_queue_type`.*
- *`channel="data"/"system"` НЕ vestigial-безопасно к удалению (комплексный рефактор).*
- *`data_type` НЕ полный дубль — самостоятелен как discriminator DATA (§9.9), партиально дублирует только в командном конверте.*
- *`reply_to_request` имеет prod-потребителя (process_lifecycle).*
- *`CommandManagerConfig` живой (мёртв `DispatcherConfig`).*
- *«RolesPanel — 1 живой execute()» — **REFUTED**: 0 живых execute() даже в roles_panel (bus=None + signal не подключён) (§5).*
- *«register_message_handler — суженный контракт» — **REFUTED**: полный relay всех 6 параметров (§4).*
- *«90% cross-machine готов» — **снято** как неподтверждённая количественная оценка; два инфраструктурных блокера (§1, §3.4).*
- *«Modbus — двунаправленный эталон в хабе» — **переквалифицировано**: INBOUND мимо хаба из-за prefix-бага (§3.2).*
- *5 фич ActionBus + persistent SQL-log — переведены с `absorbed` на `capability-to-build` (фич в Orchestrator нет; §5, §9.6).*

*Выводы строились только на confirmed/partial-основаниях.*
