# Карта зоны: квадратный вырез (`crop`)

Одна реализация выреза: `Services/layer_render/crop.py` (Task 6.1, `plans/layer-render/phase-6-train.md`).
Контракт — таблица Public API в `Services/layer_render/README.md`; здесь — кто пользуется и где держится каждый инвариант.

## API (`Services.layer_render`, реэкспорт из `__init__.py`)

- `side_from_radius(radius, radius_scale, margin_px)` — `crop.py:20-22`; `max(2, int(round(2·r·scale)) + 2·int(margin))`.
- `square_crop(frame, cx, cy, side, oob, pad_value=(0,0,0))` — `crop.py:25-79`; левый верхний угол `(cx - side//2, cy - side//2)`, размер ровно `side`.
- `resize_square(crop, out)` — `crop.py:82-91`; `out <= 0` / уже `out`×`out` -> тот же объект; AREA при `crop.shape[0] > out`, иначе LINEAR.

## Четыре режима `oob` (квадрат выходит за кадр)

| oob | выход | нет пересечения с кадром |
|-----|-------|--------------------------|
| `drop` | `None` (`crop.py:55`) | `None` |
| `pad` | холст `side`×`side` под `pad_value` (`crop.py:63-68`; 2D — `pad_value[0]`, 4 канала — хвост нулями, `crop.py:94-103`) | чистый холст |
| `clamp` | обрезка по кадру, меньше `side` (`crop.py:70-73`) | `None` |
| `replicate` | репликация края, `copyMakeBorder` (`crop.py:75-79`) | `ValueError` (`crop.py:76-77`) |

Неизвестный `oob` — `ValueError`, проверка первой (`crop.py:45-46`), в том числе для квадрата внутри кадра.
«Нет пересечения» решается по обрезанным границам: `sx1 > sx0 and sy1 > sy0` (`crop.py:58-61`); касание (x1 == 0) — не пересечение.

## Инвариант «всегда копия»

Выход никогда не view кадра: кадры из SHM (транспорт 4.7b) — read-only view на живой буфер.
Держится в трёх местах: внутри кадра `crop.py:52-53` (`.copy()`), `clamp` `crop.py:73`, `pad`/`replicate` строят новый
массив (`crop.py:94-103`, `copyMakeBorder` `crop.py:79`). Для `holdout_eval._crop_disk` это намеренное изменение: раньше
полностью внутри кадра отдавался view (байты те же).

## Потребители

1. `Plugins/processing/center_crop/plugin.py` — `_oob_mode` (`plugin.py:139-146`) мапит регистр в `oob`:
   `drop_partial` -> `drop` (побеждает), иначе `pad_if_oob` -> `pad` (цвет `pad_color_bgr`, `plugin.py:137`), иначе `clamp`.
   `_resolve_side` (fallback `size_mode`/радиус неизвестен -> `side_px`) остаётся в плагине, формула — `side_from_radius` (`plugin.py:117`).
   `_resize_output` (`plugin.py:106`) -> `resize_square(crop, output_size)`.
2. `Services/ml_train/holdout_eval.py::_crop_disk` (`holdout_eval.py:44-54`) — `detect_disk`, `half = round(r·(1+margin))`,
   `square_crop(bgr, cx, cy, 2*half, oob="replicate")`. Формула стороны НЕ менялась (её смена — Task 6.4).
   Вызов в `evaluate_holdout` без try/except: `ValueError` достижим, только если `detect_disk` вернул центр целиком вне кадра
   (раньше молча возвращался массив неверной формы). Обработки нет намеренно.

## Границы слоёв

`layer_render` не импортирует `dataset_gen` / `line_sim` / `ml_train` (AST-тест A7). Потребители идут вниз по слоям.

## Где тесты

- `Services/layer_render/tests/test_acceptance_6_1_crop.py` — слепой набор tester (литералы sha256 снятые до задачи).
- `Services/layer_render/tests/test_hazards_6_1_crop.py` — hazard-тесты автора (квадрат больше кадра, нечётная сторона,
  read-only кадр, 2D/4-канал, маппинг регистра, `_crop_disk` с центром вне кадра).
- `Plugins/processing/center_crop/tests/test_plugin.py` — поведение плагина целиком.
