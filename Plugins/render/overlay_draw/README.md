# overlay_draw — рисовальщик overlay

Категория: **rendering**. Универсальный плагин: рисует структурные draw-params
(`overlay`) на кадре через cv2 и выдаёт готовый `frame` для дисплея.

## Контракт

| Порт | Тип | Описание |
|------|-----|----------|
| **вход** `frame` | image/bgr | исходный кадр |
| **вход** `overlay` | dict | draw-params (`vlines`/`lines`/`dashed_lines`/`points`) |
| **выход** `frame` | image/bgr | кадр с нарисованным overlay (перезапись, конвенция framework) |

Многовходовый узел: `frame` и `overlay` приходят слитыми в один item — их коррелирует
`JoinInspectorManager` по `(seq_id, data_type)`. Stateless, `thread_safe=True`. Кадр не
мутируется (рисуем на `frame.copy()`).

## overlay-форматы

- `vlines: [{cx, cy, angle, zone_width, group, type}]` — семантика виртуальной линии;
  разворачивается в центральную линию «от края до края» + 2 пунктирные границы полосы
  (клиппинг по кадру в `geometry.vline_segments`).
- `lines: [{p1, p2, ...}]` / `dashed_lines: [{p1, p2, ...}]` — явные отрезки.
- `points: [{xy, label, ...}]` — точки + подписи.

## Таблица цветов

`color_table` (list[dict], редактор в карточке): резолв стиля фигуры
`per-shape color → строка по group → строка по type → дефолт`. Дефолты — отдельные поля.

## Тесты

`pytest Plugins/render/overlay_draw/tests/` — рендер/резолв цвета (9 тестов).
