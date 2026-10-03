# Карта зоны: `Services/layer_render`

Первый автор — Task 2.2 (layer-render). Следующие задачи правят карту в своём handoff. Номера строк — на коммит Task 2.2.

## Модули и публичное API

| Модуль | Публичное | Назначение |
|---|---|---|
| `interfaces.py` | `SolidFill`, `ScrollingTile` | типы слоёв фона (frozen dataclass) |
| `background.py` | `background_layers_from_config`, `fold_background`, `render_background` | стек слоёв -> кадр фона |
| `compose.py` | `rotate_expand`, `crop_to_alpha`, `fit_longest_side`, `cast_contact_shadow`, `composite` | геометрия и композиция спрайта (Task 2.1) |
| `io.py` | `imread_unicode`, `imwrite_unicode` | Windows-safe I/O (Task 2.1) |
| `layers.py` | `LayerMode`, `RangeF`, `SpriteSource`, `AUGMENT_FIELDS`, `LayerAugment`, `LayerSpec`, `ComposedLayers`, `load_layer_sprite`, `transform_layer`, `canvas_size`, `compose_layers` | стек слоёв объекта: розыгрыш и композиция в RGBA (Task 2.3); не знает паспорта и `line_sim` |
| `preset.py` | `ScenePreset`, `CLASS_SPRITE_SOURCE` | пресет сцены (Task 2.4a); `LayerSpec` из `layers.py`; блока стенда (`REPO_ROOT` и др.) здесь нет |
| `catalog.py` | `SpriteCatalog`, `ClassEntry`, `CatalogConfig`, `SPRITE_SUFFIXES`, `BACKGROUND_SUFFIXES` | каталог классов и фонов (Task 2.4a); приватный `_cover_crop` |
| `metadata.py` | `ClassMeta`, `load_meta`, `write_meta`, `META_FILENAMES`, `SymmetryType` | разметка узла каталога, наследование сверху вниз (Task 2.4a) |
| `procedural_backgrounds.py` | `procedural_background`, `gradient_bg`, `brushed_metal_bg`, `conveyor_belt_bg`, `speckled_bg`, `_GENERATORS` | процедурные фоны каталога (Task 2.4a); не путать с `background.py` |
| `factory.py` | `ObjectFactory`, `RenderedObject` | фабрика объекта из слоёв (Task 2.4b): `render(rng, *, force_defect, label) -> RenderedObject`, `nominal_layers`; флага оператора и паспорта нет (они в `line_sim.ObjectFactory`) |
| `preview.py` | `render_preview_grid`, `render_layout`, `validate_preview_request`, `confine_preset_paths`, `PreviewLimitError`, `OUTSIDE_ROOTS_MESSAGE`, `PREVIEW_*` | превью пресета (Task 2.4b); кэш фабрики `_factory_cache` — глобал этого модуля |
| `effects.py` | `EFFECTS`, `EFFECT_PARAMS`, `EffectSpec`, `apply_effects`; функции `apply_glare`, `apply_shadow`, `apply_occlusion`, `apply_motion_blur`, `make_motion_kernel`, `apply_vignette`, `apply_brightness_contrast`, `apply_gamma`, `apply_color_temperature`, `apply_channel_shift`, `apply_jpeg` | фотометрические эффекты кадра (Task 2.2) |

Старые пути — реэкспорт, тот же объект (`is`): `dataset_gen.core.compose.*`, `dataset_gen.core.catalog.imread_unicode/imwrite_unicode`, `dataset_gen.core.augment.<11 функций>` (потребитель — `line_sim/core/factory.py`: `apply_occlusion`); `line_sim.interfaces.<6 типов слоя>`, `line_sim.core.layered_object.canvas_size`, `LayeredObject._transform` (= `transform_layer`). Приватные `_rotate`/`_hue_shift`/`_over`/`_compose_canvas` не реэкспортируются; `factory.py` берёт `load_layer_sprite` из `Services.layer_render`.
Task 2.4a, тот же принцип: `line_sim.core.preset.{ScenePreset, CLASS_SPRITE_SOURCE}` (блок стенда `REPO_ROOT`/`resolve_repo_path`/`load_scene_preset` остался там, `import os` держит строку-цель патча теста), `dataset_gen.core.catalog.{SpriteCatalog, ClassEntry, SPRITE_SUFFIXES, BACKGROUND_SUFFIXES, imread_unicode, imwrite_unicode}`, `dataset_gen.core.metadata.{ClassMeta, load_meta, write_meta, META_FILENAMES}`, `dataset_gen.core.backgrounds.{procedural_background, gradient_bg, brushed_metal_bg, conveyor_belt_bg, speckled_bg, _GENERATORS}` — только эти имена; `_cover_crop`, `_low_freq` и транзитные имена старых модулей (`catalog.CatalogConfig`, `catalog.ClassMeta`, `catalog.load_meta`, `catalog.procedural_background`, `metadata.SymmetryType`) не реэкспортируются (потребителей 0, AST-скан ревью 2026-10-02); `dataset_gen.core.config.{CatalogConfig, SymmetryType}` (импорт на уровне модуля: pydantic собирает `GeneratorConfig`).
Task 2.4b: `line_sim.core.{preview,catalog_bridge}` — чистый реэкспорт, `line_sim.interfaces._json_safe` = `layers.json_safe`; `line_sim.ObjectFactory(layer_render.ObjectFactory)` — подкласс: `make` = флаг оператора + `render` + `LayeredObject.from_rendered` (паспорт; `render()` объекта возвращает тот же массив, что `RenderedObject.rgba`).
Мост конфига остался в `dataset_gen`: `augment_config_to_effects(cfg)` и `apply_photometric` в `dataset_gen/core/augment.py:62,71`.

