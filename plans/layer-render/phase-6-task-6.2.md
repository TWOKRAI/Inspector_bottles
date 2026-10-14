# Task 6.2 — `LayerSceneGenerator`: сэмплы обучения любого продукта из слоёв сима (бывш. 2.2)

Фаза: [phase-6-train.md](phase-6-train.md) · план: [plan.md](plan.md) (строка Task 6.2) · эталоны: [goldens.md](goldens.md) ·
прежняя спека: [phase-2.md](phase-2.md) «Task 2.2 — SimCropGenerator» (написана до 2.4a/2.4b/2.5; расхождения сведены ниже)

- **Статус:** [DONE 2026-10-14] (после 2.5, 6.1 — DONE; литерал m4 — `d0cdc9503`) · **Level:** Senior+ · **Assignee:** teamlead <!-- lint-language: allow -->
- **Gate:** RED тестера → GREEN; инъекции лида записаны; `reviewer` APPROVED по SHA; рамка-grep — 0

TASK: 6.2 — генератор обучающих сэмплов `LayerSceneGenerator` в `dataset_gen` поверх `layer_render`; продуктовые данные — секция `train` пресета слоёв
PLAN: plans/layer-render/plan.md (Ф6, Task 6.2; статус в plan.md правит лид)
ROLE: teamlead
CHAIN: tester(слепая приёмка RED в worktree на коммите брифа, до кода) -> you(GREEN + hazard-тесты) -> lead(инъекции) -> reviewer(по SHA)
Module contract: public-api-change (`layer_render`: `ObjectFactory.render(..., class_index=)`, `ObjectFactory.catalog`, поле `ScenePreset.train`) +
new-lite (`dataset_gen.core.layer_scene`: докстринг модуля несёт `Purpose:`, `Public API:`, `Stability: lite`; `Pre:`/`Post:` — у
конструктора и `generate_sample`; роль контракт-тестов играет приёмка тестера `test_acceptance_6_2_*`)

## Посылка (код на `d0cdc9503`; не перемерять)

1. `Services/layer_render/factory.py`: `ObjectFactory.render(rng, *, force_defect=False, label="")` → `RenderedObject(rgba (read-only),
   class_name, angle_deg, defect, layer_params)`. Порядок `rng` в `_resolve_bottom_layers` (`:144-179`): `integers` (класс) → `uniform`
   (угол) → `get_sprite` → `rng.spawn(len(layers))`. `make()` с паспортом — у наследника `line_sim/core/factory.py:46`, генератору не нужен.
2. Канва слоёв всегда чётная (`layers.py:247`, `canvas_size`): спрайт 41 и 42 дают `obj.rgba` 42×42 при 0°, 59×59 при 37° (воспроизведено лидом).
3. Кадр — `layer_render.scene.render_scene`; `SceneCompositor` делегирует ей побайтно (2.5, A8). Вырез — `layer_render.crop` (6.1).
4. `layer_render` не импортирует `dataset_gen`/`line_sim`; `dataset_gen` не импортирует `line_sim` (`.sentrux/rules.toml:157-177`).
5. `_resolve_symmetries` — `dataset_gen/core/engine.py:193-214`. `apply_defect_override` — в `line_sim/core/preset.py:42`, отсюда недоступен.

## Расхождения со старой 2.2 и тихие решения (лид подтверждает)

