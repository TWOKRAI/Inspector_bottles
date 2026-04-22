# statistics_module — Статус рефакторинга

## Текущий этап: 5 / 8

## Оценки (0–10)

| Критерий        | Оценка | Комментарий                                                                   |
|-----------------|--------|-------------------------------------------------------------------------------|
| Код             | 9      | ChannelRoutingManager + AggregationWindow; sentinel-паттерн для broadcast     |
| Тесты           | 9      | ~37 тестов; integration, adapter, thread-safety, tags                         |
| Документация    | 10     | DECISIONS.md (ADR-SM-001…006), §6.15 в ARCHITECTURE.md, README fix              |
| Связанность     | 9      | Наследует CRM; IStatsManager(IChannelRoutingManager); StatsPlugin-совместим   |
| Дублирование    | 9      | _metric_key дублируется в core/ — приемлемо (изолированные слои)             |
| Работоспособность | 9    | Все 24 теста проходят; broadcast, теги, flush работают корректно              |

## Чеклист рефакторинга

- [x] Этап 0: Критические баги исправлены
  - [x] Баг N-кратного счёта (enqueue per channel → sentinel _STATS_SENTINEL)
  - [x] Баг _managers (getattr → get_manager("logger"))
  - [x] Несогласованный merge тегов
  - [x] Дублирование buffer.start() / is_initialized в initialize()
- [x] Этап 1: Архитектура — IStatsManager(IChannelRoutingManager), StatsManagerConfig
- [x] Этап 2: Ядро — StatsManager(ChannelRoutingManager), AggregationWindow, MetricRecord
- [x] Этап 3: Каналы — LogStatsChannel, FileStatsChannel
- [x] Этап 4: Адаптер — StatsAdapter (get_metrics, reset_metrics, stats_snapshot, flush_stats)
- [x] Этап 5: Формализация — DECISIONS.md (ADR-SM-001…006), ARCHITECTURE.md §6.15, тесты integration/adapter/thread-safety
- [ ] Этап 6: Интеграция — добавить StatsManager в process_managers.py
- [ ] Этап 7: Graceful shutdown — тест flush перед остановкой в реальном процессе
- [ ] Этап 8: Стресс-тест — concurrent writes, высокая нагрузка, tag cardinality; полная интеграция с process_manager_module

## Обновление 2026-04-01

- Пути файлов метрик по умолчанию резолвятся через **`logger_module.core.log_paths.resolve_log_file_path`** (не в дереве `modules/` при pytest; ADR-111).

## Обновление 2026-04-03

- **`StatsManagerConfig`**: **`ChannelRoutingConfig`** импортируется из публичного **`channel_routing_module`** (глобальный ADR-108 / ADR-CRM-005, единый стиль с логгером).

## Известные проблемы

- `_metric_key` дублируется в `stats_manager.py` и `aggregation_window.py` —
  оба работают корректно, но при изменении логики нужно менять в двух местах.
- `FileStatsChannel` пишет в режиме append без ротации файлов.
  Для production нужно добавить RotatingFileHandler или ограничение размера.
- При `shutdown()` двойной flush: `flush()` + `buffer.stop()` (который тоже flush).
  Второй flush отправляет пустой снапшот — безвредно, но неэлегантно.
- Нет MetricsRetention — старые метрики не вычищаются автоматически
  (поле `retention_seconds` в конфиге существует, но логика не реализована).
- RouterManager-интеграция (отправка снапшотов в другой процесс) не реализована.

## История изменений

| Дата | Что сделано |
|------|-------------|
| 2026-03-31 | ADR-108: убран избыточный `build()` у `StatsManagerConfig` (наследует `SchemaMixin.build`) |
| 2026-04-03 | Импорт `ChannelRoutingConfig` из публичного `channel_routing_module` (ADR-114) |
| 2026-04-10 | DECISIONS.md (ADR-SM-001…006), ARCHITECTURE.md §6.15, тесты integration/adapter/thread-safety, README fix; этап 4→5 |
