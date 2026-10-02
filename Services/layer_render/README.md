# layer_render — слои сцены: фон, объект, пресет, каталог классов

Слой Services. Механизмы: «стопка слоёв снизу вверх -> кадр фона», стек слоёв объекта, пресет сцены (`ScenePreset`), каталог классов (`SpriteCatalog`). Ничего не знает про энкодер, ленту,
`line_sim`, `dataset_gen`, `ml_train`, плагины и прототип: вызывающий отдаёт готовый сдвиг `scroll_px` числом.

## Контракт (`Services.layer_render`)

| Имя | Что |
|-----|-----|
| `SolidFill(color_rgb)` | сплошная заливка, цвет **RGB** (не BGR), три целых 0..255 |
| `ScrollingTile(image)` | тайл uint8 `(H, W, 3)` RGB или `(H, W, 4)` RGBA; едет по X, повторяется по ширине; хранит собственную **read-only копию** массива (правка исходника на кадр не влияет) |
| `background_layers_from_config(items, load_image)` | YAML-список -> список слоёв; схему проверяет целиком до загрузки картинок |
| `fold_background(layers)` | свёртка стека для скорости (см. ниже) |
| `render_background(frame, layers, *, scroll_px, origin_xy, center_y)` | рисует стек в `frame` (HxWx3 RGB uint8) на месте |
| `rotate_expand(sprite_rgba, angle_deg)`, `crop_to_alpha(sprite_rgba)`, `fit_longest_side(sprite, target_px)` | (`compose`, Task 2.1) геометрия спрайта: поворот CCW с расширением холста, обрезка по alpha > 0, масштаб длинной стороны |
| `cast_contact_shadow(background_rgb, sprite_rgba, center_xy, opacity, blur_px, offset_xy)`, `composite(background_rgb, sprite_rgba, center_xy)` | (`compose`, Task 2.1) контактная тень и альфа-композиция спрайта на фон; обе возвращают копию, фон не меняют |
| `imread_unicode(path, flags)`, `imwrite_unicode(path, image_bgr)` | (`io`, Task 2.1) чтение/запись изображений с non-ASCII путями (Windows-safe); `ValueError` при нечитаемом файле / сбое кодирования |
| `EFFECTS`, `EFFECT_PARAMS` | (`effects`, Task 2.2) упорядоченный реестр фотометрических эффектов `name -> fn(x_float32, params, rng) -> x` (кроме `jpeg`: он принимает и возвращает uint8; `apply_effects` сам делает clip→uint8 и обратно) (12 шт., порядок вставки = порядок прохода: блик, тень, окклюзия, расфокус, смаз, виньетка, яркость/контраст, gamma, температура, сдвиг каналов, шум, JPEG) и литералы дефолтов параметров |
| `EffectSpec(name, prob=1.0, params={})` | (`effects`) шаг списка; `ValueError` на неизвестное имя / ключ параметра / prob вне 0..1; `params` — глубокая копия под `MappingProxyType` (read-only только верхний уровень, вложенные списки изменяемы), недостающие ключи из `EFFECT_PARAMS`; сравнение по идентичности |
| `apply_effects(frame_u8, specs, rng)` | (`effects`) прогон списка по порядку; вентиль `rng.random() < prob` тянется всегда; пустой список — копия кадра без розыгрышей; вход не меняется |
| `apply_glare`, `apply_shadow`, `apply_occlusion`, `apply_motion_blur`, `make_motion_kernel`, `apply_vignette`, `apply_brightness_contrast`, `apply_gamma`, `apply_color_temperature`, `apply_channel_shift`, `apply_jpeg` | (`effects`, Task 2.2) функции эффектов, перенесены из `dataset_gen.core.augment` без изменений |
| `side_from_radius(radius, radius_scale, margin_px)` | (`crop`, Task 6.1) сторона квадрата: `max(2, int(round(2·r·scale)) + 2·int(margin))` |
| `square_crop(frame, cx, cy, side, oob, pad_value=(0,0,0))` | (`crop`, Task 6.1) квадрат `side`×`side`, угол `(cx - side//2, cy - side//2)`; **всегда копия**, не view кадра. `oob` у границы: `drop` -> `None`; `pad` -> холст `pad_value`; `clamp` -> обрезка по кадру (нет пересечения -> `None`); `replicate` -> репликация края (нет пересечения -> `ValueError`; **потребителей нет с Task 6.4**, режим оставлен как контракт, закреплённый тестами 6.1).  Неизвестный `oob` -> `ValueError` |
| `resize_square(crop, out)` | (`crop`, Task 6.1) ресайз к `out`×`out`: `out <= 0` или уже готово -> тот же объект; иначе INTER_AREA при `crop.shape[0] > out`, INTER_LINEAR иначе |
| `LayerMode`, `RangeF`, `SpriteSource`, `AUGMENT_FIELDS`, `LayerAugment`, `LayerSpec` | (`layers`, Task 2.3) слой объекта и диапазоны его аугментации (pydantic, frozen); перенесены из `line_sim.interfaces` дословно, поля не менялись. Поворот CCW, ось Y вниз |
| `load_layer_sprite(layer)` | (`layers`) RGBA uint8 спрайт слоя; callable-провайдер зовётся один раз; строковый id -> `TypeError`, не RGBA -> `ValueError` |
| `transform_layer(sprite, scale, angle_deg, hue_deg, color_rgb=None)` | (`layers`) заливка -> scale -> поворот (кратные 90° — `rot90`) -> сдвиг тона; без трансформа возвращает **сам** `sprite` (не копию) |
| `canvas_size(placed)` | (`layers`) размер `(w, h)` симметричной канвы под `[(RGBA, offset_x, offset_y)]` без рендера |
| `compose_layers(layers, rng, object_angle_deg=0.0, forced_defects=(), *, label="")` -> `ComposedLayers(rgba, layer_params, active_defects)` | (`layers`) розыгрыш и композиция стека: слой i берёт `rng.spawn(len(layers))[i]`; `rgba` — новый **записываемый** массив; `active_defects` — в порядке слоёв. Ошибки по порядку: `forced_defects` строкой -> `TypeError`; пустой список -> спрайты -> дубли имён -> неизвестный `forced_defects` -> прозрачный итог (`ValueError`). Все с префиксом `LayeredObject '<label>':`, кроме ошибок спрайта (`load_layer_sprite`: `TypeError`/`ValueError` с именем слоя, без префикса). Известное старое поведение (follow-up, не исправлено): стек, где на канву не попал ни один слой (только defect-слои, ни один не активен), падает сырым `ValueError` из `max()` на пустой последовательности |
| `ScenePreset`, `CLASS_SPRITE_SOURCE` | (`preset`, Task 2.4a) пресет сцены (pydantic, frozen): `catalog_dir`, `angle_range_deg`, `defect_probability`, `layers`, `base_dir`; `from_dict`/`to_dict`/`from_yaml`/`to_yaml`/`resolve_path`. Перенесён из `line_sim.core.preset` дословно. Блок конфига стенда (`REPO_ROOT`, `resolve_repo_path`, `apply_defect_override`, `load_scene_preset`) остался в `line_sim.core.preset`: здесь `REPO_ROOT` нет |
| `SpriteCatalog(config, background_cache_size=64)`, `ClassEntry`, `CatalogConfig(classes_dir, backgrounds_dir=None)` | (`catalog`, Task 2.4a) каталог классов: лист = папка со спрайтами RGBA, индекс по пути; `get_sprite(i, rng)`, `get_background(rng, size_hw)` (фон из папки или процедурный). Перенесены из `dataset_gen.core.catalog` и `dataset_gen.core.config` дословно |
| `ClassMeta`, `load_meta(directory)`, `write_meta(directory, meta)`, `SymmetryType`, `META_FILENAMES` | (`metadata`, Task 2.4a) разметка узла каталога (`meta.yaml`/`.yml`/`.json`), наследуется сверху вниз. Перенесены из `dataset_gen.core.metadata` и `dataset_gen.core.config` |
| `procedural_background(rng, size_hw)` | (`procedural_backgrounds`, Task 2.4a) случайный процедурный фон из 4 текстур (`gradient_bg`, `brushed_metal_bg`, `conveyor_belt_bg`, `speckled_bg`, реестр `_GENERATORS`). Имя модуля не `backgrounds`: рядом `background.py` (стек слоёв фона) |