| Старая 2.2 | Здесь | Почему |
|---|---|---|
| `line_sim/core/sim_crop.py`, `SimCropGenerator` | `dataset_gen/core/layer_scene.py`, `LayerSceneGenerator` | фабрика, сцена, вырез теперь в `layer_render` |
| `line_sim.ObjectFactory.make(..., class_index)` | `layer_render.ObjectFactory.render(..., class_index)`; `make` не меняется | паспорт — понятие ленты |
| отдельный YAML `SimCropConfig` | секция `train:` того же пресета: в `ScenePreset` — `train: dict \| None`, схема — `dataset_gen.TrainSection` | `extra="forbid"`: без поля ключ ломает загрузку пресета симом |
| `composite` + `apply_photometric` по окну | `render_scene(фон, [объект], effects, rng)` | одна функция кадра (2.5) |
| `drop_partial / pad_if_oob / pad_color_bgr` | нет; вырез внутри окна по построению | режим края не срабатывает никогда |
| `center_jitter_px`, `radius_jitter_frac` как `[lo, hi]` | скаляры: `U(−j, j)` по оси, радиус `× (1 + U(−f, f))` | ошибка детектора симметрична; у `[lo, hi]` не было смысла знака |
| `apply_defect_override` | `preset.model_copy(update={"defect_probability": p})` | `p` проверен `TrainSection`; `line_sim` недоступен |
| — | геометрия `augment` (`rotation`, `shift`, `scale`, `contact_shadow`) игнорируется | геометрию дают слои пресета; у `rotation/shift/scale` дефолт `enabled=True` (`config.py:35,42,49`) — молча включились бы |
| — | `to_yaml` не пересчитывает пути `tile:` внутри `train` | поле непрозрачно для `layer_render`; → «Открыто» + follow-up |

**Совместимость с 3.1** (`schema_version`, PENDING): 6.2 `schema_version` не вводит; `train` необязателен, `to_dict()` при
`train is None` ключа не пишет — `to_dict`/`to_yaml` пресетов без `train` побайтно прежние; 3.1 берёт `train` в схему v1 как есть.

## DESIGN (решено; набираешь, не выводишь)

**A. `layer_render/factory.py`.** `render(rng, *, force_defect=False, label="", class_index: int | None = None)`;
`_resolve_bottom_layers(rng, class_index=None)`. `None` — путь байт в байт прежний. Задан: `rng.integers` не зовётся, дальше тот же
порядок. Проверки до любого розыгрыша, тексты **без входного значения**: каталога нет → `ValueError("class_index: пресет без
catalog_dir")`; не `int` (`bool` — нет, `np.integer` — да) → `ValueError("class_index: ожидался int")`; вне диапазона →
`ValueError(f"class_index вне [0, num_classes={n})")`. `nominal_layers` не меняется. Свойство `catalog -> SpriteCatalog | None` (тот же объект).

**B. `layer_render/preset.py`.** Поле `train: dict[str, Any] | None = None`, содержимое не проверяется; `to_dict()` удаляет ключ
`train`, если `None`; `from_dict(p.to_dict()) == p` держится. В докстринге поля: пути `tile:` внутри `to_yaml` не пересчитывает.

**C. `dataset_gen/core/symmetry.py`.** `resolve_symmetries(catalog: SpriteCatalog, sym_cfg: SymmetryConfig) -> dict[int, SymmetryType]`
— тело `engine.py:196-214` дословно; `DatasetEngine._resolve_symmetries` возвращает `resolve_symmetries(self._catalog, self.config.symmetry)`.

**D. `dataset_gen/core/layer_scene.py` — схема `train` (Pydantic v2, `frozen=True, extra="forbid"` у трёх моделей):**

