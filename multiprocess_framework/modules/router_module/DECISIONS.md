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
