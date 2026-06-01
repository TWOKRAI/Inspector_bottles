# router_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) (ADR-008 Dict at Boundary, ADR-013 CRM, ADR-015 AsyncSender)

## ADR-RTR-001 (was ADR-153): RouterManager наследует ChannelRoutingManager

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** RouterManager, LoggerManager, ErrorManager дублировали ChannelRegistry + Dispatcher.  
**Решение:** `RouterManager(ChannelRoutingManager)`. CRM даёт `_channel_registry`, `_dispatcher`, `_buffer` (не используется). RouterManager добавляет: AsyncSender (outgoing pipeline с middleware), AsyncReceiver, message_dispatcher.  
**Последствия:** Удалён локальный `core/_channel_registry.py` (мёртвый код после миграции). Единый паттерн для всех CRM-наследников. Для `channel_types` при опросе каналов суффикс — полный хвост после префикса `{process.name}_`, а не «последний сегмент по `_`», иначе ломаются имена вида `{process}_data_extra`.

## ADR-RTR-002 (was ADR-154): Name-returning handler pattern

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** CRM `register_route()` вызывает `channel.write()` напрямую. RouterManager'у нужен middleware pipeline перед send.  
**Решение:** `register_route("key", "channel_name")` регистрирует `lambda msg: "channel_name"`. `_resolve_channels()` получает строку → `_channel_registry.get(name)`.  
**Последствия:** Middleware всегда применяется. Dispatch возвращает имя канала, не результат отправки.

## ADR-RTR-003 (was ADR-155): Два dispatcher'а — channel + message

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Routing outgoing (в какой канал?) и handling incoming (какой handler?) — разные задачи.  
**Решение:** `channel_dispatcher` = CRM's `_dispatcher` (исходящие). `message_dispatcher` = отдельный Dispatcher (входящие).  
**Последствия:** Чёткое разделение; нет путаницы между routes и handlers.

## ADR-RTR-004 (was ADR-156): Thread-safe _stats с Lock

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `_do_send()` вызывается из main thread (sync `send()`) и AsyncSender thread (`send_async()`). `dict["key"] += 1` — не атомарная операция.  
**Решение:** `_stats_lock = threading.Lock()`. Helper `_inc_stat()` для всех мутаций. `get_stats()` читает снимок `_stats` под lock.  
**Последствия:** Корректные счётчики при параллельных sync и async отправках.

## ADR-RTR-005 (was ADR-157): IMessageChannel(IChannel) — осознанный cross-module import

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** `interfaces.py` строка 17: `from ..channel_routing_module.interfaces import IChannel`. Это sibling-module relative import.  
**Решение:** Осознанная связь. IMessageChannel расширяет IChannel → QueueChannel совместим с CRM `ChannelRegistry` и `RouterManager`.  
**Последствия:** Единая иерархия каналов. Документировано как допустимое зацепление.

## ADR-RTR-006 (was ADR-158): Сохранение registration API (register_channel_handler, register_channel_scenario, cleanup)

**Статус:** принято  
**Дата:** 2026-04-09  
**Контекст:** Методы `register_channel_handler()`, `register_channel_scenario()`, `cleanup()` не имеют внешних вызовов на момент рефакторинга. Однако анализ `multiprocess_prototype_v2` показывает паттерн config-driven setup: каналы из конфига (`queues` dict в ProcessConfigBase), команды через `command_manager.register_command()`. Phase 8 STATUS.md предусматривает config-driven channel setup в RouterManager.  
**Решение:** Сохранить все registration-методы. Они образуют инфраструктуру для:
- `register_channel_handler` — аналог `command_manager.register_command()` для каналов
- `register_channel_scenario` — сценарная маршрутизация (multi-step pipelines)
- `cleanup()` — стандартный alias-паттерн для shutdown  
**Последствия:** LOC не сокращается на ~28 строк, но API готов к Phase 8 без breaking changes.

## ADR-RTR-007: Контракт routing-таблицы (`routing/`) — нормализация kind ДО таблицы