```python
class TrainCrop(BaseModel):  # дефолты = CenterCropRegisters, литералами (Plugins отсюда не импортируются)
    size_mode: Literal["radius", "fixed"] = "fixed"
    side_px: int = Field(200, ge=2, le=4000); radius_scale: float = Field(1.0, gt=0); margin_px: int = Field(10, ge=0)
    output_size: int = Field(128, ge=1)          # 0 у регистра = «без ресайза»; здесь нет: Protocol ждёт один размер
    center_jitter_px: float = Field(0.0, ge=0, le=500); radius_jitter_frac: float = Field(0.0, ge=0, lt=1)
class TrainLabel(BaseModel):
    angle_layer: str | None = "auto"             # "auto" | None | имя слоя class:// (DESIGN E)
class TrainSection(BaseModel):
    label: TrainLabel = TrainLabel(); symmetry: SymmetryConfig = SymmetryConfig()
    background_layers: list[dict] = [{"solid": [0, 0, 0]}]     # схема 1.1
    lateral_offset_px: tuple[float, float] = (0.0, 0.0)
    crop: TrainCrop = TrainCrop(); augment: AugmentConfig | None = None   # None — без фотометрии
    defect_probability: float = Field(0.0, ge=0, le=1)         # перекрывает preset.defect_probability

    @field_validator("lateral_offset_px")
    @classmethod
    def _lateral(cls, v):
        lo, hi = v
        if not (0.0 <= lo <= hi <= 2000.0):
            raise ValueError("train.lateral_offset_px: нужно 0 <= lo <= hi <= 2000")
        return v

    @model_validator(mode="before")
    @classmethod
    def _no_unknown_keys(cls, data):  # у SymmetryConfig/AugmentConfig нет extra="forbid": опечатка молча дала бы дефолт
        if not isinstance(data, dict):
            return data
        blocks = [("symmetry", data.get("symmetry"), SymmetryConfig), ("augment", data.get("augment"), AugmentConfig)]
        aug = data.get("augment")
        if isinstance(aug, dict):
            blocks += [(f"augment.{k}", v, AugmentConfig.model_fields[k].annotation)
                       for k, v in aug.items() if k in AugmentConfig.model_fields]
        for path, block, model in blocks:
            if isinstance(block, dict) and set(block) - set(model.model_fields):
                raise ValueError(f"train.{path}: неизвестный ключ (допустимы: {sorted(model.model_fields)})")
        return data
```

**E. `LayerSceneGenerator(preset: ScenePreset, *, seed: int | None = None)`; `from_yaml(path, *, seed=None)`.**
`train = TrainSection.model_validate(preset.train or {})`; `preset.catalog_dir is None` → `ValueError("LayerSceneGenerator: пресет без
catalog_dir — генератору обучения нужен каталог классов")`. **`label.angle_layer`:** `"auto"` разрешается первым → слой `class://`,
если он есть, иначе `None`; `None` → угол объекта; иначе имя обязано быть слоем `class://` пресета, иначе
`ValueError(f"label.angle_layer: нет такого слоя class:// (слои class:// пресета: {names})")`. Фабрика —
`ObjectFactory(preset.model_copy(update={"defect_probability": train.defect_probability}))` из `layer_render`. Фон —
`background_layers_from_config(train.background_layers, loader)`, `loader(p)` = `imread_unicode(preset.resolve_path(p),
cv2.IMREAD_UNCHANGED)` → `BGR2RGB`/`BGRA2RGBA`; нечитаемый файл — исключение наружу, не `None` (обучение без фона — тихая порча).
Симметрии — `resolve_symmetries(factory.catalog, train.symmetry)` один раз; `self._rng = default_rng(seed)`. Свойства `num_classes`,
`class_names`, `symmetry_map` — как у `DatasetEngine`. `class_registry` не реализуется (6.3).

**F. `generate_sample(class_index=None, rng=None)` — порядок розыгрышей = контракт seed:**
1. `rng = rng if rng is not None else self._rng`; `ci = class_index` или `int(rng.integers(num_classes))`.
2. `obj = factory.render(rng, class_index=ci, label="train")`.
3. `lat = rng.uniform(lo, hi)`, затем `sign = 1.0 if rng.random() < 0.5 else -1.0` — **всегда** два розыгрыша.
4. bbox альфы `obj.rgba[..., 3] > 0`, `r = max(bbox_w, bbox_h) / 2.0`; `side_max` = `side_px` или `side_from_radius(r·(1+f), radius_scale, margin_px)`.
5. `half = ceil(side_max/2) + ceil(lat_hi) + ceil(j) + 2; half += half % 2; W = 2·half` — `W` кратно 4, `W/2` чётно.
6. Есть хотя бы один `ScrollingTile` → `scroll_px = int(rng.integers(0, max ширин тайлов))`; иначе розыгрыша нет, `0`.
7. `frame = render_scene(SceneBackground(layers, (W, W), center_y=W/2, scroll_px=scroll_px), [PlacedObject(obj.rgba, (W/2, W/2 + sign·lat))], effects, rng)`,
   `effects = augment_config_to_effects(train.augment)` или `()`; центр объекта — float, без своего округления.
