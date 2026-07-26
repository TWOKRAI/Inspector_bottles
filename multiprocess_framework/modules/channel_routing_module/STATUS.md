# channel_routing_module — Статус рефакторинга

## Текущий этап: 9 / 9  ✅

## Оценки (0–10)

| Критерий | Оценка | Комментарий |
|---|---|---|
| Код | 9 | CRM + ChannelRegistry + 3 буфера + normalize_config + ChannelRoutingConfig + observability/ObservabilityHub (Ф5.15) |
| Тесты | 9 | 84 теста (58 base + 26 observability: hub/bounded-channel); все проходят |
| Документация | 10 | README полный; `DECISIONS.md` (ADR-013…016, ADR-108); §6.4 в `ARCHITECTURE.md` |
| Связанность | 10 | Зависит только от base_manager + dispatch_module + data_schema_module. Нет циклов |
| Работоспособность | 9 | Все наследники мигрированы; 155 тестов зелёные |

## Чеклист рефакторинга

- [x] Этап 0: interfaces.py (IChannel, IBufferStrategy, IChannelRoutingManager)
- [x] Этап 1: ChannelRegistry (generic, thread-safe, RLock)
- [x] Этап 2: normalize_config (Dict at Boundary: None | dict | RegisterBase → dict)
- [x] Этап 3: Буферы (DirectBuffer, AsyncSenderBuffer, BatchBuffer + BatchConfig)
- [x] Этап 4: ChannelRoutingManager (register_channel, route, register_route, register_broadcast)
- [x] Этап 5: ChannelRoutingConfig(RegisterBase) — базовый конфиг, observable_config, dispatcher_strategy
- [x] Этап 6: Тесты (test_channel_registry, test_buffers, test_channel_routing_manager) — 58 тестов
- [x] Этап 7: Миграция LoggerManager (Фаза 2) + ErrorManager (Фаза 3)
- [x] Этап 8: Миграция RouterManager (Фаза 4) + документация (Фаза 5)
- [x] Этап 9 (2026-04-09): `DECISIONS.md`, заполнение `ARCHITECTURE.md` §6.4, удалён shim `buffers/base_buffer.py`

## Иерархия наследников

```
ChannelRoutingManager
    ├── LoggerManager  (BatchBuffer, scope/level routing, ILogChannel(IChannel))
    │       └── ErrorManager  (_level_to_channel, severity routing)
    └── RouterManager  (AsyncSender + channel_dispatcher, IMessageChannel(IChannel))
```

## Известные ограничения

- **configs/ vs core:** `ChannelRoutingManagerConfig` (реестр/UI) и `ChannelRoutingConfig` в `core/` (база для наследников CRM) — оба нужны; см. **ADR-108**
- `AsyncSenderBuffer.flush()` — не гарантирует синхронное ожидание; используй `stop()` + `start()`.
- `BatchBuffer.max_pending` ограничивает **накопленную пачку**, но не то, что уже отдано в `flush_fn`. Верхняя граница памяти на канал — `max_pending + max_size` (одна пачка в полёте: параллельные сбросы одного канала запрещены через `_in_flight`).
- `urgent_flush_requests` считает запросы, а не записанные пачки (сброс идёт вне lock-а). При гонке может превысить `total_batches` — это не ошибка учёта, а семантика имени.

- `BatchBuffer` timer thread запускается в `start()` — вызывай `initialize()` перед использованием.
- `RouterManager` не использует `IBufferStrategy` из CRM — см. ADR-015.

## История изменений

| Дата | Изменение | Фаза |
|------|-----------|------|
| 2026-03-12 | Фаза 1: создан channel_routing_module (interfaces, CRM, buffers, тесты, README) | 1 |
| 2026-03-12 | Фаза 2: ChannelRoutingConfig, observable_config, dispatcher_strategy в CRM | 2 |
| 2026-03-12 | Фаза 2: ILogChannel(IChannel), LogChannel(ILogChannel), LoggerManager мигрирован | 2 |
| 2026-03-12 | Фаза 3: ErrorManagerConfig(ChannelRoutingConfig), _level_to_channel, log() override | 3 |
| 2026-03-12 | Фаза 4: IMessageChannel(IChannel), RouterManager мигрирован | 4 |
| 2026-03-12 | Фаза 5: README полный, DECISIONS.md ADR-013..016, STATUS.md всех модулей | 5 |
| 2026-03-31 | ADR-108: убран дублирующий `build()` у `ChannelRoutingConfig`; зафиксированы две роли схем | — |
| 2026-04-09 | Фаза 0.5 документации: локальный `DECISIONS.md`, §6.4, строка в главном `DECISIONS.md`; удалён `base_buffer.py` | 9 |
| 2026-07-09 | Ф5.15: `observability/` — ObservabilityHub + BoundedChannel + Protocol-контракты (drop-in ObservableMixin, pull-drain, drop_oldest + счётчик потерь, две плоскости фасада); 26 contract-тестов; ADR-CRM-007 | Ф5.15 |
| 2026-07-26 | **Ф0.3:** потолок `BatchBuffer` (`max_pending` + `overflow_policy`), учёт потерь `dropped`/`flush_failed` по каналам, `_in_flight` (один сбрасывающий поток на канал), контракт `flush_fn → int` («записано», а не «отдано»), `urgent_flushes` → `urgent_flush_requests`. Счётчики выходят наружу командой `introspect.observability`. **Редакция 2 по ревью Opus:** первая редакция применяла потолок безусловно — на дефолтах он не срабатывал никогда, а при `max_pending < max_size` ронял записи на здоровом стоке; реальный безлимитный рост был в пачках «в полёте» | Ф0.3 |
| 2026-07-26 | **Ф0.3, редакция 3 (вторая итерация ревью):** механизм `_in_flight` сам принёс два дефекта того же класса. (1) Флаг снимался вне `finally`, а `except Exception` не ловит `KeyboardInterrupt` — один Ctrl+C внутри `ch.write` запирал канал НАВСЕГДА, причём книги при этом сходились (фантомные записи вечно в `in_flight_records`). (2) `flush()` перестал быть барьером: `stop()` возвращался мгновенно, оставляя хвост в `pending` без счётчика, а сброс порядка «контекст раньше ошибки» (Ф0.9) молча становился no-op на занятом канале. Исправлено: учёт в `finally`, `Exception` глушится / `BaseException` пробрасывается, барьер через `Condition` с таймаутом (`flush_timeouts`), `stop()` в два прохода + `dropped_at_stop`. Плюс: враньё стока о числе принятых не кламповится (`flush_contract_violations`) | Ф0.3 |
| 2026-07-26 | **Ф0.6 (подъём в базу):** `set_sink_enabled` (generic disable + хук `_recreate_channel` на enable), `add_tap`/`remove_tap`/`_emit_to_taps`, `_fallback_log` — из `LoggerCore` в CRM; копии у логгера **удалены**, не оставлены делегатами. Ранги уровней вынесены в `levels.py` (закрывает резидуал R6: `error_manager` больше не импортирует вглубь `logger_module`, база не зависит от потомка). `add_log_tap` → `add_tap` по 14 файлам. Промежуточный класс НЕ введён (условие плана). **Риск закрыт whitelist'ом:** `RouterManager` унаследовал `set_sink_enabled`, но командой не адресуем — иначе message-канал IPC снимался бы одной командой | Ф0.6 |
