# Вердикт CTO (Fable) по архитектуре сервиса слоёв — 2026-10-01

Родитель: [plan.md](plan.md). Запрос владельца: «целый сервис, с помощью которого делался бы и фон из слоёв, и объекты —
как для симулятора, так и для обучения с аугментацией из слоёв»; приоритет — хороший редактор слоёв (фон слоями, эффекты
с превью, удобство канвы, Qt-версия). База: `main 6cb6e945`, worktrees `lr11-impl`/`lr12-impl` на `4b152c52`.

**Вердикт: ACCEPT WITH CONDITIONS.** Пакет ниже обоих сервисов — верно. Меняются: граница сервиса (в него уезжают
пресет, фабрика, каталог, превью), формат пресета (фон и эффекты — в файле пресета), порядок фаз (редактор раньше
источников, обучение — параллельной дорожкой). Волна 1 сливается без правок API.

## Решения

1. **Сервис = библиотека `Services/layer_render`, процессы — тонкие плагины.** Сим рендерит в своём процессе, обучение — в
   воркере DataLoader, редактору нужен процесс превью `layers` (`Plugins/sim/layer_preview`) — он уже есть.
2. **Граница шире плана:** кроме `compose/layers/effects/background/crop/sources` вниз уезжают `ScenePreset`, `ObjectFactory`,
   `SpriteCatalog`, `preview`. Иначе генератор обучения живёт в `line_sim` и обучение зависит от симулятора ленты.
   Паспорт ленты остаётся в `line_sim`: `layer_render.factory` отдаёт `RenderedObject(rgba, class_name, angle_deg, defect,
   layer_params)`, `LayeredObject` = он + `ObjectPassport`.
3. **Одна функция сцены `render_scene(background, placed_objects, effects, rng)`** (`layer_render.scene`): её зовут
   `SceneCompositor.render`, генератор обучения и `scene.preview` редактора — гарантия «что в редакторе, то в симе и в обучении».
4. **Фон и эффекты сцены — поля пресета**, не конфиг плагина. Ключ `background_layers` (Task 1.1) — дефолт стенда;
   приоритет `preset.background > config background_layers > background_texture`, лог называет источник.
5. **`preset.get/commit` остаются в `scene_source`** (живая подмена фабрики), логика (rev, ограда, атомарная запись через
   `recipe`, ADR-RCP-008) — в `layer_render.preset_store`.
6. **`dataset_gen` остаётся обучением:** `DatasetEngine` (классический генератор), labels, symmetry, export, torch,
   metadata, realcut + новый `LayerSceneGenerator` (бывш. `SimCropGenerator`) поверх `layer_render`. Пресеты не мигрируют.
   **Открыто владельцу** (2026-10-01, вопрос «у нас будет два механизма?»): судьба `DatasetEngine` — см. журнал plan.md.
7. **`line_sim` = лента:** belt, spawner, `SceneCompositor` (обёртка над `render_scene` + отсечение + паспорта), matching, truth.

## Отвергнуто

- Растить `dataset_gen` в сервис — сим и редактор зависели бы от «датасета»; 70 входящих рёбер (frontend 18).
- Генератор обучения в `line_sim` — `ml_train` импортировал бы симулятор ленты.
- Процесс-сервис рендера для всех — кадр 1440×1080 через IPC каждый тик; библиотека даёт тот же код без цены.
- Отдельная живая команда `scene.effects.set` (4.4) — эффекты в пресете, `preset.commit` применяет живьём.
  Частично пересматривает О-2 — **владельцу подтвердить**.
- `locked` в механизме — состояние клиента; в механизм только `enabled` (`rng.spawn` на слой остаётся).

## Карта модулей (цель)

| Модуль | Ответственность | Зависит от |
|---|---|---|
| `layer_render/io`, `compose` | imread/imwrite; composite, rotate_expand, crop_to_alpha, fit, contact_shadow | cv2/numpy |
| `layer_render/layers` | `LayerSpec`(+`enabled`, `effects`), `LayerAugment`, `compose_layers`, `canvas_size` | compose, effects |
| `layer_render/background` | `SolidFill`/`ScrollingTile`, `fold_background`, `render_background` (волна 1) | — |
| `layer_render/effects` | `EFFECTS`, `EffectSpec`, `EFFECT_PARAMS`, `effects_from_config`, `apply_effects(_rgba)` | cv2 |
| `layer_render/scene` | `render_scene(background, placed, effects, rng)` | background, compose, effects |
| `layer_render/catalog`, `sources` | `SpriteCatalog` (переезд); image/class/solid/glyph/cutout | io |
| `layer_render/preset` | `ScenePreset` v2 (объект + `background` + `effects` + `train`), YAML, пути | layers, pydantic |
| `layer_render/factory` | `ObjectFactory` → `RenderedObject` | catalog, layers, preset |
| `layer_render/preview` | grid, layout, `scene_preview`, ограда путей | factory, scene |
| `layer_render/preset_store` | get / commit(base_rev) → rev, conflict, атомарно | `framework.modules.recipe` |
| `layer_render/crop` | `side_from_radius`, `square_crop`, `resize_square` | cv2 |
| `dataset_gen` | `DatasetEngine`, labels, symmetry, export, torch, realcut, `LayerSceneGenerator` | layer_render |
| `line_sim` | belt, spawner, `SceneCompositor`, matching, truth, `LayeredObject` | layer_render, dataset_gen |
| `Plugins/sim/scene_source` | хост сима: `produce()`, `preset.get/commit`, поток эффектов `[seed,1]` | line_sim, preset_store |
| `Plugins/sim/layer_preview` (`layers`) | бэкенд редактора: preview/layout/sprites/sprite_put + `preset.schema`/`effects.catalog`/`scene.preview` | layer_render |
| `Plugins/sim/pult_web`; Qt (Ф8) | тонкие клиенты одних команд | router; gui-constructor И3 |