8. **Всегда** три розыгрыша: `dx = rng.uniform(−j, j)`, `dy = rng.uniform(−j, j)`, `k = rng.uniform(−f, f)`. `side` = `side_px` или
   `side_from_radius(r·(1+k), ...)`; `cx = int(round(W/2 + dx))`, `cy = int(round(W/2 + sign·lat + dy))` (как `center_crop/plugin.py:128`).
9. `crop = square_crop(frame, cx, cy, side, "drop")`; `None` → `RuntimeError` (нарушен инвариант п. 5); `out = resize_square(crop, output_size)`.
10. `angle = (obj.angle_deg + L.angle_deg + obj.layer_params.get(L.name, {}).get("angle_deg", 0.0)) % 360` для слоя метки `L`;
    без слоя — `obj.angle_deg % 360`. `encode_angle(angle, symmetry[ci])` → `SampleLabel(..., class_path=entry.qualified_name, symmetry=...)`.

Слова продукта в коде генератора запрещены: только «объект», «слой», «класс».

## FILES (полный список; нужен другой файл — стоп, спроси лида)

1. `Services/layer_render/factory.py` — DESIGN A
2. `Services/layer_render/preset.py` — DESIGN B
3. `Services/dataset_gen/core/symmetry.py` — DESIGN C
4. `Services/dataset_gen/core/engine.py` — только `_resolve_symmetries` (`:193-214`) делегирует
5. `Services/dataset_gen/core/layer_scene.py` (новый) — DESIGN D–F
6. `Services/dataset_gen/__init__.py` — экспорт `LayerSceneGenerator`, `TrainSection`
- тесты тестера: `Services/layer_render/tests/test_acceptance_6_2_factory_train.py`, `Services/dataset_gen/tests/test_acceptance_6_2_layer_scene.py`;
  hazard-тесты автора: `Services/dataset_gen/tests/test_hazards_6_2_layer_scene.py` — минимум: `lateral_offset_px [5, 1]` → `ValidationError`;
  `radius_jitter_frac 1.0` → `ValidationError`; нечитаемый `tile:` → исключение при создании; без `ScrollingTile` фаза не тратит `rng`
  (состояние `rng` после сэмпла равно реплею F без п. 6); опечатка в `augment.noise` → `ValidationError` со списком допустимых.
- документация — отдельный шаг `docs-writer` → `reviewer`(express) после APPROVED: README и STATUS `dataset_gen` и `layer_render`

## REDS (тестер, на коммите брифа; каждый красный до кода)

1. `test_acceptance_6_2_factory_train.py::test_render_class_index` — пресет `angle_range_deg: [0, 360]`; `render(default_rng(5),
   class_index=1).class_name == class_names[1]`, `.angle_deg == default_rng(5).uniform(0, 360)`; `class_index` `-1` и `num_classes` →
   `ValueError`, текст содержит `class_index` и `num_classes=3`; `True` → `ValueError` с `class_index`; без `catalog_dir` → текст с `catalog_dir`.
2. `…::test_scene_preset_train_section` — `from_dict({..., "train": {"crop": {"side_px": 96}}}).train == {"crop": {"side_px": 96}}`;
   без `train`: `"train" not in p.to_dict()`, в `to_yaml` нет строки `train`; `from_dict(p.to_dict()) == p` в обоих случаях.
3. `test_acceptance_6_2_layer_scene.py::test_protocol_shapes_symmetry` — `isinstance(gen, SampleGenerator)`; `class_names == ["a", "b", "c"]`;
   кадр `(64, 64, 3)` `uint8`; `train.symmetry: {overrides: {a: "180"}, auto_detect: false}` → `symmetry_map == {"a": "180", "b": "none",
   "c": "none"}`, у сэмпла `ci=0` `label.symmetry == "180"`.
