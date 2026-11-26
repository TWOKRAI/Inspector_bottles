# Design: один сервис изображений — карта дублей

Родитель: [design-unified.md](design-unified.md). Код дерева `docs/layer-render-status` (от `main` 53efe24b9), прочитан 2026-11-26.

## 2. Карта дублей (проверено по коду)

Четыре пути: **сим** (`scene_source` → `line_sim.SceneCompositor`), **редактор** (`layer_preview` → `layer_render/preview.py`),
**новое обучение** (`LayerSceneGenerator`, файл `dataset_gen/core/layer_scene.py`), **старое обучение** (`DatasetEngine`,
`dataset_gen/core/engine.py`). Сокращения путей: `lr/` = `Services/layer_render/`, `dg/` = `Services/dataset_gen/`,
`ls/` = `Services/line_sim/core/`, `ss/` = `Plugins/sim/scene_source/plugin.py`.

Вердикт: **дубль** — одна операция написана дважды и больше; **уже одна** — все зовут одну функцию; **законно разное** —
разная задача, причина в строке.

### 2.1 Объект: спрайт, поворот, размер, брак, фон, место

| Операция | Сим | Редактор | Новое обучение | Старое обучение | Вердикт |
|---|---|---|---|---|---|
| выбор спрайта | `lr/factory.py:221` → `lr/catalog.py:223` | тот же `:221` (через `lr/preview.py:106`) | тот же `:221` (через `layer_scene.py:269`) | `engine.py:125` → `lr/catalog.py:223` | **уже одна** (`get_sprite`). Порядок розыгрыша разный: см. «rng». |
| выбор класса | `lr/factory.py:216-217` | тот же | `layer_scene.py:267-268`, затем `class_index` в фабрику | `engine.py:121-122` | одна строка `rng.integers` в трёх местах; уйдёт при заморозке `DatasetEngine`. Отдельного шага не нужно. |
| поворот | `lr/layers.py:173-186` (`_rotate`: кратные 90° — `rot90`, прочие — `rotate_expand`) | тот же | тот же | `engine.py:130` → `lr/compose.py:17` (`rotate_expand` всегда) | **дубль №9**: два правила одной операции. |
| размер объекта | `lr/layers.py:265-268` (масштаб слоя, пиксели спрайта) | тот же | вырез по радиусу: `layer_scene.py:277-282`, затем `resize_square` | `engine.py:139-145` (доля кадра, `fit_longest_side`) | **законно разное**: на ленте — физические пиксели, в обучении — нормировка. Вырез по радиусу + `radius_jitter_frac` даёт ту же нормировку, что доля кадра + разброс. |
| склейка слоёв объекта | `lr/layers.py:295` (`compose_layers`) | тот же | тот же | нет (один спрайт) | **уже одна**; старый путь слоёв не знает. |
| брак | `lr/factory.py:146-153`, пятно `:265-291` → `lr/effects.py:115` | тот же | тот же | брака нет; `occlusion` — аугментация, `lr/effects.py:203` | **законно разное**: брак — класс объекта, окклюзия — помеха. Примитив `apply_occlusion` один. |
| фон | стек заливка/тайл: `ls/scene_compositor.py:99-109` → `lr/background.py:128` | серая плитка `lr/preview.py:196` | стек: `layer_scene.py:194`, `:297` | фото или процедурный: `engine.py:136` → `lr/catalog.py:228-252` | две модели фона в одном пакете, а не дубль кода. Данные фона заданы дважды (находка 4). |
| чтение тайла фона | `ss:436-447` (`_load_layer_image`) | — | `layer_scene.py:184-192` (`load_image`) | `lr/catalog.py:228-252` (фото, другой формат) | **дубль №3**: сим и новое обучение. Проверки разные: сим проверяет dtype и каналы, генератор — только `ndim`. |
| место объекта | лента: `ls/scene_compositor.py:135-144` | по центру плитки `lr/preview.py:204` | центр окна + поперечное смещение `layer_scene.py:273-274`, `:298` | центр + сдвиг + «внутри кадра» `engine.py:147-155` | **законно разное** (это и есть переходник сценария). Кроме смещения: **дубль №4** — `ls/spawner.py:358-363` и `layer_scene.py:273-274` делают те же два розыгрыша (`uniform`, затем знак). |
| тень под объектом | нет | нет | нет | `engine.py:157-165` → `lr/compose.py:79` | не дубль: умение только старого пути. Нужно общему генератору, чтобы повторить старые пресеты. |

### 2.2 Кадр: эффекты, сбор, смесь, вырез, метка, пресет, превью, rng

