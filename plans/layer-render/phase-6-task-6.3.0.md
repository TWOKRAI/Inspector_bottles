# Task 6.3.0 — байтовый литерал на выход `LayerSceneGenerator` (до кода 6.3)

Родитель: [phase-6-task-6.3.md](phase-6-task-6.3.md) (стадия 1 «Порядок запуска»); справка — [phase-6-task-6.3-context.md](phase-6-task-6.3-context.md). Эталоны — [goldens.md](goldens.md).

## Подзадача (свой коммит, до любого кода 6.3)

**Исполнитель:** `developer`, Level Middle+. **Файл (единственный):** `Services/dataset_gen/tests/test_layer_scene_golden_6_3.py` (новый).
**Коммит:** `test(dataset_gen): литерал выхода LayerSceneGenerator до Task 6.3` с `Why:`/`Layer: Services`/`Refs: plans/layer-render/phase-6-task-6.3.md`.
Строку в `goldens.md` добавляет лид.

**Правило оракула (урок 6.2 J1).** Ни одно ожидаемое значение не считается через `ObjectFactory`, `render_scene`,
`square_crop`, `resize_square`, `encode_angle` или сам генератор. Два вида ожидаемого: (а) **независимый numpy-оракул** —
кадр собран вручную `np.full` + срез; (б) **литералы** sha256 и полей метки, вставленные из ОДНОГО прогона на `87dd240dc`
(win32), никогда не вычисляются в `assert`. Докстринг модуля — как у `test_engine_golden_m4.py:1-20` (что закреплено, где
снято, «красный литерал — находка, не повод переписать»).

**Синтетика** (в `tmp_path`, numpy → PNG через PIL; `data/` не читается):

- **G1 — независимый оракул.** Каталог 2 класса `k0`, `k1`, по одному спрайту RGBA **60×30** (ширина 60, высота 30), альфа
  255 везде, цвет `k0` = `(200, 40, 40)`, `k1` = `(40, 200, 40)`. Пресет: `catalog_dir`, `angle_range_deg: [0, 0]`, `layers: []`,
  `train: {label: {angle_layer: null}, symmetry: {auto_detect: false}, background_layers: [{solid: [20, 40, 60]}],
  crop: {size_mode: fixed, side_px: 96, output_size: 96}}`. Для `ci ∈ {0, 1}` × `s ∈ {0, 1, 2}`:
  `frame = gen.generate_sample(class_index=ci, rng=default_rng(s))[0]`; ожидаемое — `np.full((96, 96, 3), (20, 40, 60), uint8)`,
  в нём `[33:63, 18:78] = цвет класса` (прямоугольник по центру выреза: `(96−30)/2 = 33`, `(96−60)/2 = 18`); `np.array_equal`.
  Метка: `class_index == ci`, `class_name == ["k0", "k1"][ci]`, `angle_deg == 0.0`, `angle_sin == 0.0`, `angle_cos == 1.0`,
  `symmetry == "none"`, `angle_valid is True`.
  **Если оракул не равен выходу** — не подгонять оракул: снять дифф (где отличаются пиксели, сколько), стоп, `ESCALATION -> teamlead` через лида.
- **G1-radius — тот же оракул, вырез по радиусу.** Каталог и пресет G1, только `crop: {size_mode: radius, radius_scale: 1.0,
  margin_px: 18, output_size: 96}`. Радиус по альфа-bbox `max(60, 30) / 2 = 30`; сторона `round(2·30·1.0) + 2·18 = 96` — ресайза нет.
  Те же `ci × s`, то же ожидаемое `np.full` + `[33:63, 18:78]`, та же метка. Закрепляет ветку `size_mode: radius` без литерала.