4. `…::test_two_products_zero_code` — (а) и (б) из ACCEPTANCE 2 одним `from_yaml`; у (б) `angle_range_deg: [123.5, 123.5]` → `label.angle_deg == 123.5`.
5. `…::test_identical_to_scene_crop` — ACCEPTANCE 3, параметры: `obj_even` / `obj_odd` × окно `small` / `1440x1080`, плюс `oracle_order`.
6. `…::test_angle_label_and_iou[static|augmented]` — `47.0` / `52.0`; IoU ≥ `0.98` против `rotate_expand(спрайт, 47 | 52)`.
7. `…::test_same_seed_same_bytes` — два генератора, `rng=default_rng(3)` каждому → `tobytes()` кадров и `to_dict()` меток равны.
8. `…::test_all_four_classes_in_100` — `{class_index по 100 сэмплам, rng=default_rng(0)} == {0, 1, 2, 3}`.
9. `…::test_resolve_symmetries_module_level` — `from Services.dataset_gen.core.symmetry import resolve_symmetries`; `overrides: {"a": "180"}`,
   `auto_detect: false` → `{0: "180", 1: "none", 2: "none"}`; по именам == `DatasetEngine(cfg).symmetry_map` на том же каталоге.
10. `…::test_errors_defect_and_frame_words` — без `catalog_dir` → `ValueError` с `catalog_dir`; `label.angle_layer: "nope"` → `ValueError`,
    текст содержит `label.angle_layer` и список слоёв `class://` пресета; пресет `defect_probability: 1.0` без `train` → кадр равен эталону
    по схеме ACCEPTANCE 3, но с дефолтами `train` (фон чёрный, `side_px 200`, `output_size 128`) и фабрикой с `defect_probability 0`;
    `re.search(r"letter|букв|disk|диск", текст layer_scene.py, re.I) is None` — основная проверка рамки.

## ACCEPTANCE (слепой tester: синтетика numpy → PNG в `tmp_path`; `data/` вне git и не читается)

1. **Протокол.** `isinstance(gen, SampleGenerator)`; `num_classes`/`class_names` = каталог пресета.
2. **Два продукта, ноль кода.** (а) круг-подложка RGBA (статический слой файлом) + слой `class://`, каталог 3 класса, `size_mode: radius`;
   (б) 2 класса прямоугольных RGBA 60×30, без `class://`, `label.angle_layer: null`, `size_mode: fixed`, `side_px: 96`. Для каждого сэмпла
   обоих: кадр `(output_size, output_size, 3)` `uint8`; `0 <= class_index < num_classes`; `0 <= angle_deg < 360`; при `angle_valid`
   `abs(sin² + cos² − 1) < 1e-9`. (б): метка = угол объекта (литерал REDS 4).
3. **«Идентично там и там».** `train`: фон `[{solid: [20, 40, 60]}]`, `lateral [0, 0]`, джиттеры `0`, `augment` нет. Эталон:
   `obj = ObjectFactory(preset.model_copy(update={"defect_probability": 0.0})).render(default_rng(s), class_index=ci)` (из `layer_render`;
   при заданном `class_index` первым `rng` тратит `render`); предусловие `obj.rgba.shape[0] % 2` — `1` для `angle_range_deg [37, 37]`
   (59×59), `0` для `[0, 0]` (42×42). (а) `small`: `W` кратно 4 и достаточно для выреза, объект в `(W/2, W/2)`, `square_crop(frame, W//2, W//2, side, "drop")`;
   (б) `1440x1080`: `SceneBackground(..., (1440, 1080), center_y=540.0)`, объект в `(720.0, 540.0)`, `square_crop(frame, 720, 540, side, "drop")` —
   независимость от размера окна. `side` — `side_px` или `side_from_radius(max(bbox)/2, scale, margin)`; `resize_square(..., output_size)` ==
   `generate_sample(class_index=ci, rng=default_rng(s))[0]` побайтно. **`oracle_order`:** `lateral_offset_px [7.3, 7.3]`, `center_jitter_px 3.0`,
   `size_mode fixed`, `angle_range_deg [37, 37]`, `augment` с одним эффектом `noise: {enabled: true, prob: 1.0}` и явным `enabled: false` у
   `brightness_contrast`, `gaussian_blur`, `color_temperature` (их дефолт — включены); эталон проигрывает F явными вызовами numpy:
   `render` → `uniform(7.3, 7.3)` → `random() < 0.5` → `W` по F.5 → `render_scene(..., augment_config_to_effects(cfg), rng)` → `uniform(−3, 3)` ×2 →
   `uniform(−0, 0)` → `square_crop`/`resize_square`; seeds `0..7`, тест утверждает, что встретились оба знака
   (на GREEN один знак на всех seeds — сменить seeds, утверждение не ослаблять).
   `SceneCompositor` не зовётся: `dataset_gen` не импортирует `line_sim` (`rules.toml:175`); 2.5 доказала, что он делегирует `render_scene` побайтно.
