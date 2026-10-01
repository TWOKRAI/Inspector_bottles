# Фаза 2 — тонкий срез для дообучения

Родитель: [plan.md](plan.md). Итог фазы: обучающие вырезы **любого продукта** рождаются **тем же** путём, что кадр сима
(фабрика объектов → стек фона → композиция → общий вырез), и складываются на диск в формате, который `ml_train`
читает с `data.source: exported` без правок. После слияния Task 2.3 может стартовать Фаза 1 `letters-retrain`.

Порядок исполнения задач — как в [phase-1.md](phase-1.md) (слепой tester в worktree → исполнитель → инъекции лида →
reviewer синхронно). Переезда модулей в этой фазе нет — он в Фазе 3; фазы не конфликтуют по файлам, кроме
`Services/line_sim/core/factory.py` (2.2) против `layered_object.py` (3.2): 3.2 стартует после слияния 2.2.

---

### Task 2.1 — одна функция выреза объекта для `center_crop`, `holdout_eval` и генератора

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

### Task 2.2 — `SimCropGenerator`: сэмплы обучения любого продукта из фабрики сима

- **Статус:** [PENDING] (зависит от 1.1, 2.1) · **Level:** Senior+ (Opus 5.5) · **Assignee:** tester → teamlead → инъекции лида → reviewer
- **Module contract:** public-api-change (`ObjectFactory.make` получает необязательный `class_index`; новый публичный класс в `line_sim`)
- **CHAIN:** `teamlead`(INTERFACE: сигнатуры + docstring) → `tester`(RED) → `teamlead`(GREEN) → `reviewer`

**Goal:** `SimCropGenerator` реализует существующий Protocol `SampleGenerator` (`Services/dataset_gen/interfaces.py:19`),
отдаёт `(RGB, SampleLabel)`: картинка — вырез сцены сима вокруг объекта, метка — класс каталога и угол. Про продукт
генератор не знает ничего: всё продуктовое — в `SimCropConfig` (YAML-пресет) и в каталоге пресета сцены.

**Files:**
1. `Services/line_sim/core/sim_crop.py` (новый) — `SimCropConfig` (Pydantic) + `SimCropGenerator`
2. `Services/line_sim/core/factory.py` — `make(object_id, spawn_encoder, rng, class_index: int | None = None)`
3. `Services/dataset_gen/core/symmetry.py` — модульная `resolve_symmetries(catalog, sym_cfg) -> dict[int, SymmetryType]`
4. `Services/dataset_gen/core/engine.py` — `_resolve_symmetries` зовёт её (поведение то же)
5. `Services/line_sim/__init__.py`, `Services/line_sim/README.md` — экспорт и раздел «Генератор обучения»
- тесты: `Services/line_sim/tests/test_acceptance_sim_crop.py`, `test_hazards_sim_crop.py`

**Продуктовые данные → конфиг (`SimCropConfig`), не код:**

| Что | Ключ | Дефолт (нейтральный) |
|---|---|---|
| Объект, слои, классы | `scene_preset` — путь к `ScenePreset` (классы = `catalog_dir` пресета) | обязателен |
| Фон | `background_layers` — схема и парсер 1.1 | `[{solid: [0,0,0]}]` |
| Слой, чей угол идёт в метку | `label.angle_layer` — имя слоя пресета или `null` | слой `class://`, если есть; иначе `null` (только угол объекта) |
| Симметрии классов | `symmetry` — `SymmetryConfig` из `dataset_gen` (overrides по имени класса, авто-детектор) | как в `dataset_gen` |
| Поперечный сдвиг | `lateral_offset_px [lo, hi]` — смысл как у `scene_source` | `[0, 0]` |
| Вырез | `crop` — **те же поля, что регистр `center_crop`**: `size_mode: radius\|fixed`, `radius_scale`, `margin_px`, `side_px`, `output_size`, `oob` | дефолты `CenterCropRegisters` |
| Ошибка детектора | `crop.center_jitter_px [lo, hi]`, `crop.radius_jitter_frac [lo, hi]` | `[0, 0]` |
| Фотометрия | `augment` — `AugmentConfig` из `dataset_gen` (в 4.1 → `scene_effects`) | выключена |
| Дефекты | `defect_probability` | `0.0` |

**DESIGN (один сэмпл, порядок — часть контракта seed):**
1. `class_index` — аргумент или `rng.integers(num_classes)`.
2. `factory.make(f"train-{n}", 0.0, rng, class_index=ci)`. В фабрике: `class_index is None` → путь **байт в байт
   прежний** (`factory.py:147-151`); задан → `rng.integers` не зовётся, остальной порядок (`uniform` угла → `get_sprite` →
   `rng.spawn` слоёв) тот же. Пресет — через `apply_defect_override(preset, cfg.defect_probability)`.
3. Окно фона — `render_background` из 1.1, фаза ленты случайная (`x_px = rng.uniform(0, tile_w)`, если есть `tile`),
   поперечный сдвиг — модуль из `lateral_offset_px`, знак ±1 равновероятно.
4. `composite(окно, obj.render(), центр окна + сдвиг)` — тот же вызов, что `scene_compositor.py:114`.
5. Фотометрия — `apply_photometric(окно, augment, rng)`.
6. Размер выреза: `size_mode: radius` — радиус = половина большей стороны альфа-bbox `obj.render()` (описанная
   окружность; у круглого объекта совпадает с тем, что даёт `circle_detector`), сторона — `side_from_radius` (2.1);
   `size_mode: fixed` — `side_px`. Центр ± `center_jitter_px`, радиус × `1 ± radius_jitter_frac`; вырез и ресайз — `crop.py`.
