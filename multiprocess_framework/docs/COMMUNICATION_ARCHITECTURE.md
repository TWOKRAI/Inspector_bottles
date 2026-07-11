# Архитектура коммуникаций — контракт (роли + одна дверь на сценарий)

> **Назначение:** единый источник правды по коммуникациям проекта. Кто за что отвечает, какой ОДИН канонический механизм на каждый сценарий, какие правила нельзя нарушать. Цель — чтобы разработчик и агент следовали схеме **без повторного анализа**.
> **Это ЦЕЛЕВАЯ схема (канон), которой придерживаемся.** Где сегодняшняя реальность отличается от канона — §11 «Текущие отклонения» (со ссылками на план).
> **Companion-документы:** [`plans/_archive/comm-system-target-architecture.md`](../../plans/_archive/comm-system-target-architecture.md) — «почему так» + миграция P0→P3 (верифицированный аудит); [`ROUTING_GLOSSARY.md`](ROUTING_GLOSSARY.md) — термины (канал ≠ имя процесса).
> Дата: 2026-06-02.

---

## 0. Главное за 30 секунд

- **RouterManager — ЕДИНЫЙ хаб коммуникаций.** Он маршрутизирует по `type` (вид груза) + `targets` (адрес). Он НЕ транспорт и НЕ бизнес-логика — это слой **маршрутизация + middleware + реестр каналов**.
- **Транспорт живёт ПОД хабом:** `queue_registry` (mp.Queue между процессами) и SHM/`MemoryManager` (zero-copy кадры). **Прикладной код их напрямую не зовёт** — только через RouterManager.
- **Внешний мир = канал.** Modbus / Socket / Redis / MCP / SQL подключаются как подкласс `IMessageChannel`, ядро не трогается.
- **Шесть «главных» систем:** RouterManager (IPC) · StateStore (состояние) · SHM (кадры) · EventBus (in-proc события) · CommandDispatcherOrchestrator (GUI-команды/undo) · Logger/Error/Stats (наблюдаемость).
- **Одна операция — одна дверь.** См. §3. Если для задачи есть канонический путь — другой не используем.

```
GUI / домен (in-proc)   EventBus · QtEventBus · CommandDispatcherOrchestrator · GuiStateBindings
        │
ХАБ (framework)         RouterManager  ──  send/send_async/request/broadcast/receive
        │                               +  message_dispatcher · channel_dispatcher · middleware
        │                               +  реестр IMessageChannel
        ├── Транспорт           queue_registry (mp.Queue)  ·  SHM/MemoryManager (кадры, hot-path)
        ├── Внешние каналы      SocketChannel · ModbusChannel · (Redis/MCP/SQLChannel)
        └── Контракт груза      Message (Pydantic value object, Dict at Boundary)
```

---

## 1. Роли (единственная ответственность каждого)

| Система | Слой | Единственная ответственность | НЕ её дело |
|---|---|---|---|
| **RouterManager** | хаб | маршрутизация по type+адрес, middleware, реестр каналов | физический транспорт, бизнес-логика |
| **queue_registry** (`SharedResourcesManager`) | транспорт | физическая доставка `mp.Queue` между процессами | решать «кому» (это хаб) |
| **MemoryManager / SHM** | транспорт | zero-copy кадры (numpy через memoryview) | команды/конфиг (это хаб) |
| **Message / MessageAdapter** | контракт | value object груза (Dict at Boundary), фиксация sender | маршрутизация |
| **Dispatcher** (`dispatch_module`) | примитив | один движок key→handler | межпроцессность |
| **CommandManager** | фасад | регистрация обработчиков команд процесса (`register_command`) | undo, GUI |
| **IMessageChannel** + подклассы | адаптер | мост внешнего транспорта (Socket/Modbus/Redis/MCP/SQL) под хаб | внутрипроцессная логика |
| **StateStore** (+ `StateProxy`/`GuiStateProxy`) | состояние | реактивное cross-process дерево: `set`/`subscribe`/дельты | события-факты, undo |
| **EventBus / QtEventBus** | события | типизированные in-proc события-факты GUI | состояние, IPC |
| **CommandDispatcherOrchestrator** | команды GUI | GUI-мутации + undo/redo (snapshot) | IPC-команды процессам |
| **RegistersManager** | конфиг | живые регистры плагинов: значения + per-field observers + `FieldInfo` для GUI | транспорт |
| **LoggerManager / ErrorManager / StatsManager** | наблюдаемость | логи/ошибки/метрики поверх CRM | маршрутизация сообщений |
| **ProcessManagerProcess** | оркестрация | реестр процессов, spawn, `replace_blueprint`, broadcast статуса, ответы на request | транспорт груза |
| **ProcessHeartbeat** | liveness | heartbeat + `workers_status` телеметрия | бизнес-данные |
| **DataReceiverBridge** | GUI-мост | доставка worker→main thread (Qt) для frame/command | состояние (идёт через GuiStateProxy) |
| **GuiStateBindings** | GUI-мост | последняя миля: дельта состояния → виджет (glob-path) | транспорт |
| **channel_routing_module** (CRM) | база | общая инфраструктура каналов/буферов под Router/Logger/Error/Stats | реактивность (ортогонален StateStore) |

