# layer_render — STATUS

Task 1.1 (plans/layer-render): вертикальный срез «конфиг -> кадр симулятора» готов.

## Что есть

- `interfaces.py` — `SolidFill`, `ScrollingTile` (frozen dataclass; тайл валидируется в конструкторе).
- `background.py` — `background_layers_from_config`, `fold_background`, `render_background`.
- Подключено: `SceneCompositor(background_layers=...)`, ключ `background_layers` в `scene_source`.

## Тесты

- `tests/test_acceptance_1_1_background_layers.py` — слепые (схема, слой импортов, рамка плана).
- `tests/test_hazards_1_1_background.py` — автор: свёртка == общий путь == попиксельный оракул на случайных
  RGBA-стеках, альфа 0/255 точно, знак `scroll_px`, тайл выше кадра, неизменность входов, пустой стек.
- Слепые тесты компоновщика и плагина лежат в `Services/line_sim/tests/` и `Plugins/sim/scene_source/tests/`
  (правило слоёв: тесты `layer_render` не импортируют `line_sim`).

## Не сделано

Эффекты на слоях фона, конфиг стенда, пересборка тайла (Task 1.3), инструмент `--gap-alpha` (Task 1.2).