## Инварианты и где они держатся

| Инвариант | Где (файл:строка) | Чем доказан |
|---|---|---|
| Порядок вставки `EFFECTS` = канонический порядок прохода; отдельной константы порядка нет | `effects.py:261` | `test_a3_effects_insertion_order_is_canonical` |
| Запись реестра = блок прежнего `apply_photometric` без вентиля, значения тянет из `rng` в прежнем порядке (shadow: угол, сдвиг, сила, мягкость; occlusion: 6 вызовов на прямоугольник; noise: `standard_normal(shape, float32)`; запись реестра не правит входной массив, noise — `x + ...`, `effects.py:249`) | `effects.py:186-257` | оракул-копия в `dataset_gen/tests/test_augment_equivalence.py`, sha-литералы |
| Вентиль `rng.random() < prob` тянется ВСЕГДА, и при prob 0.0 и 1.0 | `effects.py:339` | `test_prob_zero_*`, `test_prob_one_*`, A1 |
| Пустой список: копия кадра, ни одного розыгрыша | `effects.py:335-336` | `test_a2_*`, A1 all_disabled |
| U8-эффект (`_U8_EFFECTS`, сейчас `jpeg`) получает clip -> uint8, результат возвращается во float32; в конце clip -> uint8 | `effects.py:293,341-342,345` | `test_a1c_*`, `test_jpeg_receives_clipped_uint8_not_wrapped` |
| `apply_effects`: dtype входа не uint8 -> `ValueError` до любого розыгрыша (раньше пустой список возвращал float как есть) | `effects.py:333` | `test_non_uint8_frame_raises_*` |
| `EffectSpec` валидирует имя / ключи / prob (`ValueError`) | `effects.py:311,315,319` | `test_a5_*` |
| `params` = `MappingProxyType` поверх глубокой копии `{**EFFECT_PARAMS[name], **params}` (нет алиасинга) | `effects.py:321-322` | `test_effect_spec_*`, `test_nested_list_*`, `test_spec_params_do_not_alias_*` |
| `EffectSpec` — `frozen`, `eq=False` (сравнение по идентичности) | `effects.py:296` | `test_effect_spec_is_frozen`, `test_effect_spec_equality_is_by_identity` |
| `EFFECT_PARAMS` — литералы, равны полям `AugmentConfig` (кроме `enabled`/`prob`) | `effects.py:277`; сверка — `dataset_gen/tests` | `test_a4_*` |
| Rng-контракт: слой не создаёт генератор, берёт `rng` у вызывающего; вход `frame_u8` не меняется | `effects.py:325-345` | `test_each_effect_*`, `test_input_frame_untouched_*` |
| Слой не импортирует `dataset_gen`, `line_sim`, `ml_train` | весь пакет (AST-скан) | `test_a8_*` |
| Реэкспорт без копий: `augment.apply_X is effects.apply_X`; `_uniform` в `augment` не реэкспортируется | `dataset_gen/core/augment.py:28-60` | `test_a6_*` |

## Правило реэкспорта

Перенос из `dataset_gen` = тело дословно + явный `import` и `__all__` в старом модуле (не `import *`). Приватные имена
(`_uniform`) не реэкспортируются. `EFFECTS`/`EFFECT_PARAMS` — точка расширения на этапе импорта, в рантайме не менять. Мост `augment_config_to_effects` требует, чтобы каждый ключ `EFFECTS` был полем `AugmentConfig` (4-й шаг «Как добавить эффект»). Новый потребитель импортирует из `Services.layer_render`, не из старого пути.

## Как добавить эффект

Функция в `effects.py` + запись в `EFFECTS` (место в словаре = место в проходе) + запись в `EFFECT_PARAMS`
(литералы) + такое же поле `*Aug` в `dataset_gen/core/config.py` (иначе `test_a4_*` красный; без поля `apply_photometric` падает `AttributeError`).

## Где тесты

- `Services/layer_render/tests/` — `test_acceptance_*` (слепые, тестер), `test_hazards_*` (автор механизма).
- `Services/dataset_gen/tests/test_augment_equivalence.py` — оракул `apply_photometric`, sha-литералы, `EFFECT_PARAMS == AugmentConfig`.
- `Services/line_sim/tests/`, `Plugins/sim/*/tests/` — потребители фона и сцены. Код пакета (кроме `tests/`) не импортирует `line_sim`; тесты эквивалентности обёртки (2.2 a6, 2.3 tester и hazards) — исключения с локальным импортом; исключение утверждено владельцем 2026-10-02, переносить не нужно.

## Открыто

Эффекты на слое/сцене (`apply_effects_rgba`) — вне Task 2.2; границы зоны 4.7d (data_receiver, pipeline_executor, …) не трогать.