---

## 2. Главный принцип: маршрутизация по двум осям

У сообщения **две независимые оси**, не путать (см. [`ROUTING_GLOSSARY.md`](ROUTING_GLOSSARY.md)):

1. **Адрес** — `targets` = «кому»: `proc` → `proc.worker` → глубже (иерархия). Решает, в очередь какого процесса/воркера попадёт сообщение.
2. **Вид груза (kind)** — `type` (`command`/`event`/`response`/`system`/`data`/…): решает, в какой канал/очередь процесса (`_system` vs `_data`) и как обрабатывать.

`targets` — это **имя процесса**, НЕ канал. `channel` в конверте — отдельная (низкоуровневая) вещь; прикладной код им не оперирует.

---

## 3. Канон по сценариям — ОДНА дверь

| Сценарий | ✅ Канонический механизм | ❌ НЕ использовать |
|---|---|---|
| Команда процессу | `RouterManager.send(targets=[proc], type="command")` · `send_async` (fire-forget) | прямой `queue_registry.send_to_queue` из прикладного кода |
| Команда воркеру/глубже | `targets=["proc.worker"]` (иерархический адрес) | плоские костыли |
| Синхронный запрос-ответ | `RouterManager.request()` (correlation_id) → авто-reply по `request_id` | `send()` с ожиданием ответа вручную |
| Кадр / data-поток | data-путь + `FrameShmMiddleware`; приём `receive(channel_types=["data"])` | слать payload кадра внутри сообщения |
| Реактивное состояние / телеметрия | `StateStore.set`/`subscribe` → DeltaDispatcher → `state.changed`; в GUI — `GuiStateProxy` | ad-hoc поля в heartbeat |
| Внутри-GUI событие (факт) | `domain EventBus` / `QtEventBus` | StateStore, ActionBus |
| GUI-команда + undo/redo | `CommandDispatcherOrchestrator.dispatch` | ActionBus (выводится из проводки) |
| Доставка worker→main thread | frame/command — `DataReceiverBridge`; state — напрямую `GuiStateProxy → GuiStateBindings` | второй hop через bridge для state |
| Конфиг плагина (значения/поля) | `RegistersManager` (+ observers, `FieldInfo`) | дублировать в StateStore |
| Логи / ошибки / статистика | `self._log_*` / `self._track_error` / `self._record_metric` (через `ObservableMixin`) | прямой вызов LoggerManager/loguru |
| Внешний драйвер / сервис / контроллер | подкласс `IMessageChannel` в RouterManager (inbound — **push**, см. §4) | прямой вызов в обход хаба |
| Оркестрация процессов (старт/стоп/replace) | команды в `ProcessManagerProcess` через хаб | прямое управление процессами из GUI |

---

## 4. RouterManager как хаб + каналы

### Контракт `IMessageChannel`
`name`, `channel_type`, `send(msg: dict) -> dict`, `poll(timeout) -> list[dict]`, опц. `start_listening(callback)`/`stop_listening()`/`get_info()`.
Регистрация: `RouterManager.register_channel()` — **тонкий** override (type-check + обязательная инъекция log-callbacks). Ядро не трогается. Доказано: Queue/Socket/Modbus регистрируются одинаково.

> **Правило подключения:** любой новый канал (Redis/MCP/SQLChannel) ОБЯЗАН получить log-инъекцию при `register_channel` — иначе ошибки канала уйдут в тишину. Это часть контракта.

### Две модели интеграции
- **Push (`on_inbound`) — КАНОН для внешних/контроллер-каналов** (Socket, Redis, MCP, Modbus-INBOUND). Канал сам кормит хаб, не зависит от polling-цикла и prefix-фильтра. Эталон — `SocketChannel`.
- **Pull (`poll`)** — только для синхронных источников, где push невозможен. Опрашивается в `_poll_all_channels` (требует корректного префикса процесса в имени канала).

> **Решение владельца (Q9):** для контроллеров inbound идёт **push**. Modbus физически опрашивает ПЛК внутри плагина (природа протокола), но прочитанное **толкает в хаб через `on_inbound`** — для хаба все внешние каналы выглядят одинаково (push).

