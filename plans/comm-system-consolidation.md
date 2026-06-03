# План консолидации систем коммуникации

> Источник: мульти-агентный аудит (13 граней, 112 находок) + ручная верификация ключевых мест.
> Аудит остановлен на фазе Verify (один агент случайно запустил full-reindex qex) → находки
> **salvaged** из журнала, приоритетные сверены вручную. Помечено: ✅ verified мной · ⚠️ audit-claim (нужен рантайм).
> Дата: 2026-06-01. Принципы: паритет (не ломать трафик), reuse хаба, **неиспользуемое ≠ удалить → обсудить**.

---

## 1. Резюме состояния (честно)

Система коммуникаций — **зрелое ядро (RouterManager) + недозамкнутый периметр**. Хаб правильный и
единый, но вокруг него наслоилось три поколения: (1) старый channel-routing (`channel="data"/"system"`,
FieldRouting, RouterSchemaAdapter) — почти мёртв, обходится через U1-fallback; (2) текущий
targets+queue_registry — несёт ~80–90% трафика, но через **несколько дверей** с одинаковым исходом;
(3) надстройки (StateStore, SHM, heartbeat) — поверх хаба. Параллельно в GUI живёт свой слой
(domain EventBus + CommandDispatcher), а framework-овский **ActionBus мёртв** (0 потребителей).
Главные боли — ровно те, что просили: **дубли** (одна операция через 3 пути) и **тупики**
(подписка GUI, ActionBus, system_events, preview). Конверт сообщения перегружен (дублирующие поля
`queue_type`/`type`, `request_id`/`correlation_id`). Ничего катастрофического — но без наведения
порядка каждый новый сценарий рискует «протечь» молча, как уже протекла телеметрия вкладки «Процессы».

---

## 2. Каталог систем коммуникации

**Главный (ядро):** RouterManager. Остальное — надстройки, GUI-слой или legacy.

| Система | Scope | Роль | Статус | Связь с RouterManager | Вердикт |
|---|---|---|---|---|---|
| **RouterManager** [`router_manager.py`](multiprocess_framework/modules/router_module/core/router_manager.py) | cross-proc | IPC-хаб: send/send_async/request/receive/broadcast + message_dispatcher + channel_dispatcher | **live** | — (ядро) | **ГЛАВНЫЙ** |
| **queue_registry** [`queues/core/manager.py`](multiprocess_framework/modules/shared_resources_module/queues/core/manager.py) | cross-proc | реальный транспорт (`send_to_queue`); ~80–90% трафика | live | транспорт под хабом | оставить (нижний слой хаба) |
| **ProcessCommunication** [`process_communication.py`](multiprocess_framework/modules/process_module/communication/process_communication.py) | cross-proc | фасад процесса (send_message/broadcast/receive) | live | фасад → router.send | оставить, но см. дубли |
| **StateStore** (Proxy/Manager/DeltaDispatcher) [`state_store_module/`](multiprocess_framework/modules/state_store_module/) | cross-proc | реактивное дерево + подписки (телеметрия) | live (но handshake хрупкий) | надстройка (send/send_async) | **главный для состояния** |
| **SHM / FrameShmMiddleware** [`generic/frame_shm_middleware.py`](multiprocess_framework/modules/process_module/generic/frame_shm_middleware.py) | cross-proc | транспорт кадров (coords в msg, payload в SHM) | live (hot path) | middleware над queue_registry | **главный для кадров** |
| **Heartbeat** [`process_heartbeat.py`](multiprocess_framework/modules/process_module/heartbeat/process_heartbeat.py) | cross-proc | liveness + workers_status | live | надстройка (send_message) | оставить |
| **domain EventBus** [`domain/event_bus.py`](multiprocess_prototype/domain/event_bus.py) | in-proc (GUI) | типизированный pub/sub | **live** | параллельная (вне хаба, корректно — in-proc) | **главный для GUI-событий** |
| **QtEventBus** [`frontend/qt_event_bus.py`](multiprocess_prototype/frontend/qt_event_bus.py) | gui | Qt-thread-safe обёртка EventBus | live | — | оставить |
| **CommandDispatcherOrchestrator** [`adapters/dispatch/command_dispatcher.py`](multiprocess_prototype/adapters/dispatch/command_dispatcher.py) | in-proc (GUI) | domain-команды + undo/redo (snapshot) | **live** | — (domain) | **главный для GUI-команд** |
| **SocketChannel** [`channels/socket_channel.py`](multiprocess_framework/modules/router_module/channels/socket_channel.py) | gui↔ext | backend_ctl driver по TCP | live (dev) | IMessageChannel в хабе | оставить |
| **ModbusChannel** [`Services/modbus/channels/modbus_channel.py`](Services/modbus/channels/modbus_channel.py) | cross-proc | образцовый IMessageChannel сервиса | live | **канонично** в хабе | эталон правил |
| **ActionBus** [`actions_module/bus.py`](multiprocess_framework/modules/actions_module/bus.py) | in-proc | command/undo-движок | **DEAD (0 prod)** | параллельная дверь | **ОБСУДИТЬ** (не удалять) |
| **FieldRouting / RouterSchemaAdapter** [`data_schema_module/core/field_routing.py`](multiprocess_framework/modules/data_schema_module/core/field_routing.py) | — | schema-driven channel routing | **DEAD (только тесты)** | заявлено, не используется | **ОБСУДИТЬ** |
| **dispatch_module** strategies (PATTERN/FALLBACK/CHAIN) [`dispatch_module/`](multiprocess_framework/modules/dispatch_module/) | — | богатый dispatch | **DEAD** (live только EXACT_MATCH) | — | **ОБСУДИТЬ** |
| **SQL service** [`Services/sql/core/sql_manager.py`](Services/sql/core/sql_manager.py) | mixed | БД через `execute_command` | live, но **вне хаба** | в обход (прямой вызов) | привести к правилам (см. §6) |
| GUI-glue: DataReceiverBridge / GuiStateBindings / _StateDeltaEmitter | gui | worker→main thread доставка | live | — | оставить (app-specific) |

