# Фаза 2 — тонкий срез для дообучения

Родитель: [plan.md](plan.md). Итог фазы: обучающие вырезы 128×128 рождаются **тем же** путём, что кадр сима
(фабрика объектов → стек фона → композиция → общий вырез), и складываются на диск в формате, который `ml_train`
читает с `data.source: exported` без правок. После слияния Task 2.3 может стартовать Фаза 1 `letters-retrain`.

Порядок исполнения задач — как в [phase-1.md](phase-1.md) (слепой tester в worktree → исполнитель → инъекции лида →
reviewer синхронно). Переезда модулей в этой фазе нет — он в Фазе 3; фазы не конфликтуют по файлам, кроме
`Services/line_sim/core/factory.py` (2.2) против `layered_object.py` (3.2): 3.2 стартует после слияния 2.2.

---

### Task 2.1 — одна функция выреза диска для `center_crop`, `holdout_eval` и генератора

- **Статус:** [PENDING] · **Level:** Middle+ (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** public-api-change (`Services/layer_render` получает `crop.py`, реэкспорт в `__init__`)
- **CHAIN:** `tester`(RED: снять литералы старого поведения) → `developer`(GREEN) → `reviewer`

**Goal:** вырез квадрата вокруг центра и ресайз ко входу модели живут в одной функции; оба нынешних места зовут её,
их выход не меняется ни на байт.

**Files:**
1. `Services/layer_render/crop.py` (новый) — `side_from_radius(radius, radius_scale, margin_px) -> int`,
   `square_crop(frame, cx, cy, side, oob, pad_value) -> ndarray | None`, `resize_square(crop, out) -> ndarray`
2. `Services/layer_render/__init__.py`, `Services/layer_render/README.md`
3. `Plugins/processing/center_crop/plugin.py` — `_resolve_side`, `_crop_square`, `_resize_output` делегируют
4. `Services/ml_train/holdout_eval.py` — `_crop_disk` делегирует (`side = 2·round(r(1+margin))`, `oob="replicate"`)
- тесты: `Services/layer_render/tests/test_crop_*.py`

**DESIGN:**
- `oob ∈ {"drop", "pad", "clamp", "replicate"}` — ровно четыре нынешних поведения: `drop`/`pad`/`clamp` из
  `center_crop` (`plugin.py:137-168`, `pad` — заливка `pad_value`), `replicate` из `holdout_eval` (`cv2.copyMakeBorder`).
- Привязка квадрата — как сейчас в обоих: `x0 = cx - side // 2`, ширина ровно `side`.
- `side_from_radius` — формула `center_crop` (`plugin.py:120-123`): `max(2, round(2·r·scale) + 2·margin)`.
- Ресайз: `INTER_AREA` при уменьшении, `INTER_LINEAR` при увеличении, `out <= 0` — как есть (`plugin.py:100-110`).
- Формула стороны `holdout_eval` **не меняется** (решение О-1 владельца — отдельно).

**Acceptance:**
- [ ] Литералы до задачи (тестер снимает в worktree на коммите плана): sha256 выреза `center_crop` на фиксированном
      кадре 200×160 для `oob` × {внутри, у края, центр вне кадра} и `holdout_eval._crop_disk` на 3 кадрах у края —
      после задачи те же sha256.
- [ ] Существующие тесты `Plugins/processing/center_crop/tests/` и `Services/ml_train/tests/` — зелёные без правки.
- [ ] `square_crop` с неизвестным `oob` → `ValueError`, текст называет значение.
- [ ] Числа из рецепта `letter_robot_sim.yaml:250-254` (`radius_scale 1.0`, `margin_px 14`, `output_size 128`): `r=150` → сторона 328.

**Goldens:** тесты `center_crop` и `ml_train` (holdout) — зелёные.

**Out of scope:** смена формулы `holdout_eval` (О-1); новые режимы выреза; круглая маска.

---

### Task 2.2 — `SimCropGenerator`: сэмплы обучения из фабрики сима

- **Статус:** [PENDING] (зависит от 1.1, 2.1) · **Level:** Senior+ (Opus 5.5) · **Assignee:** tester → teamlead → инъекции лида → reviewer
- **Module contract:** public-api-change (`ObjectFactory.make` получает необязательный `class_index`; новый публичный класс в `line_sim`)
- **CHAIN:** `teamlead`(INTERFACE: сигнатуры + docstring) → `tester`(RED) → `teamlead`(GREEN) → `reviewer`

**Goal:** `SimCropGenerator` реализует существующий Protocol `SampleGenerator` (`Services/dataset_gen/interfaces.py:19`),
отдаёт `(RGB 128×128, SampleLabel)`, где картинка — вырез сцены сима вокруг диска, метка — класс и угол буквы.

**Files:**
1. `Services/line_sim/core/sim_crop.py` (новый) — `SimCropConfig` (Pydantic) + `SimCropGenerator`
2. `Services/line_sim/core/factory.py` — `make(object_id, spawn_encoder, rng, class_index: int | None = None)`
3. `Services/dataset_gen/core/symmetry.py` — модульная `resolve_symmetries(catalog, sym_cfg) -> dict[int, SymmetryType]`
4. `Services/dataset_gen/core/engine.py` — `_resolve_symmetries` зовёт её (поведение то же)
5. `Services/line_sim/__init__.py`, `Services/line_sim/README.md` — экспорт и раздел «Генератор обучения»
- тесты: `Services/line_sim/tests/test_acceptance_sim_crop.py`, `test_hazards_sim_crop.py`

**DESIGN (один сэмпл, порядок — часть контракта seed):**
1. `class_index` — аргумент или `rng.integers(num_classes)`.
2. `factory.make(f"train-{n}", 0.0, rng, class_index=ci)`. В фабрике: `class_index is None` → путь **байт в байт
   прежний** (`factory.py:147-151`, `rng.integers` разыгрывается); задан → `rng.integers` не зовётся, остальной порядок
   (`uniform` угла → `get_sprite` → `rng.spawn` слоёв) тот же. Пресет грузится с `apply_defect_override(preset, 0.0)`.
3. Окно фона — `render_background` из 1.1 с тем же `background_layers` (схема 1.1, тот же парсер), фаза ленты — случайная
   (`x_px = rng.uniform(0, tile_w)`), поперечный сдвиг — `lateral_offset_px [lo, hi]` в смысле `scene_source` (модуль,
   знак ±1 равновероятно).
4. `composite(окно, obj.render(), центр окна + сдвиг)` — тот же вызов, что `scene_compositor.py:114`.
5. Фотометрия — `apply_photometric(окно, augment, rng)` из `dataset_gen` (в 4.1 заменяется на `scene_effects`).
6. Радиус — половина большей стороны альфа-bbox `obj.render()`; центр выреза ± `center_jitter_px`, радиус ×
   `1 ± radius_jitter_frac`; сторона и вырез — `crop.py` из 2.1 (`radius_scale 1.0`, `margin_px 14`, `pad`, выход 128).
7. Метка: угол буквы = `(passport.angle_deg + angle_deg слоя класса + разыгранный angle_deg слоя из passport.layer_params) % 360`;
   нет слоя `class://` — угол базового слоя 0. Симметрия — `resolve_symmetries` (`dataset_gen`), кодирование — `encode_angle`.
- Дефолты `SimCropConfig`: `lateral_offset_px [10, 20]`, `center_jitter_px [0, 0]`, `radius_jitter_frac [0, 0]`,
  `output_size 128`, `augment` — выключен. Числа джиттера детектора владелец/letters-retrain задаёт пресетом в 2.3.
- Генератор свой rng не держит, если передан внешний (как `DatasetEngine.generate_sample`).

**Acceptance:**
- [ ] `isinstance(gen, SampleGenerator)` — True; `num_classes`/`class_names` = каталогу пресета; кадр `(128,128,3) uint8`.
- [ ] `class_index=None` в `factory.make`: `test_hazards_1_3h_layout.py:40-44` и `test_acceptance_lateral_offset.py:355` — зелёные без правки.
- [ ] **«Идентично там и там»:** при выключенных джиттерах и фотометрии и `lateral 0` сэмпл побайтно равен вырезу
      `square_crop` (2.1) из кадра `SceneCompositor` (тот же `background_layers`, тот же `LayeredObject` на той же позиции).
- [ ] Угол: буква, повёрнутая путём сима (`passport.angle_deg = 37`, слой класса `angle_deg = 10`) и путём `dataset_gen`
      (`rotate_expand` на 47°) — IoU альфа-масок ≥ 0.98; метка = 47.0.
- [ ] Повтор с тем же seed — побайтно тот же сэмпл; 100 сэмплов на пресете с 4 классами — все 4 класса встречаются.
- [ ] `DatasetEngine` (`test_engine.py`, `test_symmetry.py`) — зелёный без правки после выноса `resolve_symmetries`.

**Goldens:** `test_hazards_1_3h_layout.py:40-44`, `test_acceptance_lateral_offset.py:355`,
`test_acceptance_lateral_offset_plugin.py:492-493`, `Services/dataset_gen/tests/test_engine.py`.

**Out of scope:** экспорт на диск (2.3), эффекты сцены (4.1), правки `ml_train`, дефекты, торч-адаптер.

**TRAPS:** `dataset_gen` не импортирует `line_sim` — генератор живёт в `line_sim`. Не звать `spawner.tick()` — генератору
лента не нужна, нужен один объект. Фотометрия на окне, а не на кадре 1440×1080: блик/виньетка зависят от размера кадра —
записать как известное расхождение в README, не «чинить».

---

### Task 2.3 — CLI экспорта вырезов сима + пресет букв + смоук `ml_train`

- **Статус:** [PENDING] (зависит от 2.2) · **Level:** Middle (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** impl-only (CLI поверх публичного API 2.2 и `export_splits`)
- **CHAIN:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**Goal:** одной командой получить `train/val` вырезов сима на диске и сетку-превью; `ml_train` с `data.source: exported`
читает каталог без правок.

**Files:**
1. `Services/line_sim/tools/export_sim_crops.py` (новый) — `--config`, `--out`, `--train N`, `--val M`, `--seed`, `--preview PNG`
2. `Services/line_sim/presets/sim_crops_letters.yaml` (новый) — пример: пресет `letters_layered.yaml`, `background_layers` стенда, джиттеры
3. `Services/line_sim/presets/README.md` — рецепт: экспорт → `ml_train` (`source: exported`, `root: <out>`)
- тесты: `Services/line_sim/tests/test_acceptance_export_sim_crops.py`

**DESIGN:** экспорт — `Services.dataset_gen.export.export_splits(generator, out, {"train": N, "val": M}, seed=S)`; превью —
`Services.dataset_gen.preview.save_preview_grid`. Своего формата меток нет.

**Acceptance:**
- [ ] На 2 классах × `--train 5 --val 2`: `out/train/labels.csv` — 10 строк, `out/val/labels.csv` — 4, `classes.json` есть,
      каждый PNG 128×128.
- [ ] Загрузчик `ml_train` для `source: exported` (тот, что зовёт `python -m Services.ml_train train`) отдаёт один батч
      `(B, 3, 128, 128)` и метки класса/угла — без единой правки `Services/ml_train/`.
- [ ] Два запуска с одним `--seed` — побайтно одинаковые каталоги (sha256 всех файлов).
- [ ] `--preview` пишет PNG-сетку; кривой `--config` → `SystemExit` с путём.

**Out of scope:** само обучение, состав шрифтов и каталог 33 букв (это `letters-retrain` Фаза 1).
