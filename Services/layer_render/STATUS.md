# layer_render — STATUS

Task 1.1 (plans/layer-render): вертикальный срез «конфиг -> кадр симулятора» готов.
Task 1.3: единственный способ задать фон сцены — `background_layers` (прежние одиночный тайл компоновщика и ключ
фон-текстуры плагина удалены, LR-002); стенд `apps/line_sim` на `[solid чёрный, tile belt_tile.png]`.
Решения пакета — [DECISIONS.md](DECISIONS.md).

## Что есть

- `interfaces.py` — `SolidFill`, `ScrollingTile` (frozen dataclass; тайл валидируется в конструкторе).
- `background.py` — `background_layers_from_config`, `fold_background`, `render_background`.
- `compose.py`, `io.py` — Task 2.1: геометрия/композиция спрайта и Windows-safe `imread_unicode`/`imwrite_unicode` перенесены из `dataset_gen` дословно; старые пути — реэкспорт (тот же объект).
- Подключено: `SceneCompositor(background_layers=...)`, ключ `background_layers` в `scene_source`.

## Тесты

- `tests/test_acceptance_1_1_background_layers.py` — слепые (схема, слой импортов, рамка плана).
- `tests/test_acceptance_2_1_compose_io.py` — слепые (идентичность `is`, `__module__`, отсутствие def в старом compose, слой импортов, хеш-пины поведения).
- `tests/test_hazards_1_1_background.py` — автор: свёртка == общий путь == попиксельный оракул на случайных
  RGBA-стеках, альфа 0/255 точно, знак `scroll_px`, тайл выше кадра, неизменность входов, пустой стек.
- Слепые тесты компоновщика и плагина лежат в `Services/line_sim/tests/` и `Plugins/sim/scene_source/tests/`
  (правило слоёв: тесты `layer_render` не импортируют `line_sim`).

## Не сделано

Эффекты на слоях фона, фон в пресете сцены (Ф3), пересборка `data/line_sim/belt_tile.png` с `--gap-alpha` (шаг лида).