**Вывод:** «главных» по сценариям — пять: RouterManager (IPC), StateStore (состояние), SHM (кадры),
EventBus+CommandDispatcher (GUI). Всё остальное — либо их транспорт/надстройка, либо legacy на обсуждение.

---

## 3. Правила общения (единый свод — одна дверь на сценарий)

| Сценарий | Канонический способ | НЕ использовать |
|---|---|---|
| Команда процессу | `RouterManager.send(targets=[proc], type="command")` (sync) / `send_async` (fire-forget) | прямой `queue_registry.send_to_queue` из прикладного кода |
| Команда воркеру | `targets=["proc.worker"]` (иерархическая адресация P2) | плоский костыль |
| Синхронный запрос-ответ | `RouterManager.request()` (correlation_id + ожидание) | `send()` с ожиданием ответа (как сломанный `_send_sync`) |
| Кадр / data-поток | data-путь + `FrameShmMiddleware`, приём `channel_types=["data"]` | слать payload в сообщении |
| Реактивное состояние / телеметрия | `StateStore` (`set`/`subscribe`) → DeltaDispatcher → `state.changed` | ad-hoc heartbeat-поля |
| Событие внутри GUI | `domain EventBus` / `QtEventBus` | `ActionBus` |
| Команда-мутация GUI + undo/redo | `CommandDispatcherOrchestrator.dispatch` | `ActionBus` |
| Внешний драйвер | `SocketChannel` (backend_ctl) | — |
| Сервис (Modbus/SQL/Hikvision) | регистрировать `IMessageChannel` в RouterManager (эталон — ModbusChannel) | прямой вызов в обход хаба (как SQL сейчас) |

---

## 4. Дубли и тупики (ПРИОРИТЕТ)

