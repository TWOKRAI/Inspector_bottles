# statistics_module — Статус рефакторинга

## Текущий этап: 4 / 8

## Оценки (0–10)

| Критерий        | Оценка | Комментарий                                                                   |
|-----------------|--------|-------------------------------------------------------------------------------|
| Код             | 9      | ChannelRoutingManager + AggregationWindow; sentinel-паттерн для broadcast     |
| Тесты           | 8      | 24 теста: lifecycle, типы метрик, теги, N-кратный счёт, flush, каналы         |
| Документация    | 8      | README с архитектурой, API, примерами; STATUS.md создан                       |
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
- [ ] Этап 5: Интеграция — добавить StatsManager в process_managers.py
- [ ] Этап 6: Graceful shutdown — тест flush перед остановкой в реальном процессе
- [ ] Этап 7: Стресс-тест — concurrent writes, высокая нагрузка, tag cardinality
- [ ] Этап 8: Полная интеграция с process_manager_module

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
