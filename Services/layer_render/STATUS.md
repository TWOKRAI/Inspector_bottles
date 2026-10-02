# layer_render — STATUS

Task 1.1 (plans/layer-render): вертикальный срез «конфиг -> кадр симулятора» готов.
Task 1.3: единственный способ задать фон сцены — `background_layers` (прежние одиночный тайл компоновщика и ключ
фон-текстуры плагина удалены, LR-002); стенд `apps/line_sim` на `[solid чёрный, tile belt_tile.png]`.
Task 2.2: фотометрические эффекты перенесены в `effects.py` как упорядоченный реестр; `apply_photometric` — одна строка над `apply_effects`.
Task 6.1: одна функция квадратного выреза `crop.py` (`side_from_radius`, `square_crop`, `resize_square`); `center_crop` и `holdout_eval._crop_disk` делегируют, выход побайтно прежний (кроме: всегда копия; `replicate` без пересечения — `ValueError`). Карта — [docs/maps/crop.md](../../docs/maps/crop.md).
Task 2.3: стек слоёв объекта — `layers.py` (`LayerSpec`/`LayerAugment`/`compose_layers` и ещё 8 имён); `line_sim.LayeredObject` — обёртка вокруг `compose_layers`, выход сима побайтно прежний.
Решения пакета — [DECISIONS.md](DECISIONS.md). Карта зоны — [docs/maps/layer_render.md](../../docs/maps/layer_render.md).

## Что есть

- `interfaces.py` — `SolidFill`, `ScrollingTile` (frozen dataclass; тайл валидируется в конструкторе).
- `background.py` — `background_layers_from_config`, `fold_background`, `render_background`.
- `compose.py`, `io.py` — Task 2.1: геометрия/композиция спрайта и Windows-safe `imread_unicode`/`imwrite_unicode` перенесены из `dataset_gen` дословно; старые пути — реэкспорт (тот же объект).
- `effects.py` — Task 2.2: 11 функций эффектов (дословно из `dataset_gen.core.augment`), `EFFECTS` (12 записей, порядок = порядок прохода), `EFFECT_PARAMS`, `EffectSpec`, `apply_effects`; `dataset_gen.core.augment` реэкспортирует функции (тот же объект).
- `crop.py` — Task 6.1: вырез квадрата с четырьмя режимами у границы (`drop`/`pad`/`clamp`/`replicate`), ресайз ко входу модели.
- `layers.py` — Task 2.3: типы слоя (из `line_sim.interfaces` дословно), `load_layer_sprite`, `transform_layer`, `canvas_size`, `compose_layers` -> `ComposedLayers`; `line_sim.interfaces` и `layered_object` реэкспортируют (тот же объект).
- Подключено: `SceneCompositor(background_layers=...)`, ключ `background_layers` в `scene_source`.

## Тесты

- `tests/test_acceptance_1_1_background_layers.py` — слепые (схема, слой импортов, рамка плана).
- `tests/test_acceptance_2_1_compose_io.py` — слепые (идентичность `is`, `__module__`, отсутствие def в старом compose, слой импортов, хеш-пины поведения).
- `tests/test_hazards_1_1_background.py` — автор: свёртка == общий путь == попиксельный оракул на случайных
  RGBA-стеках, альфа 0/255 точно, знак `scroll_px`, тайл выше кадра, неизменность входов, пустой стек.
- `tests/test_acceptance_2_2_effects.py` — слепые (порядок, пустой список, вентиль prob, U8-круг, `EffectSpec`, реэкспорт, слой импортов); `tests/test_hazards_2_2_effects.py` — автор: алиасинг параметров, read-only вход, JPEG на значениях вне 0..255, повтор spec; оракул `apply_photometric` и `EFFECT_PARAMS == AugmentConfig` — в `Services/dataset_gen/tests/test_augment_equivalence.py`.
- `tests/test_acceptance_2_3_layers.py` — слепые (sha-литералы до задачи на 6 стеках × 3 seed, тексты ошибок, реэкспорт, AST); `tests/test_hazards_2_3_layers.py` — автор: read-only обёртки не замораживает вход, генератор `forced_defects`, порядок проверок и rng, пустая метка, рантайм-импорт без `line_sim`/`dataset_gen`, алиас `_transform`.
- Слепые тесты компоновщика и плагина лежат в `Services/line_sim/tests/` и `Plugins/sim/scene_source/tests/`
  (правило слоёв: код пакета, кроме `tests/`, не импортирует `line_sim`; тесты эквивалентности обёртки — `test_acceptance_2_2_effects.py` (a6), `test_acceptance_2_3_layers.py`, `test_hazards_2_3_layers.py` — исключения с локальным импортом; перенос их в `line_sim/tests` — вопрос владельца, OPEN).

## Не сделано

Эффекты на слоях/сцене (`apply_effects_rgba`), переключение потребителей на новые импорты, эффекты на слоях фона, фон в пресете сцены (Ф3), пересборка `data/line_sim/belt_tile.png` с `--gap-alpha` (шаг лида).
