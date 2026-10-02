# layer-render — как сейчас

Родитель: [plan.md](plan.md).

## Как сейчас (сверено по коду `main` 0d2d6ec2)

Это **не два независимых движка**: `line_sim` уже стоит на примитивах `dataset_gen` — `composite`/`rotate_expand`
(`Services/line_sim/core/layered_object.py:21`, `scene_compositor.py:35`), `SpriteCatalog` и `imread_unicode`
(`core/catalog_bridge.py:16-17`), `apply_occlusion` (`core/factory.py`). Дублирование — в пяти местах:

| Что | Где раз | Где два |
|---|---|---|
| Источник «текст-глиф» | `Services/line_sim/tools/make_font_letters.py` (493 стр.) | `Services/dataset_gen/tools/make_ru_letter_sprites.py` (132 стр.) |
| Вырез объекта | `Plugins/processing/center_crop/plugin.py:112-123` (`2r·scale + 2·margin`, pad/clamp/drop) | `Services/ml_train/holdout_eval.py:44-61` (`2·round(r(1+margin))`, replicate) |
| Фотометрия | только `dataset_gen/core/augment.py:180-260` (`apply_photometric`, порядок зашит) | в симе нет вовсе |
| Фон | `SceneCompositor`: заливка `background_bgr` + один RGB-тайл (`scene_compositor.py:84-103`) | `dataset_gen` — каталог фонов |
| Модель размера | сим — пиксели/мм | `dataset_gen` — `placement.object_size_frac` |

Плюс torch-аугментации `ml_train` (`config.py:60-64`) — вне плана (см. Out of scope).