| Операция | Сим | Редактор | Новое обучение | Старое обучение | Вердикт |
|---|---|---|---|---|---|
| эффекты | пустой список: `ls/scene_compositor.py:145` | нет (`apply_effects` молча не действует, находка 5) | `layer_scene.py:197` → `render_scene` → `lr/effects.py:325` | `engine.py:170` → `dg/core/augment.py:71-79` → `lr/effects.py:325` | функция **уже одна** (`apply_effects`). **Дубль №6** — схема настроек: `AugmentConfig` (`dg/core/config.py:183`, у трёх эффектов `enabled` по умолчанию `True`) и `EffectSpec` (`lr/effects.py:297`); мост `augment.py:62-68`. |
| сбор кадра | `render_scene`: `lr/scene.py:99` (зов `ls/scene_compositor.py:145`) | нет (`scene.preview` — ЛР-09) | `layer_scene.py:299` | свой порядок `engine.py:136-170`: фон → тень → `composite` → эффекты | **дубль №2**: старый путь повторяет «фон → объекты → эффекты» мимо `render_scene`. |
| смесь по альфе | `lr/compose.py:149-153` (`composite`, float32 + 0,5); фон-тайл `lr/background.py:91-101` (`_over`, целые) | `lr/preview.py:203-206` (`_fit_tile`, без округления) | `lr/compose.py:149-153` | `lr/compose.py:149-153` | **дубль №1**: три кода одной формулы (четвёртый — `patch` из draw-universal §1.4). Замер: `composite` = `_over` побайтно, `_fit_tile` отличается на 1 уровень (раздел 3). |
| вырез | линия: `Plugins/processing/center_crop` → `lr/crop.py:25` | — | `layer_scene.py:310`, `:315` → `lr/crop.py:25`, `:82` | нет вырезания (ресайз `engine.py:173-174`) | **уже одна** (задача 6.1). |
| метка / паспорт | паспорт ленты `ls/layered_object.py:56-72` | `{seed, class_name, layer_params}` `lr/preview.py:108-110` | `SampleLabel`: `layer_scene.py:318-331` | `SampleLabel`: `engine.py:176-188` | **дубль №5**: блок метки двух генераторов совпадает построчно. Паспорт, метка и данные плитки — **законно разные** формы одной правды (`RenderedObject`). |
| симметрия | — | — | `layer_scene.py:207` → `dg/core/symmetry.py:133` | `engine.py:197` → тот же `:133` | **уже одна**. |
| пресет / настройки | `ls/preset.py:50` → `ScenePreset` `lr/preset.py:31`; фон — в конфиге плагина `ss:342-356` | `Plugins/sim/layer_preview/plugin.py:296` → тот же | `ScenePreset` + секция `train` (`layer_scene.py:99`, `:213`) | `GeneratorConfig` `dg/core/config.py:255` | **дубль №7**: два формата одного: каталог, угол, эффекты, выход. Конфиг стенда (геометрия ленты) — законно отдельно. |
| превью / сетка | — | `lr/preview.py:96` (ряд объектов, PNG) | сетка QC `dg/preview.py:43` (зов `export_sim_crops.py:114`) | та же `dg/preview.py:43` (зов прототипа `dataset_gen_section.py:214-219`) | **дубль №8**: два сборщика сетки картинок. |
| шрифты | — | — | — | — | **дубль №10**: списки шрифтов `dg/preview.py:17`, `dg/tools/make_ru_letter_sprites.py:25`, `Services/ml_inference/plugin/plugin.py:41`; свой путь шрифта `Services/line_sim/tools/make_font_letters.py:113`. Уже в плане draw-universal 1.2. |
| rng | один поток процесса `ss:283`; слоям — `rng.spawn`, `lr/layers.py:351` | свой `default_rng(seed)` на плитку `lr/preview.py:106` | свой поток `layer_scene.py:208` | свой поток `engine.py:46` | **законно разное**: поток принадлежит сценарию (`render_scene` rng не создаёт, LR-001). Порядок розыгрышей разный: фабрика — класс → угол → спрайт (`lr/factory.py:216-221`), старый путь — класс → спрайт → угол (`engine.py:121-130`). |

### 2.3 Итог

**Итог: 10 настоящих дублей.** №1 смесь по альфе (3 кода), №2 сбор кадра старого пути, №3 чтение тайла, №4 поперечное
смещение, №5 блок метки, №6 схема эффектов, №7 формат пресета, №8 сетка превью, №9 правило поворота, №10 списки шрифтов.
Ещё одна строка в трёх местах — выбор класса (без шага). Уже общие: спрайт, склейка слоёв, эффекты-функции, вырез,
симметрия, процедурный фон, каталог.

## 3. Замеры, на которые опирается дизайн

Скрипт в scratchpad сессии, main `.venv`, `PYTHONPATH` = дерево `lr-audit` (путь пакета показан в выводе):

```
layer_render file: ...\.claude\worktrees\lr-audit\Services\layer_render\__init__.py
import s: 0.65 pydantic loaded: True cv2: True
compose_layers shape (32, 28, 4) sprite (31, 27, 4)
rgb equal to sprite (one static layer, angle 0): False alpha equal: True max rgb diff: 60
composite == background._over: True  composite == preview-trunc: False max diff trunc: 1
```

Что это значит: (1) импорт `layer_render` тяжёлый; (2) один слой через фабрику ≠ исходный спрайт, значит перевод объекта
старого пути меняет пиксели; (3) `composite` и `_over` — одна формула; `_fit_tile` отличается на 1 уровень.
Слабость: (3) — один случайный холст 64×64, не перебор; перебор всех сочетаний делал CTO r2 только для `composite`.