### Как добавить канал (Redis / MCP / SQL)
1. Подкласс `MessageChannel(IMessageChannel)`; реализовать `send` (outbound) и push-доставку inbound через `on_inbound`.
2. `register_channel(channel)` в процессе-владельце (log-инъекция — автоматически по контракту).
3. Ядро RouterManager НЕ менять.

### SHM и WorkerPoolDispatcher — НЕ каналы хаба
- **SHM/MemoryManager** — оправданный отдельный hot-path (кадры). Хаб **конфигурирует** SHM (через `wire.configure` middleware), но не поглощает транспорт. Гибрид «почта для команд + трубы для кадров» — оставить.
- **WorkerPoolDispatcher** — мёртв, **реанимации запрещена**. Cross-process dispatch тяжёлых задач — через worker-handler routing поверх хаба.

---

## 5. Адресация (иерархическая, cross-machine-ready)

- Формат: `proc[.worker[.deeper]]`. Плоское имя `proc` == `["proc"]` (backward-совместимо).
- Чистые JSON-safe функции: `split_address` / `process_of` / `worker_of` / `normalize_targets` (`message_module.addressing`).
- Провязано: cross-process (`_deliver_by_targets`) + intra-process (`_route_to_worker` + `register_worker_handler`).
- **Machine-сегмент** (`machine.process.worker`) — **зарезервирован в хелперах разбора** (решение Q1: закладываем сейчас, чтобы не переписывать worker-routing), но рантайм-резолв нелокальных адресов НЕ реализован. Это один из блокеров реального cross-machine.

---

## 6. GUI signal-слой — пять направлений, по канону на каждое

| Направление | ✅ Канон | Лишнее (убрать) |
|---|---|---|
| (а) backend→GUI телеметрия | `GuiStateProxy` (транспорт, маршалит в Qt main thread) → `GuiStateBindings` | второй no-op hop через `DataReceiverBridge` для state |
| (б) внутри-GUI событие | `EventBus` + `QtEventBus` | — |
| (в) GUI-команда + undo | `CommandDispatcherOrchestrator` (snapshot) | второй undo-движок `ActionBus` |
| (г) worker→main thread (frame/command) | `DataReceiverBridge` | single-slot `set_*_callback` → multi-subscriber; closure `_state_multiplexer` |
| (д) адресация команды плагину | `CommandSender` + резолвер `plugin_name`→register | address-резолв в event-listener'е (вынести в резолвер) |

---

## 7. Канонический конверт сообщения

Создавать **только через `MessageAdapter`** (фиксирует sender).
**Минимальный контракт:** `type`, `sender`, `targets` (dotted), `data`, `request_id`, опц. `channel`.
- `request_id` — **единое** имя корреляции. `data.correlation_id` — только backward-shim чтения.
- `queue_type` — выводится из `type` (`_select_queue_type`); в продюсерах не хардкодить.
- `data_type` — самостоятелен как discriminator для типа `DATA` (frame_ready/state_delta/register_update); не удалять.
- Мёртвые поля (`routers`, `subtype`) — на удаление (см. план §11). `IMessageFactory` — удалён (§11.4).

---

## 8. Capabilities конструктора — не удалять (помечены `@experimental`)

Принцип: **«не используется ≠ не нужно»** — удаляем только доказанный дубль.

- **FieldRouting.channel + RouterSchemaAdapter + routing_table** — оживить как **декларативный kind-слой** над каналами (FieldRouting декларирует kind/priority, не произвольную channel-строку). Решение Q3.
- **dispatch стратегии PATTERN/FALLBACK/CHAIN + сценарии** (`ScenarioBuilder`/`ScenarioManager`/`dispatch_scenario`) — reserved для vision/processing-pipeline. Решение Q4 (сценарии беречь приоритетно).
- **IBufferStrategy** (`BatchBuffer` triple-trigger, `AggregationWindow`, `AsyncSenderBuffer`) — точка расширения буферизации (back-pressure/batch для высокочастотной телеметрии).
- **system_events** канал — задел под cross-process событийную шину; ждёт первого подписчика (решение Q5).
- **PreviewWindow** — продуктовый задел превью кадров (подписка `display.*`); продюсера дать при реализации фичи (решение Q8). Подписку не удалять.
- **StateStore**: `coalesce()`, selectors/middleware/persistence/recipes, `StateAdapterBase._pending_paths` (anti-loop — беречь), per-pattern фильтрация (ADR-SS-012).
- **SocketBridgeAdapter** — канонический рецепт sync-over-async для cross-machine адаптеров.
- **InMemoryRouter** — тест-helper (ADR-SS-010).