4. **Угол.** Спрайт ≥ 64 px, `angle_range_deg [37, 37]`, слой `class://` с `angle_deg: 10`, `label.angle_layer` — он. `static` → метка `47.0`;
   `mode: augmented` с `augment.angle_deg [5, 5]` → `52.0`. Маски `alpha > 127` у `obj.rgba` и `rotate_expand(спрайт, 47 | 52)` по центру общего холста; IoU ≥ 0.98.
5. **Seed.** Тот же seed → побайтно тот же сэмпл; 100 сэмплов на 4 классах — все 4.
6. **Эталоны без правки** (зелёные до и после): `Plugins/sim/layer_preview/tests/test_hazards_1_3h_layout.py:40-44`,
   `Services/line_sim/tests/test_acceptance_lateral_offset.py:355`, `Plugins/sim/scene_source/tests/test_acceptance_lateral_offset_plugin.py:492-493`,
   `Services/layer_render/tests/test_acceptance_2_4b_factory_preview.py` (A3, `_A3` `:145`), `test_acceptance_2_5_render_scene.py` (A7),
   `Services/dataset_gen/tests/test_engine.py`, `test_symmetry.py`, `test_augment_equivalence.py`, **m4** — `Services/dataset_gen/tests/test_engine_golden_m4.py` (`d0cdc9503`).
7. **Рамка и граница.** `rg -in "letter|букв|disk|диск" Services/dataset_gen/core/layer_scene.py` — exit 1, 0 совпадений (не `rg -E`: в ripgrep это `--encoding`, exit 2; не `grep -i`: Git Bash не сворачивает
   регистр кириллицы); чистый `python -c "import Services.layer_render"` — нет `Services.dataset_gen*`/`Services.line_sim*` в `sys.modules`; `sentrux check .` — чисто.

## TESTS (через гейт; main `.venv`, `PYTHONPATH` = корень worktree; никакого `uv sync`)

```bash
G="$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh"
PY=D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python
bash "$G" light inspector-bottles-5d env PYTHONPATH="$PWD" $PY -m pytest -q --tb=short Services/layer_render   # база: 1613 passed
bash "$G" light inspector-bottles-5d env PYTHONPATH="$PWD" $PY -m pytest -q --tb=short Services/dataset_gen    # база: 206 passed, 1 skipped
bash "$G" heavy inspector-bottles-5d env PYTHONPATH="$PWD" $PY -m pytest -q --tb=short Services/line_sim Plugins/sim  # база — лид (ориентир 6.5: 1382 passed, 4 skipped)
$PY -m ruff check -q Services/layer_render Services/dataset_gen
```

База — `d0cdc9503`; после GREEN — база + новые тесты, падений 0. Код 75 — пропуск гейтом («NO WINDOW»), не красный прогон.
Bash, запущенный из Python на Windows, стартует WSL, не Git Bash — гейт звать из Bash-инструмента.

## OUT OF SCOPE

