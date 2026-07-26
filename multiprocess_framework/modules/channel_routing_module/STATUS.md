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
- `BatchBuffer.max_pending` ограничивает **накопленную пачку**, но не то, что уже отдано в `flush_fn`: медленный сток удерживает свою пачку в памяти сверх потолка. Верхняя граница — `max_pending + размер пачки в полёте` на канал.
- `urgent_flush_requests` считает запросы, а не записанные пачки (сброс идёт вне lock-а). При гонке может превысить `total_batches` — это не ошибка учёта, а семантика имени.

## История изменений

- **2026-07-26 (Ф0.3 `observability-unified-routing`):** у `BatchBuffer` появился потолок `max_pending` на канал + политика переполнения (`drop_oldest` / `drop_newest`) и учёт потерь `dropped` / `dropped_by_channel`. До этого потолка не было вовсе — медленный сток копил записи в памяти без предела и без следа. Счётчик `urgent_flushes` переименован в `urgent_flush_requests` (семантика: запросы, а не записанные пачки). Инвариант учёта `total_enqueued == total_flushed + Σ pending + dropped` зафиксирован тестом. Наружу счётчики выходят командой `introspect.observability`; на живом стенде `dualcam_synth` при `max_pending=3` получено `dropped=581` с разбивкой по каналам.
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
