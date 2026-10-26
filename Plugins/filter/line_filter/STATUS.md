# STATUS — line_filter

**Состояние:** реализован, покрыт тестами (28 зелёных). Ветка `feat/line-filter-virtual`.

## Готово
- geometry (signed_distance, клиппинг линии/полосы к кадру) + тесты.
- tracker (CentroidTracker, SORT-lite) + тесты.
- registers (FieldMeta + Literal mode + валидатор `hysteresis_margin ≥ dedup_radius`).
- plugin: режимы `enter_zone`/`cross_line`, min_hits, дедуп, overlay (vlines+points),
  выход `data_type=overlay` + наследование `seq_id`.
- категория «Фильтр» в палитре (palette_widget + constants).
- `zone_edge` — одно событие на проход диска (C-42): память места пропажи (`max_match_distance`,
  `max_age`) — повторное появление в радиусе и окне = тот же диск, события нет; защёлка при
  старте закрыта (О1: занятая зона при рестарте не засчитывается). Условия настройки —
  в README и `FieldMeta.info`: `max_match_distance` ≥ v×(L+1); `rearm_frames` ≤ L ≤ `max_age`;
  `max_age`×v < `zone_width` − `max_match_distance`. Валидатора нет.

## Зависит от
- `overlay_draw` (Этап 3) — разворачивает `overlay.vlines` в отрезки и рисует.
- `JoinInspectorManager` (Этап 1, готов) — корреляция кадр↔overlay по `(seq_id, data_type)`.
- Источник кадра должен помечать `data_type="frame"` (интеграция).

## TODO
- Сквозной qt-mcp smoke (рецепт камера→детектор→line_filter→Join→overlay_draw→display).
- Опц.: cKDTree для дедупа при больших N.