Границы sentrux (Task 1.3): `layer_render ↛ line_sim/dataset_gen/ml_train`, `dataset_gen ↛ line_sim`.

## Схема пресета v2 (эскиз)

```yaml
schema_version: 2                 # нет ключа = v1; новые поля с дефолтами — v1-файлы грузятся как есть
catalog_dir: ../../../data/line_sim/letters_ink
angle_range_deg: [0, 360]
defect_probability: 0.0
background:                       # стек снизу вверх, схема Task 1.1 без изменений
  layers: [{solid: [0, 0, 0]}, {tile: ../../../data/line_sim/belt_tile.png}]
layers:                           # поля LayerSpec как есть (на них стоит pult_web)
  - {name: disk, mode: static, sprite_source: ../../../data/line_sim/letters_ink_disk.png,
     enabled: true, effects: [{name: noise, prob: 1.0, std: [1, 3]}]}
  - {name: letter, mode: augmented, sprite_source: "class://", augment: {angle_deg: [-5, 5]}}
effects:                          # на весь кадр после композиции, свой поток rng [seed, 1]
  - {name: gaussian_blur, prob: 0.5, sigma: [0.4, 1.8]}
train:                            # читает только LayerSceneGenerator
  crop: {size_mode: radius, radius_scale: 1.0, margin_px: 14, output_size: 128}
  label: {angle_layer: letter}
```

Контракт rng не меняется: `effects: []` = ноль розыгрышей; эффекты слоя — из sub-rng слоя после нынешних розыгрышей;
эффекты сцены — отдельный поток; `enabled: false` сохраняет `spawn`.

## Команды редактора (один бэкенд, два клиента)

| Команда | Процесс | Что даёт |
|---|---|---|
| `preset.get` / `preset.commit {preset, base_rev}` | `scene_source` | есть; v2-поля едут словарём |
| `preset.schema` | `layers` | **новая**: `ScenePreset.model_json_schema()` — формы для `augment`/`effects`/`background` (сейчас вложенные поля read-only, `pult_web/plugin.py:596-602`) |
| `effects.catalog` | `layers` | **новая**: имя → параметры, диапазоны, дефолты |
| `preset.preview` / `preset.layout {…, apply_effects}` | `layers` | есть (+флаг) |
| `scene.preview {preset, seed, size_px}` | `layers` | **новая**: кадр `render_scene`; приёмка — побайтно равен кадру `SceneCompositor` |
| `preset.sprites` / `preset.sprite_put` | `layers` | есть |

Канва (сетка/привязка, мультивыбор, хоткеи, zoom-to-fit, lock) — только клиент; `enabled` — поле слоя.

## Волна 1

- **1.1 согласована**, условия к слиянию: (а) README — ключ конфига = дефолт стенда, фон переедет в пресет;
  (б) ветка `background_tile` в `scene_compositor.py` удаляется после перевода стенда (1.3); (в) риск второго RGBA-тайла
  (несвёрнутый путь 39.5 мс против 3.2 мс свёрнутого и 8.8 мс старого, 1440×1080) — записать, не чинить.
- **1.2 согласована:** пороги — данные продукта в инструменте `line_sim`, не в механизме.

## Порядок фаз (предложение CTO, до утверждения владельцем)

| Фаза | Задачи | Ждёт |
|---|---|---|
| Ф1 фон слоями | 1.1, 1.2 → 1.3 стенд + sentrux | — ; открывает letters-retrain 0.4 |
| Ф2 ядро | compose/io ∥ effects → layers → переезд ScenePreset/ObjectFactory/SpriteCatalog/preview → `render_scene` | Ф1 |
| Ф3 пресет v2 | `background`/`effects`/`enabled`/`schema_version`; эффекты сцены в `produce()` → `preset_store` | Ф2 |
| Ф4 бэкенд редактора | `preset.schema` + `effects.catalog` → `scene.preview`, приёмка «редактор == сим» | Ф3 |
| Ф5 HTML-редактор | панель фона → панели эффектов с живым превью → канва (сетка, мультивыбор, хоткеи, видимость) | Ф4 |
| Ф6 обучение (∥ Ф3–Ф5) | crop → `LayerSceneGenerator` в `dataset_gen` → export CLI → holdout | Ф2; открывает letters-retrain Ф1 |
| Ф7 источники | бывш. 5.1–5.3 | Ф2 |
| Ф8 Qt-клиент | вкладка `sim.*`, паритет сценариев | gui-constructor И3 |

## Риски

- Переезд — 15 не-тестовых файлов импортируют `dataset_gen`, 5 — `line_sim`; реэкспорты обязательны.
- `extra="forbid"` + `train`-секция: сим обязан объявить поле и игнорировать.
- Без `preset.schema` HTML не сможет править эффекты — критический путь Ф5.
- Объём ≈ 24 задачи против 17 (≈ +40 % к оценке 7.2 M).

## Проверено запуском

`sentrux check .` → 37 rules, `✓ All rules pass`; `graph_slice` `dataset_gen`: входящих 70 (line_sim 37, frontend 18,
ml_train 10, Plugins/sim 3); `line_sim`: входящих 60, наружу 52 (dataset_gen 37); smoke `lr11-impl` — свёртка == общий путь,
max|diff| 0. **Не проверено:** побайтное равенство `render_scene` ↔ `SceneCompositor.render` (проектное требование),
`dataset_gen/core/catalog.py` не читан, живой стенд не поднимался.