**Статус:** принято  
**Дата:** 2026-05-31  
**Контекст:** План `transport-router-hub` (P0.2) фиксирует контракт хаба — «`send` выбирает один канал по типу груза». Глобальное решение — [ADR-COMM-001](../../DECISIONS.md). Аудит (recon #1) показал, что на живых билетах поле `type` НЕ всегда соответствует целевому каналу: state-телеметрия несёт `type="event"`/`"command"`, но семантически — STATE (диспатч по `command="state.changed"`). Прямая таблица `MessageType → channel` на таких билетах промахивается.  
**Решение:** Подмодуль `router_module/routing/` — **декларация** контракта (без проводки в рантайм, она в P1):
- `MESSAGE_TYPE_TO_CHANNEL: dict[MessageType, str]` — база (type → channel-kind);
- `resolve_channel_kind(msg)` — **нормализация ДО таблицы**: сперва override по префиксу `command` (`COMMAND_PREFIX_TO_CHANNEL`, напр. `state.*` → `state`), затем таблица по `MessageType`; неизвестный `type` без покрытия → `UnknownMessageTypeError` (а НЕ тихий drop);
- `channel_name(process, kind)` → `f"{process}_{kind}"` («склейка» осей адрес × kind, совпадает с очередями `{proc}_system`/`{proc}_data`);
- `resolve_route(s)` → `RouteDecision(process, kind, channel, subpath)` — чистое ядро `send` будущего address-aware канала.
**Ключевое:** STATE — это **channel-kind**, выводимый из `command="state.*"`, а **НЕ** член enum `MessageType` (его не вводим — план запрещает новый `kind`). Новый Channel-Protocol тоже не вводится — address-aware канал будет подклассом существующего `MessageChannel` (P1.1).  
**Последствия:** Резолв канала работает на текущих (несогласованных по `type`) билетах без их немедленной миграции. `_resolve_channels` подключит `resolve_channel_kind` в P1.2. Контракт address-aware канала и решения по recon #2/#3/#4/#6 — в docstring `routing/address_aware_channel.py`.  
**Refs:** [ADR-COMM-001](../../DECISIONS.md), [ADR-COMM-004](../../DECISIONS.md), [plans/2026-05-31_transport-router-hub/plan.md](../../../plans/2026-05-31_transport-router-hub/plan.md)

## ADR-RTR-008: SocketChannel — внешний driver-доступ как обычный IMessageChannel

**Статус:** принято
**Дата:** 2026-06-01
**Контекст:** Нужен headless-доступ к бэкенду извне (driver под MCP — отлаживать backend без GUI/qt-mcp). Инвариант владельца: ВСЁ общение с бэкендом строго через `RouterManager`, без сайд-каналов. ProcessManager — отдельный OS-процесс; внешний процесс не подключить к shared `queue_registry` процессов. План `backend-control-mcp` P2 ([plan](../../../plans/2026-05-31_backend-control-mcp/plan.md), [дизайн](../../../plans/2026-05-31_backend-control-mcp/P2_socket_design.md)).
**Решение:** `SocketChannel(MessageChannel)` — серверный TCP-эндпоинт, **обычный** `IMessageChannel` (сиблинг `QueueChannel`), хостится в ProcessManager (`register_channel` — by-design extension). Делает ТОЛЬКО байтовый I/O (newline-JSON). Связь с router'ом — `SocketBridgeAdapter.on_inbound`: `router.request(msg)` (P0.5 request-response) → `router.send({type:response, channel:"backend_ctl", request_id, result})` → `_resolve_channels(channel=)` → `SocketChannel.send`. Внешний driver (`backend_ctl/`) шлёт те же router-сообщения, что GUI (общий билдер `message_module/builders/command_envelopes.py` — один источник правды GUI+driver), плюс reply-поля. Гейт `BACKEND_CTL=1` + bind 127.0.0.1.
**Ключевое:**
- `poll()` намеренно no-op: inbound — push через read-loop (`on_inbound`), не pull. Имя канала без префикса `{process}_` → `receive`-цикл его не опрашивает (и это верно).
- `request()` крутится в read-потоке сокета, резолвится в system-цикле PM (другой поток) → дедлок-контракт P0.5 соблюдён даром.
- Сокет = граница ровно Claude↔driver; кадры/SHM через сокет НЕ гоняем (Dict at Boundary).
- Совпадает с `transport-router-hub` P3 («ещё один IMessageChannel»), второй транспорт не плодим.
**Последствия:** Внешний доступ без нарушения инварианта «всё через router». В проде endpoint не существует (env-гейт). GUI-форма команд вынесена в билдер — `CommandSender` переведён на него (вывод байт-в-байт, регрессия зелёная). Остановка PID-specific (`teardown` закрывает канал + unregister), без глобального kill.
**Refs:** [plans/2026-05-31_backend-control-mcp/](../../../plans/2026-05-31_backend-control-mcp/plan.md), ADR-RTR-005 (IMessageChannel), [ADR-COMM-001](../../DECISIONS.md) (Dict at Boundary)