Карта зоны выреза: `docs/maps/crop.md`.

Старые места импорта работают (реэкспорт, тот же объект): `Services.dataset_gen.core.compose.*` и
`Services.dataset_gen.core.catalog.imread_unicode` / `imwrite_unicode`, `Services.dataset_gen.core.augment.apply_*` (11 функций), `Services.line_sim.interfaces.LayerSpec` и ещё пять типов слоя, `Services.line_sim.core.preset.{ScenePreset, CLASS_SPRITE_SOURCE}` (Task 2.4a), `Services.dataset_gen.core.{catalog,metadata,backgrounds}` (все имена, включая `imread_unicode`/`imwrite_unicode` и `_GENERATORS`), `CatalogConfig` и `SymmetryType` из `Services.dataset_gen.core.config`, `Services.line_sim.core.layered_object.canvas_size`, `LayeredObject._transform` (= `transform_layer`). `LayeredObject` — обёртка: разбор `passport.defect`, `compose_layers`, паспорт, read-only кэш. Код функций перенесён без изменений. `apply_photometric(frame, cfg, rng)` остался в `dataset_gen` и стал одной строкой над `apply_effects(frame, augment_config_to_effects(cfg), rng)`.

## Схема YAML `background_layers`

Список слоёв **снизу вверх**; элемент — словарь ровно с одним ключом:

```yaml
background_layers:
  - solid: [0, 0, 0]                    # RGB, не BGR; три целых 0..255
  - tile: data/line_sim/belt_tile.png   # путь от корня репозитория; RGBA — по альфа-каналу
```

Нарушение схемы (пустой список, не словарь, не один ключ, неизвестный ключ, цвет не из трёх целых 0..255,
bool/float/str в цвете) — `ValueError("background_layers[<i>]: <причина>: <repr элемента>")`. `load_image(path)`
вернул `None` (картинка нечитаема, об ошибке уже доложено) — слой выбрасывается, порядок остальных сохраняется;
выброшены все — стек пуст, кадр чёрный.

**Где живёт ключ.** Сейчас `background_layers` — ключ конфига плагина `scene_source` (дефолт стенда). По вердикту
CTO 2026-10-01 (`plans/layer-render/cto-verdict-2026-10-01.md`) фон переедет в пресет сцены (`background.layers`,
схема та же); ключ конфига останется дефолтом с приоритетом `пресет > background_layers`.

## Порядок сцены

Снизу вверх: чёрный (под всеми слоями) -> слои фона по порядку -> активные объекты (рисует компоновщик).
Тайл индексируется циклически по ширине: `cols = (arange(w) + origin_x - scroll_px) % tw`; по высоте кладётся
симметрично `center_y` (`top = round(center_y - th/2)`), строки кадра вне полосы тайла не трогаются — виден слой
ниже. Положительный `scroll_px` двигает содержимое тайла вправо.

## Свёртка (`fold_background`)

`SolidFill` прячет всё под собой — отсчёт от последнего. Первый тайл над подложкой (или над неявным чёрным)
запекается с её цветом в непрозрачный RGB-тайл: `out = (a*t + (255-a)*c + 127) // 255` в uint16. Результат:
`[SolidFill, (непрозрачный RGB-тайл)?, *остальные тайлы]`. Остальные тайлы идут общим путём «over» с тем же
округлением, поэтому свёрнутый и несвёрнутый стек дают одинаковые пиксели (альфа 0 и 255 — точно).

**Цена.** Замер 1440×1080 (Task 1.1, до удаления прежнего одиночного тайла): прежний путь ≈ 8.8–9.1 мс, свёрнутый `[solid, RGBA-тайл]` ≈ 3.0–3.2 мс.
Второй и следующие RGBA-тайлы идут общим путём «over»: смешивание идёт по строкам полосы тайла на всю ширину
кадра, цена ∝ min(`th`, высота кадра). Замер (кадр шириной 1440): +28.6 мс на лишний RGBA-тайл при `th=484`,
+65.8 мс при `th=1080`. Сегодня стенду нужен один тайл; ускорять — когда появится стек с двумя.

## Использование

`SceneCompositor(background_layers=...)` (`Services/line_sim`) и ключ `background_layers` плагина `scene_source`.
Миграция (layer-render 1.3): параметр компоновщика `background_tile` и ключ плагина `background_texture` удалены (ключ в конфиге — `ValueError`); вместо них `background_layers: [{solid: [R, G, B]}, {tile: <путь>}]`.

## Как добавить эффект

1. Функция `apply_<имя>(frame, ...)` в `effects.py` (float32 0–255 на входе и выходе; кодек-эффекту нужен uint8 — добавить имя в `_U8_EFFECTS`).
2. Запись в `EFFECTS` — функция-шаг `(x, params, rng) -> x` без вентиля вероятности, значения тянет из `rng` в фиксированном порядке; место записи в словаре = место в проходе.
3. Запись в `EFFECT_PARAMS` — дефолты параметров литералами (без `enabled`/`prob`); `layer_render` не импортирует `dataset_gen`, равенство полям `AugmentConfig` держит `test_a4_*`.
4. Мост `augment_config_to_effects` (`dataset_gen/core/augment.py`) делает `getattr(cfg, имя)` для КАЖДОГО ключа `EFFECTS`: каждый ключ `EFFECTS` обязан быть полем `AugmentConfig` — добавить поле `*Aug` в `dataset_gen/core/config.py` и литерал в `test_a4_*` (`test_augment_equivalence.py`). Иначе `apply_photometric(frame, AugmentConfig(), rng)` падает с `AttributeError`. (Учесть в 4.1 и Ф3.)

`EFFECTS` и `EFFECT_PARAMS` — точка расширения на этапе импорта; во время работы их менять нельзя (каждый новый `EffectSpec` читает их заново).
