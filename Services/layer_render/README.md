# layer_render — стек слоёв фона

Слой Services. Механизм «стопка слоёв снизу вверх -> кадр фона». Ничего не знает про энкодер, ленту,
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

Старые места импорта работают (реэкспорт, тот же объект): `Services.dataset_gen.core.compose.*` и
`Services.dataset_gen.core.catalog.imread_unicode` / `imwrite_unicode`. Код функций перенесён без изменений.

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