### 4.1 Дубли (одна операция — разные двери)
- ✅ **Тройная дверь в queue_registry:** `ProcessCommunication.send_to_process` ↔ `RouterManager._deliver_by_targets` ↔ `broadcast` — все три зовут `send_to_queue`, qtype-логика размазана несмотря на `_select_queue_type`. → **слить** на один путь, [`router_manager.py:255-315`](multiprocess_framework/modules/router_module/core/router_manager.py#L255-L315), [`process_communication.py:182-248`](multiprocess_framework/modules/process_module/communication/process_communication.py#L182-L248).
- ✅ **Дубль FrameShmMiddleware:** идентичная SHM-логика в `router_module/middleware/` и `process_module/generic/` (~200 строк); router-вариант не на hot-path. → **слить** в один (generic — живой).
- **Два command-движка:** `ActionBus` vs `CommandDispatcherOrchestrator` — оба создаются в [`app.py:431-557`](multiprocess_prototype/frontend/app.py#L431), живой только domain. → **слить/обсудить** (см. 4.2).
- **Два qtype-правила:** `DeltaDispatcher` хардкодит `queue_type="system"` ([`delta_dispatcher.py:115`](multiprocess_framework/modules/state_store_module/manager/delta_dispatcher.py#L115)) vs канонический `_select_queue_type()`. → **слить** на канон.
- **Modbus:** `ModbusChannel.send()` vs `ModbusPlugin.cmd_*()` — два источника истины для одних операций. → **слить**.
- **register_update дважды:** domain-dispatch + relay `PluginOrchestrator.register_changed` (у relay нет потребителя). → **fix** (убрать мёртвый relay).

### 4.2 Тупики (путь в никуда)
- ✅ **Подписка GUI на телеметрию** — `state.subscribe` уходит **без `request_id`** ([`state_proxy.py:243`](multiprocess_framework/modules/state_store_module/proxy/state_proxy.py#L243)) → нет корреляции; callback регистрируется локально даже при провале сервера ([`state_proxy.py:287`](multiprocess_framework/modules/state_store_module/proxy/state_proxy.py#L287)) → ложный успех. **+ ВТОРОЙ разрыв (✅ verified):** `state.changed` доставляется в `{gui}_system`, а GUI-воркер опрашивает только `channel_types=["data"]` ([`process.py:131`](multiprocess_prototype/frontend/process.py#L131)). → **fix** (см. отдельный план телеметрии + §7 P0).
  > ⚠️ Находка аудита «register_message_handlers не вызывается» — **ложная** (✅ проверил: `orchestrator.py:47` зовёт `initialize()`, тот регистрирует обработчики). В план не берём.
- **ActionBus** — 0 prod-потребителей ([`bus.py:199-282`](multiprocess_framework/modules/actions_module/bus.py#L199), создаётся в `app.py:433` и не передаётся никуда; `RolesPanel` получает `bus=None` → правки ролей **молча теряются**). → **ОБСУДИТЬ** (capability для будущих forms/system-settings; НО баг с RolesPanel — **fix**).
- **system_events канал** — зарегистрирован, 0 подписчиков ([`process_communication.py:111-122`](multiprocess_framework/modules/process_module/communication/process_communication.py#L111)). → **обсудить** (ждёт первого потребителя).
- **PreviewWindow** — подписан на `display.*`, продюсера кадров нет (Phase 4 placeholder). → **обсудить**.
- **FieldRouting / RouterSchemaAdapter / dispatch_module strategies** — реализованы, в проде не используются. → **обсудить** (потенциал конструктора).

---

## 5. Целевой дизайн

### 5.1 Канонический конверт сообщения
Минимальный обязательный набор + правила (избыточное — убрать/вывести):
- `type` (command|event|response|system), `sender`, `targets` (dotted `proc[.worker]`), `data`.
- `request_id` — **единое** имя корреляции (убрать дубль `data.correlation_id`; оставить зеркало только для обратной совместимости PM-обёртки на переходный период).
- `queue_type` — **выводить** из `type` через `_select_queue_type()`, не дублировать в продюсерах (DeltaDispatcher).
- `channel` — **удалить** vestigial `"data"/"system"` из продюсеров (source_producer/pipeline_executor); реальные каналы — `{proc}_data`/`{proc}_system`/`system_events`/`{proc}_local`.
- `_address` — внутреннее (адресация воркера), не для прикладного кода.

### 5.2 Единый путь отправки
Свести `send_to_process` / `_deliver_by_targets` / `broadcast` к одному внутреннему `_dispatch(targets, msg)`; публичные API остаются фасадами над ним. Документировать: прикладной код **не** зовёт `queue_registry` напрямую.

### 5.3 Дженерик request/reply
Сейчас ответ инициатору шлёт **только** `_handle_process_command` вручную ([`process_manager_process.py:893-911`](multiprocess_framework/modules/process_manager_module/process/process_manager_process.py#L893)); `reply_to_request` в дженерик-диспетчере **не вызывается** (0 ссылок, ✅ verified). → Встроить в `receive()`/`message_dispatcher`: если у входящего есть `request_id` и обработчик вернул значение — **авто-reply** результатом. Это разблокирует надёжный `subscribe` (Вариант B плана телеметрии) и любые будущие sync-обработчики без ручной обвязки.

### 5.4 Судьба «канала»
Channel-routing оставить как **возможность** (system_events, schema-driven) — но из горячего пути убрать: targets-адресация каноническая, vestigial-поле `channel` удалить у продюсеров, а не стрипать post-hoc в `send_to_process:210`.

---

## 6. Carve-out: что из prototype уходит во framework

| Компонент | Текущий путь (prototype) | Целевой модуль framework | Почему универсально |
|---|---|---|---|
| Паттерн GUI-подписки на StateStore (subscribe `processes.**` + emitter + retry) | [`frontend/process.py:78-101`](multiprocess_prototype/frontend/process.py#L78) | `state_store_module` (helper `GuiStateProxy.subscribe_telemetry`) | любое GUI-приложение на фреймворке подписывается на телеметрию так же |
| Ручная регистрация `state.changed` handler | `process.py:91` (обходит ADR-SS-006) | дочинить авто-регистрацию в `ProcessModule._init_state_proxy` для Qt-варианта | онбординг нового GUI-процесса не должен помнить про ручную привязку |
| Резолвер `plugin_name`→register / адрес (CommandSender) | `app.py:509-533` | `message_module` (адресация команд плагину) | нужно любому потребителю, не только Inspector |
| DataReceiverBridge (worker→main thread) | [`frontend/bridge.py`](multiprocess_prototype/frontend/bridge.py) | обсудить: generic Qt-bridge в опц. `frontend`-слой framework | паттерн переиспользуем, но Qt-завязка |

**Остаётся app-specific:** topology/recipe-модель, доменные команды Inspector, ConnectionMap, конкретные виджеты/привязки.
**Проверка на Services:** ModbusChannel уже соблюдает правила (эталон); SQL — нет (см. 4 / §7 P2). Universal-правила валидны на втором потребителе.

> Учитывает существующий [`plans/prototype-carveout.md`](plans/prototype-carveout.md): вынос universal-частей как forcing function.

---

## 7. План этапами P0 → P3

> **Инвариант приёмки каждого этапа:** Pipeline (камера→обработка→дисплей) работает. Проверка — `/run-proto` + Qt-smoke, кадры идут, телеметрия не регрессирует.

### P0 — разблокировать телеметрию (критично, последовательно, горячий путь)
- **Этап 0 (Debugger):** рантайм-подтверждение точки обрыва подписки — крутит ли GUI системный цикл (`_message_processing_loop`, `['system']`) параллельно `data_receiver`; доходит ли `state.changed`. DEBUG-логи в 3 точках.
- **Fix подписки** (см. отдельный `plans/processes-tab-telemetry.md`): ретрай доставки + различать «доставлено»/«отклонено» + закрыть `data`/`system`-разрыв приёма. Риск: средний (горячий путь). Паритет: heartbeat/старт-стоп не трогать.
- **RolesPanel bus=None** — отдельный мелкий fix (правки ролей теряются).
- Файлы: `state_proxy.py`, `frontend/process.py`, `roles_panel.py`. **Последовательно**, без worktree.

### P1 — единый путь отправки + конверт (framework, аккуратно)
- Свести `send_to_process`/`_deliver_by_targets`/`broadcast` к одному `_dispatch` (паритет — тот же `send_to_queue`).
- Удалить vestigial `channel="data"/"system"` у продюсеров (source_producer/pipeline_executor), убрать post-hoc strip.
- `DeltaDispatcher` → канонический `_select_queue_type` вместо хардкода.
- Риск: высокий (hot data-path кадров). **Последовательно**, обширные тесты роутера + integration кадров.

### P2 — дженерик request/reply + сервисы к правилам (framework + Services)
- Авто-reply по `request_id` в `receive()`/`message_dispatcher`; затем перевести `StateProxy.subscribe` на `request()` (Вариант B телеметрии).
- SQL-сервис: обернуть `execute_command` в `IMessageChannel` (как Modbus) ИЛИ задокументировать как осознанное исключение.
- Слить дубли: FrameShmMiddleware (2→1), Modbus `cmd_*` vs `channel.send`.
- Риск: средний. Частично **параллельно** (worktree): SQL-channel и FrameShm-merge независимы.

### P3 — legacy и косметика (обсудить, не удалять)
- ActionBus / FieldRouting / RouterSchemaAdapter / dispatch_module strategies / system_events / PreviewWindow / RingBufferWriter / local_channel — **обсуждение** с владельцем: оставить как capability конструктора (пометить `@experimental`/доком) vs убрать.
- Унификация терминологии `request_id`/`correlation_id`; вынести suffix-парсинг каналов в утилиту; double `register_commands_with_router` — задокументировать.
- Риск: низкий. **Параллельно**.

---

## 8. Быстрые победы vs большие рефакторинги

**Быстрые победы (низкий риск, высокий эффект):**
- RolesPanel bus=None fix (теряются правки ролей).
- `DeltaDispatcher` → `_select_queue_type` (1 строка, убирает источник рассинхрона).
- Убрать мёртвый relay `register_changed`.
- Удалить дубль-класс DataReceiverBridge (shadowing).

**Большие рефакторинги (планировать отдельно):**
- Единый `_dispatch` + чистка конверта (P1) — трогает hot path, нужен полный регресс.
- Дженерик request/reply (P2) — меняет контракт ответов, осторожно с PM-обёрткой.
- Carve-out GUI-подписки во framework — после стабилизации телеметрии.

**Что разблокирует надёжную подписку GUI:** дженерик request/reply (5.3) + закрытие `data`/`system`-разрыва приёма (P0). Первое — во framework, второе — на стыке framework/prototype (кандидат на carve-out).

---

## Приложение: сырые данные
Полный дамп (13 карт + 112 находок) — `_salvage_digest.md` (временный, в корне; удалить после переноса в этот план). Разбивка: 15 duplicate · 22 dead-end · 26 active-bug · 34 smell · 15 unused-capability.
