# statistics_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md) (ADR-022)

## ADR-SM-001: StatsManager как прямой наследник ChannelRoutingManager (не LoggerManager)

- **Дата:** 2026-03-15
- **Статус:** принято
- **Контекст:** Нужен менеджер метрик. Рассматривалось наследование от LoggerManager (как ErrorManager). LoggerManager добавляет scope/level — не нужны для метрик.
- **Решение:** `StatsManager(ChannelRoutingManager, IStatsManager)` — прямой наследник CRM. Получает каналы, буферизацию, dispatcher без overhead LoggerManager.
- **Глобальная ссылка:** ADR-022 в `../../DECISIONS.md`.
- **Отклонено:** `StatsManager(LoggerManager)` — scope/level избыточны.

## ADR-SM-002: Dual-layer storage (_metrics + AggregationWindow)

- **Дата:** 2026-03-31
- **Статус:** принято
- **Контекст:** Метрики нужны в двух режимах: (1) императивный запрос `get_metric()`, (2) периодический flush снапшотов в каналы.
- **Решение:** `self._metrics` (Dict[str, MetricRecord]) для live-запросов + `AggregationWindow` (IBufferStrategy) для flush. Каждый record_metric() пишет в оба.
- **Компромисс:** Двойная запись, стоимость O(1), данные консистентны.

## ADR-SM-003: Sentinel-паттерн (_STATS_SENTINEL) для N-channel broadcast

- **Дата:** 2026-03-31
- **Статус:** принято
- **Контекст:** Если enqueue для каждого из N каналов — метрики считаются N раз.
- **Решение:** `_enqueue_to_buffer()` использует sentinel `"__stats__"`. `_do_flush()` транслирует снапшот во ВСЕ каналы через `_channel_registry.all()`.

## ADR-SM-004: _metric_key дупликация — намеренная изоляция слоёв

- **Дата:** 2026-03-31
- **Статус:** принято
- **Контекст:** `_metric_key(name, tags)` определена в `stats_manager.py:31` и `aggregation_window.py:18`.
- **Решение:** Намеренная изоляция. Вынос в общий модуль создаёт нежелательную связность.
- **Компромисс:** При изменении формата ключа — менять в двух местах.

## ADR-SM-005: StatsAdapter для CommandManager-интеграции

- **Дата:** 2026-04-01
- **Статус:** принято
- **Решение:** `StatsAdapter(BaseAdapter)` регистрирует 5 команд: get_metrics, get_metric, reset_metrics, stats_snapshot, flush_stats. Паттерн совпадает с другими адаптерами.

## ADR-SM-006: AggregationWindow как IBufferStrategy (не BatchBuffer)

- **Дата:** 2026-03-31
- **Статус:** принято
- **Контекст:** CRM предоставляет BatchBuffer (collect + flush). Для метрик нужна агрегация: counter sum, gauge last, timing p95.
- **Решение:** `AggregationWindow(IBufferStrategy)` — агрегация MetricRecord вместо простого батчинга. Flush отправляет агрегированный снапшот.
- **Отклонено:** BatchBuffer — не поддерживает агрегацию.