- CLI экспорта, пресет первого продукта, смоук `ml_train`, `class_registry` — 6.3; эффекты сцены и `schema_version` — 3.1.
- Правки `Services/ml_train`; сведение `DatasetEngine` к пресету слоёв — 6.5 layer-render; торч-адаптер; детектор некруглых объектов.
- `Services/line_sim` (кроме прогона тестов), `make()`, `scene_source`, `apps/line_sim`.
- **Запрещённые пути для всех агентов:** `Services/device_hub/`, `Services/robot_comm/`, `Plugins/sim/robot_host/`,
  `plans/robot-protocol-v2/`, `apps/line_sim/pipeline.yaml`, `scripts/machine_gate*`, `.claude/settings.json`, `Services/ml_train`.

## TRAPS

- **Банковское округление `composite`** (`compose.py:139`, `int(round(cx − sw/2))`). Важна чётность стороны **`obj.rgba` (после канвы и
  поворота)**, не исходного спрайта: канва слоёв всегда чётная, нечётной сторону делает только поворот. При нечётной стороне позиция зависит
  от чётности центра; равенство держится, если центр объекта — ровно `(W/2, W/2 + sign·lat)` float без своего `x0`, а `W/2` чётно (F.5).
- **`class_index=None` — байт в байт прежний.** Не переставлять `integers`/`uniform`; эталоны A3 2.4b и `1_3h_layout` ловят перестановку.
- **`obj.rgba` read-only** — не писать, не снимать флаг. **`to_dict` с `train: None`** — ключ не писать (YAML сима, литералы `pult_web`/`scene_source`).
- **`layer_render` не импортирует `dataset_gen`** — `TrainSection` в `dataset_gen`, в `ScenePreset` только `dict`.
- **Тексты ошибок без входного значения:** имя поля + допустимое множество из пресета.
- **Фотометрия на окне `W×W`, не на кадре 1440×1080** — блик/виньетка зависят от размера; известное расхождение, не чинить.
- **Не звать `spawner.tick()` и `SceneCompositor`** — нужен один объект, не лента.

## Цели break-injection

Род 1 (лид, после GREEN; по одной на свойство): `class_index` → снова `rng.integers` · `sign` без розыгрыша · `W` без `half % 2` ·
центр объекта `int(round(W/2 + sign·lat))` · слой метки без `layer_params` · `resolve_symmetries` без `meta.symmetry` ·
`to_dict` пишет `train: None` · `effects` до объекта.
Род 2 («нуль/тотал», другой исполнитель): `symmetry_map` → `{}` · фабрика без перекрытия `defect_probability` · `loader` возвращает `None` ·
`W = side_max` без полей.

## Открыто (известно, не чинится в 6.2)

- `to_yaml` не пересчитывает пути `tile:` в `train`: сохранение пресета в другой каталог (редактор Ф5) ломает относительные пути — follow-up.
- Геометрия `augment` молча игнорируется (докстринг `TrainSection.augment`); ошибку конфигурации пользователь не увидит.
- ~~`preset.commit` пишет клиентский `train` без ограды~~ — закрыто ревью ит.1/ит.2: `confine_preset_paths` огораживает
  `train.background_layers[*].tile` в форме `to_dict()` (`13582a69f`, `23f08eeab`). Новые ключи с путями в `train` — добавлять в `_train_tile_paths` вручную.
- `train` — изменяемый `dict` внутри frozen `ScenePreset`; `tuple` внутри `train`, заданный из Python, ломает `from_dict(to_dict()) == p`.
- `train` проверяет только генератор — сим и редактор ошибку в секции не увидят.
- Эталона «там» через сам `SceneCompositor` нет (граница слоёв); опора — делегирование, доказанное 2.5 A8.
- `angle_layer` — только слой `class://`; обобщение на любые слои — возможный вопрос владельцу позже.
- Дефолты `TrainCrop` — литералы `CenterCropRegisters` без теста равенства (`dataset_gen` не импортирует `Plugins`).
- Предел стороны выреза 4000 px проверяется на сэмпле, не в конструкторе: длинный экспорт 6.3 может упасть посреди прогона.
- `background_layers_from_config` (`background.py:62`) пишет в ошибку `repr` плохого элемента (эхо ввода) — до 6.2, вне задачи.
- `DatasetEngine` молча игнорирует override симметрии для неизвестного класса; генератор 6.2 отказывает — поведение расходится.
- Байтового литерала на выход `LayerSceneGenerator` нет (seed-контракт держат оракулы-реплеи через `factory.render` и независимый оракул угла) — снять в 6.3.
- Потокобезопасность генератора не обещана; тест двух потоков — smoke, не доказательство.

