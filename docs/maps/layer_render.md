# Карта зоны: `Services/layer_render`

Первый автор — Task 2.2 (layer-render). Следующие задачи правят карту в своём handoff. Номера строк — на коммит Task 2.2.

## Модули и публичное API

| Модуль | Публичное | Назначение |
|---|---|---|
| `interfaces.py` | `SolidFill`, `ScrollingTile` | типы слоёв фона (frozen dataclass) |
| `background.py` | `background_layers_from_config`, `fold_background`, `render_background` | стек слоёв -> кадр фона |
| `compose.py` | `rotate_expand`, `crop_to_alpha`, `fit_longest_side`, `cast_contact_shadow`, `composite` | геометрия и композиция спрайта (Task 2.1) |
| `io.py` | `imread_unicode`, `imwrite_unicode` | Windows-safe I/O (Task 2.1) |
| `effects.py` | `EFFECTS`, `EFFECT_PARAMS`, `EffectSpec`, `apply_effects`; функции `apply_glare`, `apply_shadow`, `apply_occlusion`, `apply_motion_blur`, `make_motion_kernel`, `apply_vignette`, `apply_brightness_contrast`, `apply_gamma`, `apply_color_temperature`, `apply_channel_shift`, `apply_jpeg` | фотометрические эффекты кадра (Task 2.2) |

Старые пути — реэкспорт, тот же объект (`is`): `dataset_gen.core.compose.*`, `dataset_gen.core.catalog.imread_unicode/imwrite_unicode`, `dataset_gen.core.augment.<11 функций>` (потребитель — `line_sim/core/factory.py`: `apply_occlusion`).
Мост конфига остался в `dataset_gen`: `augment_config_to_effects(cfg)` и `apply_photometric` в `dataset_gen/core/augment.py:62,71`.

## Инварианты и где они держатся

| Инвариант | Где (файл:строка) | Чем доказан |
|---|---|---|
| Порядок вставки `EFFECTS` = канонический порядок прохода; отдельной константы порядка нет | `effects.py:261` | `test_a3_effects_insertion_order_is_canonical` |
| Запись реестра = блок прежнего `apply_photometric` без вентиля, значения тянет из `rng` в прежнем порядке (shadow: угол, сдвиг, сила, мягкость; occlusion: 6 вызовов на прямоугольник; noise: `standard_normal(shape, float32)`) | `effects.py:186-258` | оракул-копия в `dataset_gen/tests/test_augment_equivalence.py`, sha-литералы |
| Вентиль `rng.random() < prob` тянется ВСЕГДА, и при prob 0.0 и 1.0 | `effects.py:335` | `test_prob_zero_*`, `test_prob_one_*`, A1 |
| Пустой список: копия кадра, ни одного розыгрыша | `effects.py:331-332` | `test_a2_*`, A1 all_disabled |
| U8-эффект (`_U8_EFFECTS`, сейчас `jpeg`) получает clip -> uint8, результат возвращается во float32; в конце clip -> uint8 | `effects.py:293,337-338,341` | `test_a1c_*`, `test_jpeg_receives_clipped_uint8_not_wrapped` |
| `EffectSpec` валидирует имя / ключи / prob (`ValueError`) | `effects.py:310,314,318` | `test_a5_*` |
| `params` = `MappingProxyType` поверх глубокой копии `{**EFFECT_PARAMS[name], **params}` (нет алиасинга) | `effects.py:320-321` | `test_effect_spec_*`, `test_nested_list_*`, `test_spec_params_do_not_alias_*` |
| `EffectSpec` — `frozen`, `eq=False` (сравнение по идентичности) | `effects.py:296` | `test_effect_spec_is_frozen`, `test_effect_spec_equality_is_by_identity` |
| `EFFECT_PARAMS` — литералы, равны полям `AugmentConfig` (кроме `enabled`/`prob`) | `effects.py:277`; сверка — `dataset_gen/tests` | `test_a4_*` |
| Rng-контракт: слой не создаёт генератор, берёт `rng` у вызывающего; вход `frame_u8` не меняется | `effects.py:324-341` | `test_each_effect_*`, `test_input_frame_untouched_*` |
| Слой не импортирует `dataset_gen`, `line_sim`, `ml_train` | весь пакет (AST-скан) | `test_a8_*` |
| Реэкспорт без копий: `augment.apply_X is effects.apply_X`; `_uniform` в `augment` не реэкспортируется | `dataset_gen/core/augment.py:28-60` | `test_a6_*` |

## Правило реэкспорта

Перенос из `dataset_gen` = тело дословно + явный `import` и `__all__` в старом модуле (не `import *`). Приватные имена
(`_uniform`) не реэкспортируются. Новый потребитель импортирует из `Services.layer_render`, не из старого пути.

## Как добавить эффект

Функция в `effects.py` + запись в `EFFECTS` (место в словаре = место в проходе) + запись в `EFFECT_PARAMS`
(литералы) + такое же поле `*Aug` в `dataset_gen/core/config.py` (иначе `test_a4_*` красный).

## Где тесты

- `Services/layer_render/tests/` — `test_acceptance_*` (слепые, тестер), `test_hazards_*` (автор механизма).
- `Services/dataset_gen/tests/test_augment_equivalence.py` — оракул `apply_photometric`, sha-литералы, `EFFECT_PARAMS == AugmentConfig`.
- `Services/line_sim/tests/`, `Plugins/sim/*/tests/` — потребители фона и сцены (слой не импортирует `line_sim`, поэтому тесты там).

## Открыто

Эффекты на слое/сцене (`apply_effects_rgba`) — вне Task 2.2; границы зоны 4.7d (data_receiver, pipeline_executor, …) не трогать.
