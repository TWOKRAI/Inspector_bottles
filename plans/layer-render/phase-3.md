# Фаза 3 — полный вынос в `Services/layer_render` + список эффектов

Родитель: [plan.md](plan.md). Итог фазы: примитивы композиции, слои объекта и фотометрия живут в одном пакете;
`dataset_gen` и `line_sim` зовут одно и то же; фотометрия — упорядоченный список эффектов вместо зашитого порядка.
Внешнее поведение не меняется ни на байт — это переезд. Дообучение (`letters-retrain`) эта фаза не блокирует.

Порядок исполнения — как в [phase-1.md](phase-1.md). Старые места импорта остаются реэкспортом (явные имена, не `*`):
ни один потребитель вне перечисленных `Files` не правится. Проверка «потребителей не задели» — греп импортов до и после,
число совпадений в отчёт.

---

### Task 3.1 — `compose.py` переезжает, `dataset_gen.core.compose` — реэкспорт

- **Статус:** [PENDING] · **Level:** Middle (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** public-api-change (`layer_render` получает `compose`; `dataset_gen.core.compose` — реэкспорт)
- **CHAIN:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**Goal:** `composite`, `rotate_expand`, `crop_to_alpha`, `fit_longest_side`, `cast_contact_shadow` определены в
`Services/layer_render/compose.py`; старый модуль — только реэкспорт.

**Files:**
1. `Services/layer_render/compose.py` (новый — тело из `Services/dataset_gen/core/compose.py`, 153 стр., без изменений)
2. `Services/dataset_gen/core/compose.py` — реэкспорт пяти имён
3. `Services/layer_render/__init__.py`, `Services/layer_render/interfaces.py`, `Services/layer_render/README.md`
- тесты: `Services/layer_render/tests/test_compose_identity.py`; `Services/dataset_gen/tests/test_compose.py` остаётся где есть

**Acceptance:**
- [ ] `Services.dataset_gen.core.compose.composite is Services.layer_render.compose.composite` — и так для всех пяти имён.
- [ ] Все золотые эталоны плана ([goldens.md](goldens.md)) — зелёные без правки литералов.
- [ ] `sentrux check .` — зелёный; `layer_render` не импортирует `dataset_gen`.

**Out of scope:** правка импортов у потребителей (`line_sim`, `ml_train`, плагины) — реэкспорт для того и есть.

---

### Task 3.2 — `LayerSpec`/`LayerAugment`/`compose_layers` переезжают, `LayeredObject` — тонкая обёртка

- **Статус:** [PENDING] (зависит от 3.1 и от слияния 2.2) · **Level:** Senior+ (Opus 5.5) · **Assignee:** tester → teamlead → инъекции лида → reviewer
- **Module contract:** public-api-change
- **CHAIN:** `teamlead`(INTERFACE) → `tester`(RED) → `teamlead`(GREEN) → `reviewer`

**Goal:** розыгрыш и композиция стека слоёв — чистая функция в `layer_render`, не знающая паспорта и `line_sim`;
`LayeredObject` остаётся публичным именем `line_sim` и собирает паспорт вокруг неё.

**Files:**
1. `Services/layer_render/layers.py` (новый) — `AUGMENT_FIELDS`, `LayerAugment`, `LayerSpec`, `canvas_size`,
   `compose_layers(layers, rng, object_angle_deg, forced_defects) -> (rgba, layer_params, active_defects)`
2. `Services/line_sim/interfaces.py` — `LayerSpec`/`LayerAugment`/`AUGMENT_FIELDS` реэкспортом; `ObjectPassport` остаётся здесь
3. `Services/line_sim/core/layered_object.py` — обёртка: проверки имён/дефектов + `compose_layers` + паспорт
4. `Services/layer_render/__init__.py`, `Services/layer_render/README.md`
- тесты: `Services/layer_render/tests/test_layers_*.py`

**DESIGN:**
- Перенос **дословный**: `rng.spawn(len(layers))` (`layered_object.py:150`), порядок `uniform` по `AUGMENT_FIELDS`
  (`:166`), `sub.random() < defect_probability` (`:158`), премультиплицированная канва и распремультипликация (`:212-228`),
  `_rotate` через `rot90` на кратных 90° (`:44-57`), `_hue_shift`. Ни одного «попутного улучшения».
- Имена и типы полей `LayerSpec` не меняются — на них стоит `pult_web` (`plugin.py:1126-1183`) и YAML пресетов.
- `layer_render` не импортирует `ObjectPassport`: проверка «нет таких defect-слоёв» и паспорт — в обёртке.

**Acceptance:**
- [ ] `test_hazards_1_3h_layout.py:40-44` (15 отпечатков), `test_acceptance_lateral_offset_plugin.py:492-493`,
      `test_acceptance_lateral_offset.py:355` — зелёные без правки литералов.
- [ ] Все тесты `Services/line_sim/tests/`, `Plugins/sim/*/tests/` — зелёные без правки.
- [ ] `Services.line_sim.interfaces.LayerSpec is Services.layer_render.layers.LayerSpec`.
- [ ] `compose_layers` с теми же входами и seed дважды — побайтно тот же RGBA; входной список слоёв не мутирован.
- [ ] `layer_render` не импортирует `Services.line_sim` (AST-тест из 1.1 расширен на `layers.py`).

**Out of scope:** эффекты слоя (4.2), новые поля слоя, перенос `ObjectFactory`/`ScenePreset`.

---

### Task 3.3 — `effects.py` + эквивалентность `apply_photometric` на 50 seed

- **Статус:** [PENDING] (зависит от 3.1) · **Level:** Senior (Opus 5.5) · **Assignee:** tester → teamlead → инъекции лида → reviewer
- **Module contract:** public-api-change
- **CHAIN:** `tester`(RED: оракул — копия старого `apply_photometric` в тесте) → `teamlead`(GREEN) → `reviewer`

**Goal:** фотометрия — упорядоченный список `EffectSpec`, исполняемый `apply_effects`; `AugmentConfig` превращается в
этот список, и `apply_photometric` становится одной строкой поверх него.

**Files:**
1. `Services/layer_render/effects.py` (новый) — функции эффектов (переезд из `dataset_gen/core/augment.py:27-173`),
   `EFFECTS: dict[str, fn]`, `EffectSpec(name, prob, params)`, `apply_effects(frame, specs, rng)`
2. `Services/dataset_gen/core/augment.py` — реэкспорт функций + `augment_config_to_effects(cfg) -> list[EffectSpec]` +
   `apply_photometric = apply_effects(frame, augment_config_to_effects(cfg), rng)`
3. `Services/layer_render/__init__.py`, `Services/layer_render/README.md` (раздел «Как добавить эффект»: функция + строка в `EFFECTS`)
- тесты: `Services/layer_render/tests/test_effects_*.py`, `Services/dataset_gen/tests/test_augment_equivalence.py`

**DESIGN:**
- Канонический порядок = нынешний (`augment.py:189-258`): `glare, shadow, occlusion, gaussian_blur, motion_blur, vignette,
  brightness_contrast, gamma, color_temperature, channel_shift, noise`, затем clip в uint8, затем `jpeg`.
- Кадр между эффектами — **float32**, clip один раз перед `jpeg` (как сейчас); `jpeg` работает на uint8 — это свойство
  эффекта в реестре, не особый случай в цикле.
- Розыгрыши: на каждый **включённый** эффект — `rng.random() < prob`, затем его параметры в нынешнем порядке.
  Выключенный эффект в список не попадает → ноль розыгрышей. Пустой список → копия кадра, ноль розыгрышей.
- `contact_shadow`, `rotation`, `scale`, `shift` — геометрия движка, не фотометрия: в список не входят.
- Старое тело `apply_photometric` копируется в тест как оракул **до** замены; затем удаляется из кода.

**Acceptance:**
- [ ] Эквивалентность: старый `apply_photometric` (оракул) и новый на 50 seed × 3 конфига (все эффекты `prob 1.0`;
      дефолтный `AugmentConfig`; все выключены) × кадр 64×48 — побайтно равные кадры **и** равное
      `rng.bit_generator.state` после вызова.
- [ ] `apply_effects(frame, [], rng)` — состояние rng не изменилось, кадр равен входу.
- [ ] `test_augment.py`, `test_engine.py`, `test_export_preview.py` — зелёные без правки.
- [ ] Неизвестное имя эффекта в `EffectSpec` → `ValueError` со списком известных имён.

**Out of scope:** новые эффекты, эффекты в симе (Фаза 4), torch-аугментации `ml_train`.

**TRAPS:** `noise` берёт `rng.standard_normal(x.shape, dtype=np.float32)` — смена dtype или формы ломает поток;
`occlusion` тянет `rng.integers` для числа прямоугольников, а внутри цикла — по 6 вызовов rng на прямоугольник (`augment.py:209-213`, цвет — один вызов `size=3`).
