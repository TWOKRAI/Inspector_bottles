# line_filter — фильтр виртуальной линии

Категория: **filter** («Фильтр»). Классический фильтр технического зрения — virtual
tripwire / line-crossing. На вход — координаты объектов, на выходе — отмеченные
объекты (вход в зону / пересечение линии) + draw-params для рендера.

## Контракт

| Порт | Тип | Описание |
|------|-----|----------|
| **вход** `detections` | list[dict] | детекции с `center: [x, y]` (или `points: [[x,y]]`) |
| **выход** `overlay` | dict | семантика линии (`vlines`) + отмеченные точки — для `overlay_draw` |
| **выход** `filtered` | list[dict] | сработавшие объекты (`current` или `accumulated`) |

Выход помечается `data_type="overlay"` и наследует `seq_id` входа — для корреляции
кадр↔overlay в `JoinInspectorManager`. **Кадр через себя не пропускает.**

## Методы (защита от шума)

1. Знаковое расстояние точка→линия (`geometry.signed_distance`); линия «от края до
   края» разворачивается в `overlay_draw` (клиппинг по кадру).
2. Центроидный трекинг (`tracker.CentroidTracker`, SORT-lite) — стабильная идентичность.
3. Temporal confirmation (`min_hits`) + TTL (`max_age`) — отсев одиночных вспышек.
4. `enter_zone` + гистерезис (`hysteresis_margin`) — анти-дребезг границы зоны.
5. `cross_line` — пересечение (смена знака), направление наезд/выезд.
6. Дедуп по радиусу (`dedup_radius`) — «±N px = тот же объект».

## Параметры

См. `registers.py`: `center_x/y`, `angle`, `zone_width`, `mode`, `dedup_radius`,
`min_hits`, `max_age`, `max_match_distance`, `hysteresis_margin` (≥ `dedup_radius`),
`emit_mode`. Все редактируются в карточке ноды (live).

## Тесты

`pytest Plugins/filter/line_filter/tests/` — geometry / tracker / plugin (28 тестов).