- **G2 — sha256-литералы, богатый кейс.** Каталог 3 класса `k0`, `k1`, `k2`: асимметричные спрайты 64×64 (Г-образная маска,
  разные цвета, numpy-шум ±30 с фиксированным seed, как `_textured` в `test_engine_golden_m4.py:34-43`). Файл `under.png` — RGBA круг
  диаметра 100 на канве 104, цвет `(230, 230, 230)`. Файл `tile.png` — RGBA **40×160 (ширина 40, высота 160)**: numpy-шум seed 5, альфа 0 в столбцах 0..5.
  Пресет: `angle_range_deg: [0, 360]`, `layers: [{name: under, mode: static, sprite_source: under.png},
  {name: obj, mode: augmented, sprite_source: "class://", angle_deg: 10, augment: {angle_deg: [-5, 5]}}]` (форма `augment` слоя —
  как в 6.2 ACCEPTANCE 4; имя `base` не годится — с `catalog_dir` оно зарезервировано, `layer_render/preset.py:22,91-97`); `train: {label: {angle_layer: obj}, symmetry: {auto_detect: false, overrides: {k1: "180"}},
  background_layers: [{solid: [10, 10, 10]}, {tile: tile.png}], lateral_offset_px: [3, 9],
  crop: {size_mode: radius, radius_scale: 1.0, margin_px: 6, output_size: 64, center_jitter_px: 2.0, radius_jitter_frac: 0.1},
  augment: {noise: {enabled: true, prob: 1.0}, brightness_contrast: {enabled: false}, gaussian_blur: {enabled: false},
  color_temperature: {enabled: false}}}`. Кейсы: `generate_sample(rng=default_rng(s))` для `s ∈ {0, 1, 2, 3}` (класс разыгрывается) и
  `generate_sample(class_index=2, rng=default_rng(100 + s))` для `s ∈ {0, 1}`. Литерал на кейс: sha256 `frame.tobytes()`, `shape`,
  `dtype`, все поля `label.to_dict()` (float — точным `==`, как m4).
  Требование к литералам: среди 4 кейсов с розыгрышем класса встретились ≥ 2 разных класса (утверждение в тесте по
  литералам `class_index`); на GREEN один класс на всех seeds — сменить seeds, утверждение не ослаблять.
- **G3 — внутренний поток.** Пресет G2, `LayerSceneGenerator(preset, seed=11)`, три вызова `generate_sample()` подряд без `rng` —
  три sha256 кадра и **все** поля `label.to_dict()` литералами (как G2) — иначе L5 G3 не красит.

**Инъекции лида по литералу** (стадия 2; по одной, откат после каждой; предсказания записаны здесь до прогона):

| # | Инъекция (файл) | Предсказано красным | Предсказано зелёным |
|---|---|---|---|
| L1 | `layer_render/factory.py`: при заданном `class_index` всё равно `rng.integers` (J1 6.2). Генератор всегда передаёт `class_index` фабрике (`layer_scene.py:267-269`) — лишний розыгрыш на каждом вызове | G2 (все 6 кейсов), G3 | G1, G1-radius (угол `[0, 0]`, кадр от потока не зависит) |
| L2 | `layer_scene.py`: знак разыгрывается до смещения (`random` ↔ `uniform`) | G2, G3 | G1, G1-radius (`lateral [0, 0]`) |
| L3 | `layer_scene.py`: `scroll_px = 0` без розыгрыша | G2, G3 | G1, G1-radius (нет тайла) |
| L4 | `layer_scene.py`: центр объекта `(w / 2 + 1, …)` | G1, G1-radius, G2, G3 | — |
| L5 | `layer_scene.py` `_label_angle`: без `layer.angle_deg` | G2, G3 по полям метки (кадр зелёный) | G1, G1-radius (`angle_layer: null`) |
| L6 | `layer_scene.py`: `self._effects = []` | G2, G3 | G1, G1-radius (`augment` нет) |
| L7 | `layer_render/crop.py` `resize_square`: всегда `INTER_LINEAR` | G2, G3 (вырез > 64 → уменьшение) | G1, G1-radius (вырез 96 = выход 96, ресайза нет) |
| L8 | `layer_scene.py` `_alpha_radius`: `min` вместо `max` по сторонам bbox | G1-radius (сторона `round(30) + 36 = 66`, кадр иной) | G1 (`size_mode: fixed`); G2, G3 — не предсказываю: bbox альфы круга почти квадратный, `min` и `max` могут совпасть |

**Наблюдено** (2026-10-14, литерал `59558a638`, worktree `-inj`, `junior` по таблице выше, база 20 passed; откат после каждой строки, итог `git status` пуст):

| # | Красных | Наблюдено | Совпало |
|---|---|---|---|
| L1 | 7 | G2 6/6, G3 | да |
| L2 | 7 | G2 6/6, G3 | да |
| L3 | 7 | G2 6/6, G3 | да |
| L4 | 17 | G1 6/6, G1-radius 6/6, G2 4/6 (`rand-0`, `rand-3` зелёные), G3 | да (G2 частично) |
| L5 | 7 | G2 6/6, G3 | да |
| L6 | 7 | G2 6/6, G3 (ruff-хук заодно снял ставший неиспользуемым импорт — на кадр не влияет) | да |
| L7 | 7 | G2 6/6, G3 | да |
| L8 | 7 | G1-radius 6/6, G2 `rand-1`; G1 и G3 зелёные | да (G2 `rand-1` — сверх предсказания) |

Выживших 0 из 8. Литерал не усиливался.