---

## 9. Запреты (нарушение = регресс архитектуры)

1. Прикладной код **не зовёт** `queue_registry.send_to_queue` / `broadcast_message` напрямую — только через RouterManager (см. §10).
2. Плагин знает только `PluginContext`, **не импортирует** `multiprocess_prototype.*` (ADR-120).
3. Плагин **не читает SHM напрямую** — только через framework middleware.
4. Внешний транспорт **не вызывается в обход хаба** (исключение SQL — см. §11, временно).
5. Логи/ошибки — **не глушить** молча (`except: pass`) — логировать через ObservableMixin.
6. `WorkerPoolDispatcher` **не реанимировать**.

---

## 10. «Разные двери для queue» — правило одной двери

**Проблема (исторически):** одна операция «положить в очередь процесса» вызывается тремя путями —
`ProcessCommunication.send_to_process` ↔ `RouterManager._deliver_by_targets` ↔ `broadcast` — все три в итоге зовут `queue_registry.send_to_queue`, qtype-логика размазана.

**Правило (канон):**
- Единственная **публичная** дверь — `RouterManager.send` / `send_async` / `request` / `broadcast`.
- Внутри они сходятся в один приватный `_dispatch(targets, msg)` (целевое; миграция — план P1).
- `queue_registry` — **низкий транспортный слой**, прикладной/плагинный код его не видит.
- fan-out (broadcast) — через `register_broadcast_route` / `targets=["all"]`, не прямой `queue_registry.broadcast_message`.

Так у каждого «положить в очередь» — одна дверь, предсказуемый поток, проще отлаживать.

---

## 11. Текущие отклонения от канона (today ≠ target)

Чтобы агент не принял канон за уже-реализованное. Каждое — в плане миграции.

> **Полный список багов/мелких правок — НЕ здесь** (S4). Эта таблица = крупные отклонения. 24 quick-wins (мёртвый relay, битый `MessageAdapter.create_message`, broken console help, потеря/контракты пп.20-22, heartbeat-порядок, EventBus-инвариант внутри bucket и т.д.) + этап **P1.5** — в [`plans/_archive/comm-system-target-architecture.md`](../../plans/_archive/comm-system-target-architecture.md) §11/§12.

| Отклонение сегодня | Канон | Где чинится |
|---|---|---|
| 3 двери в `queue_registry` ещё не сведены к `_dispatch` | §10 | план **P1** |
| SQL вызывается `execute_command` **в обход хаба** | `SQLChannel(IMessageChannel)` (решение Q2 — ввести) | план **P2** |
| Modbus **INBOUND** идёт мимо хаба (prefix-баг; телеметрию делает `_poll_loop` плагина) | push в хаб через `on_inbound` (решение Q9) | план **P2** |
| GUI-подписка на телеметрию (`state.subscribe`) сломана (нет `request_id`, ложный успех, `data`/`system` разрыв) | request/reply + единый приём | план **P0** (сверить с memory `telemetry_subscription_bug` — возможно частично починено) |
| `ActionBus` ещё в GUI-проводке (мёртв, `RolesPanel bus=None`) | один undo = Orchestrator; ActionBus вывести | план **P0** (RolesPanel) / **P3** |
| `machine.process.worker` резолв не реализован | зарезервировано (Q1), реализация позже | план / открытый вопрос |
| `vestigial channel="data"/"system"` у продюсеров | убрать у источника (комплексный рефактор) | план **P1** |
| 2× `FrameShmMiddleware` + дубль ring-buffer | слить в один | план **P2** |
| Утечка SHM при `replace_blueprint` (нет `release_process_memory`) | добавить освобождение | план **P2** |
| 5 silent-drop'ов (крит.: `_route_to_worker` теряет `process.stop`) | логировать/пробрасывать | план **P0** |

---

## 12. Открытые вопросы (ждут решения владельца)

- **`local_channel`** — фигурировал в первом аудите, в v2 не переисследован → доразобрать (что это, нужен ли).

> Все развилки Q1–Q9 согласованы — см. решения в [`plans/_archive/comm-system-target-architecture.md`](../../plans/_archive/comm-system-target-architecture.md) §13. `DataReceiverBridge` (Q6) → вынести в опц. `frontend`-слой framework (P3).

---

*Полный верифицированный аудит, матрица сохранности функционала и план миграции — [`plans/_archive/comm-system-target-architecture.md`](../../plans/_archive/comm-system-target-architecture.md). Термины и различие «канал ≠ имя процесса» — [`ROUTING_GLOSSARY.md`](ROUTING_GLOSSARY.md).*