## Вопросы владельцу

1. **Эффекты сцены 3.1 в обучении** — применять вместе с `train.augment`? Рекомендация: да, «эффекты сцены → `train.augment`»; 6.2 не блокирует.
2. **Фон окна после 3.1.** Рекомендация: `train.background_layers`, если задан, иначе фон пресета, иначе чёрный — записать в 3.1.
3. **Брак в обучающих сэмплах.** `train.defect_probability` по умолчанию `0.0`. Рекомендация: оставить — классификатор учит класс и угол.

HANDOFF IN: m4 — `d0cdc9503` (строку в `goldens.md` добавляет лид); базовые числа TESTS — лид, `line_sim + Plugins/sim` после окна heavy.

## Предсказания лида для матрицы инъекций (записаны до прогона, 2026-10-14 ~10:15)

Наборы: B = слепой tester (layer_render 22 + dataset_gen 44), H = hazards автора, M4 = test_engine_golden_m4.py, G = прежние эталоны
(test_hazards_1_3h_layout, A3 2.4b, A7 2.5, test_augment_equivalence).

### Род 1 (цели брифа)
| # | Инъекция | Предсказано красным | Предсказано зелёным |
|---|---|---|---|
| J1 | factory.render: при заданном class_index всё равно `rng.integers` | B: test_render_class_index (угол ≠ оракулу), test_identical_to_scene_crop_oracle_order (оба), angle/same-seed — нет | G, M4 |
| J2 | sign без розыгрыша (всегда +1, без rng.random) | B: oracle_order (оба) | test_identical_to_scene_crop (lat 0) — зелёный |
| J3 | W без `half += half % 2` | B: test_identical_to_scene_crop[obj_odd-small-*] (если W/2 оказывается нечётным), oracle_order | obj_even — зелёный |
| J4 | центр объекта `int(round(W/2 + sign·lat))` | B: oracle_order (знак −, сторона 59) | identical (lat 0) — зелёный |
| J5 | метка без layer_params (дельта augmented-слоя не учтена) | B: test_angle_label_47_and_iou[augmented] (52 → 47) | [static] — зелёный |
| J6 | resolve_symmetries без meta.symmetry | test_metadata.py:110-135 (DatasetEngine), B: test_resolve_symmetries_priority_override_meta_detector | M4 (в конфиге meta нет — зелёный) |
| J7 | to_dict пишет `train: None` | A: test_scene_preset_without_train_key_set_and_yaml_unchanged, test_scene_preset_train_section | — |
| J8 | effects до объекта (render_scene с эффектами на фоне, объект потом) | B: oracle_order (оба), H фотометрии если есть | identical (augment нет) — зелёный |

### Род 2 (придумал не автор критериев; исполнитель матрицы может добавить своих 2–4 и предсказать сам)
| # | Инъекция | Предсказано красным |
|---|---|---|
| K1 | symmetry_map → {} | B: test_symmetry_overrides_map_and_label, test_protocol_and_shapes (если проверяет map) |
| K2 | фабрика без override брака (preset как есть) | B: test_train_defect_probability_overrides_preset, test_errors_defect_and_frame_words |
| K3 | loader возвращает None вместо исключения | H: unreadable tile |
| K4 | W = side_max без запасов | B: oracle_order (вырез вылетает → RuntimeError), H окна |

Любое расхождение «предсказано / наблюдено» = находка (в тест или в моё понимание).
