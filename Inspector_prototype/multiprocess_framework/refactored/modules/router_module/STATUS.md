# router_module — Статус рефакторинга

## Текущий этап: 4 / 8

## Оценки (0–10)

| Критерий | Оценка | Комментарий |
|---|---|---|
| Код | 9 | Мигрирован на CRM; _channel_registry из CRM; IMessageChannel(IChannel) |
| Тесты | 8 | ~797 строк тестов; все проходят; нет тестов _attach_logger |
| Документация | 9 | README — единый источник правды; лишние файлы удалены |
| Связанность | 9 | Наследует ChannelRoutingManager; IMessageChannel(IChannel) унифицирован |
| Дублирование | 9 | ChannelRegistry удалён из RouterManager; используется self._channel_registry из CRM |
| Работоспособность | 8 | correlation_id отсутствует (этап 5); ErrorManager не подключён |

## Что сделано в CRM-миграции (Фаза 4)

- [x] `IMessageChannel(IChannel)` — унифицированная иерархия, `write() = alias send()`
- [x] `RouterManager(ChannelRoutingManager)` — убран дублирующий ChannelRegistry
- [x] `self._channel_registry` из CRM вместо локального `self._channels`
- [x] `self.channel_dispatcher = self._dispatcher` — alias из CRM для backward compatibility
- [x] `message_dispatcher` — отдельный Dispatcher для ВХОДЯЩИХ сообщений (не смешивать!)
- [x] `AsyncSender` сохранён — реализует полный pipeline с middleware (ADR-015)
- [x] `register_channel()` переопределён: inject logger callbacks + без auto-dispatch регистрации
- [x] `register_route()` сохраняет "name-returning handler" паттерн (handler возвращает str → имя канала)
- [x] `_resolve_channels()` использует `self._channel_registry` для lookup
- [x] `_poll_all_channels()` итерирует по `self._channel_registry`
- [x] `initialize()` / `shutdown()` обновлены под CRM-архитектуру

## Ключевой паттерн RouterManager — name-returning handlers

```
register_route("order", "queue_channel")
    ↓ регистрирует: lambda msg → "queue_channel"
    ↓ НЕ: lambda msg → channel.write(msg)   ← это путь CRM
    ↓ ПОЧЕМУ: router сначала применяет middleware, ПОТОМ резолвит канал
```

`_resolve_channels(message)` → вызывает handler → получает str → `_channel_registry.get(str)` → IMessageChannel

## Чеклист рефакторинга

- [x] Этап 0: Критические баги исправлены (falsy message, print(), isinstance check)
- [x] Этап 1: IRouterManager полный (remove_message_callback, clear_middleware, get_all_channels)
- [x] Этап 2: Инъекция логирования в каналы (_attach_logger, MessageChannel с log callbacks)
- [x] Этап 3: IMessageChannel(IChannel); RouterManager(ChannelRoutingManager); _channel_registry из CRM
- [ ] Этап 4: ErrorManager интегрирован через ObservableMixin
- [ ] Этап 5: correlation_id для request-response паттерна
- [ ] Этап 6: StatsManager подключён
- [ ] Этап 7: Тесты _attach_logger + интеграционные тесты с LoggerManager
- [ ] Этап 8: Полная интеграция с process_module (config-driven setup)

## Известные проблемы

- `correlation_id` для request-response — этап 5
- `ErrorManager` не подключён — ошибки через `_log_error` попадают в `LoggerManager`
- `StatsManager` не реализован
- Config-driven channels (объявление `worker_in` через конфиг процесса) — этап 4

## История изменений

| Дата | Что сделано | Этап |
|------|-------------|------|
| 2026-03-11 | Начальное состояние | 0 |
| 2026-03-12 | fix bugs, log injection, clean adapter, clean docs | 1–2 |
| 2026-03-12 | CRM Фаза 4: RouterManager(ChannelRoutingManager), IMessageChannel(IChannel) | 3–4 |
| 2026-03-12 | CRM Фаза 5: STATUS.md обновлён | 5 |
