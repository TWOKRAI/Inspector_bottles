# STATUS — overlay_draw

**Состояние:** реализован, покрыт тестами (9 зелёных). Ветка `feat/line-filter-virtual`.

## Готово
- geometry (клиппинг vline/полосы к кадру).
- registers (color_table type+group + дефолты стиля, dash/gap, show_labels).
- plugin: vlines → центральная линия + пунктирные границы; explicit lines/dashed_lines;
  points + подписи; резолв цвета per-shape→group→type→дефолт; рисование на копии кадра.

## Зависит от
- `JoinInspectorManager` (готов) — слияние frame+overlay в один item.
- `line_filter` (готов) — поставщик overlay (vlines+points).

## TODO
- Сквозной qt-mcp smoke (рендер линии/зоны/точек на живом кадре).
