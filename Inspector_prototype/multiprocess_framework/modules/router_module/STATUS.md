# router_module — Статус рефакторинга

## Текущий этап: 5 / 8

## Оценки (0–10)

| Критерий | Оценка | Комментарий |
|---|---|---|
| Код | 8 | CRM-наследование стабильно; `router_manager.py` ~600 LOC; мёртвый `_channel_registry.py` удалён; `_stats` под Lock |
| Тесты | 8 | 4 файла тестов; адаптеры, `channel_types`, `_attach_logger`, concurrent stats; нет интеграции с LoggerManager в отдельных e2e |
| Документация | 8 | README; `DECISIONS.md` ADR-RTR-001…006; §6.9 в `ARCHITECTURE.md`; индекс в главном `DECISIONS.md` |
| Связанность | 9 | Чистое наследование CRM; осознанный импорт `IChannel` (ADR-RTR-005) |
| Дублирование | 9 | Локальный ChannelRegistry удалён; единый реестр из CRM |
| Работоспособность | 7 | correlation_id, ErrorManager/StatsManager — следующие этапы по плану модуля |

## Обновление 2026-04-02

- **`RouterManagerConfig`:** поле **`duplicate_messages_to_logger`** (см. **ADR-113**) — согласование с `ProcessManagers` и `ManagersConfig`.

## Обновление 2026-04-09 (план `10_router_module`)

- Удалён неиспользуемый `core/_channel_registry.py`; реестр только из CRM.
- Thread-safe счётчики `_stats` (`threading.Lock`, `_inc_stat`, снимок в `get_stats`).
- Тесты: `test_router_adapter.py`, `test_schema_adapter.py`, расширения в `test_router_manager.py`.
- Документация: `modules/router_module/DECISIONS.md`, §6.9 в `ARCHITECTURE.md`, строка в главном `DECISIONS.md`.

## Что сделано в CRM-миграции (Фаза 4)

- [x] `IMessageChannel(IChannel)` — унифицированная иерархия, `write() = alias send()`
- [x] `RouterManager(ChannelRoutingManager)` — убран дублирующий ChannelRegistry
- [x] `self._channel_registry` из CRM вместо локального `self._channels`
- [x] `self.channel_dispatcher = self._dispatcher` — alias из CRM для backward compatibility
- [x] `message_dispatcher` — отдельный Dispatcher для ВХОДЯЩИХ сообщений (не смешивать!)
- [x] `AsyncSender` сохранён — реализует полный pipeline с middleware (глобальный ADR-015 / ADR-CRM-003)
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
- [x] Этап 7: Тесты адаптеров + `_attach_logger` + `channel_types` (интеграционные с LoggerManager — опционально позже)
- [ ] Этап 8: Полная интеграция с process_module (config-driven setup)

## Известные проблемы

- **configs/:** `RouterManagerConfig` (SchemaBase) — метаданные; рантайм не переведён
- `correlation_id` для request-response — этап 5 (чеклист)
- `ErrorManager` не подключён — ошибки через `_log_error` попадают в `LoggerManager`
- `StatsManager` не реализован
- Config-driven channels (объявление `worker_in` через конфиг процесса) — этап 8

## История изменений

| Дата | Что сделано | Этап |
|------|-------------|------|
| 2026-03-11 | Начальное состояние | 0 |
| 2026-03-12 | fix bugs, log injection, clean adapter, clean docs | 1–2 |
| 2026-03-12 | CRM Фаза 4: RouterManager(ChannelRoutingManager), IMessageChannel(IChannel) | 3–4 |
| 2026-03-12 | CRM Фаза 5: STATUS.md обновлён | 5 |
| 2026-04-09 | План 10: dead code, Lock для _stats, тесты адаптеров, DECISIONS + ARCH §6.9 | 5 |