7. Метка: угол = `(passport.angle_deg + [angle_deg слоя label.angle_layer + его разыгранный angle_deg из
   passport.layer_params]) % 360`; симметрия — `resolve_symmetries(catalog, cfg.symmetry)`, кодирование — `encode_angle`.
- Генератор свой rng не держит, если передан внешний (как `DatasetEngine.generate_sample`).

**Acceptance:**
- [ ] `isinstance(gen, SampleGenerator)`; `num_classes`/`class_names` = каталогу пресета; кадр `(output_size, output_size, 3) uint8`.
- [ ] **Два продукта, ноль кода между ними:** (а) первый продукт — `letters_layered.yaml` (подложка + слой `class://`,
      `size_mode: radius`); (б) синтетический продукт тестера — 2 класса прямоугольных RGBA-спрайтов 60×30 без слоя
      `class://`, `label.angle_layer: null`, `size_mode: fixed`, `side_px: 96`. Оба дают валидные сэмплы и метки.
- [ ] `class_index=None`: `test_hazards_1_3h_layout.py:40-44` и `test_acceptance_lateral_offset.py:355` — зелёные без правки.
- [ ] **«Идентично там и там»:** при выключенных джиттерах и фотометрии и `lateral 0` сэмпл побайтно равен вырезу
      `square_crop` (2.1) из кадра `SceneCompositor` (тот же `background_layers`, тот же `LayeredObject` на той же позиции).
- [ ] Угол: объект, повёрнутый путём сима (`passport.angle_deg = 37`, слой метки `angle_deg = 10`), и тот же спрайт через
      `rotate_expand` на 47° — IoU альфа-масок ≥ 0.98; метка = 47.0. Для (б) метка = углу объекта.
- [ ] Повтор с тем же seed — побайтно тот же сэмпл; 100 сэмплов на пресете с 4 классами — встречаются все 4.
- [ ] `DatasetEngine` (`test_engine.py`, `test_symmetry.py`) — зелёный без правки после выноса `resolve_symmetries`.
- [ ] `grep -inE "letter|букв|disk|диск" Services/line_sim/core/sim_crop.py` — 0 совпадений.

**Goldens:** `test_hazards_1_3h_layout.py:40-44`, `test_acceptance_lateral_offset.py:355`,
`test_acceptance_lateral_offset_plugin.py:492-493`, `Services/dataset_gen/tests/test_engine.py`.

**Out of scope:** экспорт (2.3), эффекты сцены (4.1), правки `ml_train`, детектор некруглых объектов в конвейере
(plan.md → Out of scope), торч-адаптер.

**TRAPS:** `dataset_gen` не импортирует `line_sim` — генератор живёт в `line_sim`. Не звать `spawner.tick()` — нужен один
объект, не лента. Фотометрия на окне, а не на кадре 1440×1080: блик/виньетка зависят от размера кадра — записать как
известное расхождение в README, не «чинить».

---

### Task 2.3 — CLI `export_sim_crops` + пресет первого продукта + смоук `ml_train`

- **Статус:** [PENDING] (зависит от 2.2) · **Level:** Middle (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** impl-only (CLI поверх публичного API 2.2 и `export_splits`)
- **CHAIN:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**Goal:** одной командой получить `train/val` вырезов любого продукта и сетку-превью; `ml_train` с `data.source: exported`
читает каталог без правок. Первый продукт (буквы на дисках) — пресетом, не кодом.

**Files:**
1. `Services/line_sim/tools/export_sim_crops.py` (новый) — `--config`, `--out`, `--train N`, `--val M`, `--seed`, `--preview PNG`
2. `Services/line_sim/presets/sim_crops/letters_disk.yaml` (новый) — первый продукт: `letters_layered.yaml`, `background_layers`
   стенда, `crop` = рецепт `letter_robot_sim.yaml:250-254` (`radius`, `1.0`, `14`, `128`), `lateral_offset_px [10, 20]`
3. `Services/line_sim/presets/README.md` — рецепт «экспорт → `ml_train`» и раздел «Новый продукт: что скопировать и
   поменять» (`scene_preset`/`catalog_dir`, `symmetry`, `label.angle_layer`, `crop`)
- тесты: `Services/line_sim/tests/test_acceptance_export_sim_crops.py`

**DESIGN:** экспорт — `Services.dataset_gen.export.export_splits(generator, out, {"train": N, "val": M}, seed=S)`; превью —
`Services.dataset_gen.preview.save_preview_grid`. Своего формата меток нет.

**Acceptance:**
- [ ] 2 класса × `--train 5 --val 2`: `out/train/labels.csv` — 10 строк, `out/val/labels.csv` — 4, `classes.json` есть,
      каждый PNG — квадрат `crop.output_size`.
- [ ] Загрузчик `ml_train` для `source: exported` отдаёт батч `(B, 3, 128, 128)` и метки класса/угла — без правок `Services/ml_train/`.
- [ ] Два запуска с одним `--seed` — побайтно одинаковые каталоги (sha256 всех файлов).
- [ ] Тот же CLI на синтетическом продукте (б) из 2.2 — работает без правки кода.
- [ ] `--preview` пишет PNG-сетку; кривой `--config` → `SystemExit` с путём.

**Out of scope:** само обучение, шрифты и каталог классов первого продукта (это `letters-retrain` Фаза 1).
