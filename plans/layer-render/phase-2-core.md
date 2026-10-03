# Фаза 2 (новая нарезка) — ядро сервиса `Services/layer_render`

Родитель: [plan.md](plan.md), архитектура — [cto-verdict-2026-10-01.md](cto-verdict-2026-10-01.md). Старый
[phase-3.md](phase-3.md) — прежняя нарезка (бывш. 3.1 = 2.1, 3.3 = 2.2, 3.2 = 2.3), тексты переиспользованы.

Итог фазы: примитивы композиции, эффекты, слои, пресет, фабрика, каталог и превью живут в `layer_render`; одна
функция кадра `render_scene`. Это переезд: внешнее поведение не меняется ни на байт. Старые места импорта остаются
реэкспортом (явные имена, не `*`); ни один потребитель вне `Files` не правится.

---

### Task 2.1 — `compose.py` + `io.py` переезжают, старые модули — реэкспорт (бывш. 3.1)

- **Статус:** [DONE 2026-10-02 — `c9d56b11`] волна 2 · **Level:** Middle (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** public-api-change (`layer_render` получает `compose`, `io`; `dataset_gen.core.compose` и
  `imread_unicode`/`imwrite_unicode` в `dataset_gen.core.catalog` — реэкспорт)
- **CHAIN:** `tester`(RED, worktree до кода) → `developer`(GREEN) → инъекции лида → `reviewer`
- **Dependencies:** Ф1 (1.1)
- **Gate:** RED тестера → GREEN; инъекции записаны; `reviewer` APPROVED по SHA; grep рамки — 0

**Goal:** `composite`, `rotate_expand`, `crop_to_alpha`, `fit_longest_side`, `cast_contact_shadow` определены в
`Services/layer_render/compose.py`, `imread_unicode`/`imwrite_unicode` — в `Services/layer_render/io.py`; старые
места — только реэкспорт. Попутно закрыть ниты ревью 1.1 в `background.py`/README.

**Files:**
1. `Services/layer_render/compose.py` (новый) — тело `Services/dataset_gen/core/compose.py` без изменений логики
2. `Services/dataset_gen/core/compose.py` — реэкспорт пяти имён (явный список)
3. `Services/layer_render/io.py` (новый) — `imread_unicode`/`imwrite_unicode`, тело из `dataset_gen/core/catalog.py` без изменений
4. `Services/dataset_gen/core/catalog.py` — импорт двух функций из `layer_render.io` (имена остаются доступны из `catalog`)
5. `Services/layer_render/__init__.py`, `README.md` (таблица Public API), `STATUS.md`
6. `Services/layer_render/background.py` — ниты ревью 1.1: дубль проверки `solid` в `_validate_item` и `SolidFill.__post_init__`
   (оставить одну), лишние `tuple(...)`/`first.copy()` — **только если** тесты алиасинга 1.1 остаются зелёными (ревью 1.1 ит.1
   нашло алиасинг тайлов именно здесь — копию, которая его закрывает, не трогать); README — «цена ∝ min(th, высота кадра)»,
   read-only копия в таблице Public API
- тесты тестера: `Services/layer_render/tests/test_acceptance_2_1_compose_io.py`; старые тесты compose/catalog в `dataset_gen` остаются где есть

**Acceptance:**
- [ ] A1. Для каждого из пяти имён: `Services.dataset_gen.core.compose.<name> is Services.layer_render.compose.<name>`;
      `<name>.__module__ == "Services.layer_render.compose"`. Для `imread_unicode`/`imwrite_unicode`:
      `Services.dataset_gen.core.catalog.<f> is Services.layer_render.io.<f>`, `__module__ == "Services.layer_render.io"`.
- [ ] A2. В `Services/dataset_gen/core/compose.py` нет ни одного `def`/`class` (AST) — только реэкспорт.
- [ ] A3. Ни один модуль `Services/layer_render/**` (кроме `tests/`) не импортирует `Services.dataset_gen`, `Services.line_sim`,
      `Services.ml_train` (AST по всем `.py`, включая `import x` и `from x import y`).
- [ ] A4. `imwrite_unicode` → `imread_unicode` на пути с не-ASCII символами (кириллица) возвращает те же байты BGR/BGRA; флаг
      `cv2.IMREAD_UNCHANGED` по умолчанию сохраняет альфу.
- [ ] A5. Поведение compose не изменилось: на фиксированных входах (seed) результаты `composite`/`rotate_expand`/`crop_to_alpha`/
      `fit_longest_side`/`cast_contact_shadow` из `layer_render` побайтно равны sha256-литералам, снятым тестером **на коде до
      переезда** (литералы в тесте, не вычисленные из тестируемого кода).
- [ ] A6. Золотые эталоны плана ([goldens.md](goldens.md)) — зелёные без правки литералов; тесты 1.1 (`Services/layer_render/tests/`) — зелёные.
- [ ] A7. `sentrux check .` — зелёный; grep рамки (`grep -inE "letter|букв|disk|диск"` по новым файлам механизма) — 0 вне примеров README.
- [ ] A8. Потребители не правились: `git diff --name-only` против базы — только файлы из списка выше + тесты; число строк
      `from Services.dataset_gen.core.compose import` / `imread_unicode` в репо до и после — в отчёт, равны.

**Out of scope:** перевод потребителей (`line_sim`, `ml_train`, плагины) на новые импорты; `effects` (2.2); слои (2.3).

---

### Task 2.2 — `effects.py` + `EFFECT_PARAMS`; `apply_photometric` = список эффектов (бывш. 3.3)

- **Статус:** [DONE 2026-10-02 — `8665d7b7`] волна 3 · **Level:** Middle+ (Sonnet 5.5, решение владельца 2026-10-02: dev-effects) · **Assignee:** tester → developer → инъекции лида → reviewer
- **Module contract:** public-api-change (`layer_render.effects`: `EFFECTS`, `EFFECT_PARAMS`, `EffectSpec`, `apply_effects`;
  функции эффектов `dataset_gen.core.augment` — реэкспорт)
- **CHAIN:** `tester`(RED: оракул — дословная копия старого `apply_photometric` в тесте) → `developer`(GREEN) → инъекции лида → `reviewer`
- **Dependencies:** 2.1 (DONE)
- **Gate:** RED тестера → GREEN; инъекции записаны; `reviewer` APPROVED по SHA; grep рамки — 0

**Goal:** фотометрия — упорядоченный список `EffectSpec`, исполняемый `apply_effects`; `AugmentConfig` превращается в
этот список, `apply_photometric` — одна строка поверх него. Каталог параметров `EFFECT_PARAMS` — вход для
`effects.catalog` (Task 4.1).

**Files:**
1. `Services/layer_render/effects.py` (новый) — тела `Services/dataset_gen/core/augment.py:27-177` дословно
   (`apply_glare` … `apply_jpeg`, `make_motion_kernel`, `_uniform`); `EFFECTS`, `EFFECT_PARAMS`, `EffectSpec`, `apply_effects`
2. `Services/dataset_gen/core/augment.py` — реэкспорт функций (явный список); `augment_config_to_effects(cfg) -> list[EffectSpec]`;
   `apply_photometric(frame, cfg, rng)` = `apply_effects(frame, augment_config_to_effects(cfg), rng)`
3. `Services/layer_render/__init__.py`, `README.md` (Public API + раздел «Как добавить эффект»: функция + строка в `EFFECTS`
   + строка в `EFFECT_PARAMS`), `STATUS.md`
- тесты тестера: `Services/layer_render/tests/test_acceptance_2_2_effects.py`, `Services/dataset_gen/tests/test_augment_equivalence.py`

**DESIGN:**
- Сэмплинг параметров переезжает **из** `apply_photometric` (`augment.py:180-258`) **в** запись реестра:
  `EFFECTS: dict[str, Callable[[np.ndarray, Mapping, np.random.Generator], np.ndarray]]` — функция получает float32-кадр,
  параметры (диапазоны) и rng, разыгрывает свои значения **в нынешнем порядке** и возвращает кадр. Тело каждой записи —
  дословно соответствующий блок `apply_photometric` без строки `if … rng.random() < prob`.
- **Порядок вставки `EFFECTS` = канонический порядок** (`augment.py:191-258`): `glare, shadow, occlusion, gaussian_blur,
  motion_blur, vignette, brightness_contrast, gamma, color_temperature, channel_shift, noise, jpeg`. Отдельной константы
  порядка нет — `augment_config_to_effects` обходит ключи `EFFECTS`.
- `apply_effects(frame_u8, specs, rng)`: `specs == []` → `frame.copy()`, ноль розыгрышей. Иначе кадр — float32; на каждый
  spec — `rng.random() < spec.prob` (розыгрыш **всегда**, и при `prob 1.0`, и при `0.0` — как сейчас), затем запись реестра.
  Эффекты, работающие на uint8 (`jpeg` — множество `_U8_EFFECTS` рядом с `EFFECTS`), получают `np.clip(x, 0, 255).astype(uint8)`;
  после U8-эффекта кадр снова `astype(float32)` — каждый U8-эффект получает свой clip, порядок списка любой. В конце —
  clip→uint8; выход uint8 той же формы. (Канонический порядок — `jpeg` последним — даёт ровно нынешний один clip.)
- `EffectSpec` — `@dataclass(frozen=True, eq=False)` `(name, prob=1.0, params: Mapping = field(default_factory=dict))`;
  `__post_init__` проверяет и кладёт слитые с дефолтами параметры через `object.__setattr__` как `MappingProxyType`
  (образец — `ScrollingTile`, `layer_render/interfaces.py:42-65`). Хешируемость не нужна (`eq=False` — по идентичности). Неизвестное `name` →
  `ValueError` со списком известных; неизвестный ключ `params` → `ValueError` с именем ключа и списком допустимых;
  отсутствующий ключ → дефолт из `EFFECT_PARAMS`; `prob` вне [0, 1] → `ValueError`.
- `EFFECT_PARAMS: dict[str, dict[str, default]]` — имена параметров и дефолты **равны** полям соответствующих моделей
  `AugmentConfig` без `enabled`/`prob` (`dataset_gen/core/config.py`). `layer_render` не импортирует `dataset_gen`, поэтому
  равенство держит тест в `dataset_gen/tests` (он видит оба), а не код. Диапазоны/границы для UI — Task 4.1.
- `augment_config_to_effects(cfg)` — `[EffectSpec(n, sub.prob, sub.model_dump(exclude={"enabled", "prob"})) for n in EFFECTS
  if (sub := getattr(cfg, n)).enabled]`. Геометрия (`rotation`, `scale`, `shift`, `contact_shadow`) в список не входит.
- Имя CTO `effects_from_config` (вердикт, таблица модулей) — это `augment_config_to_effects`; живёт в `dataset_gen`, потому что
  знает `AugmentConfig`. `apply_effects_rgba` (эффекты слоя) — Task 2.3/3.1, не здесь.

**Acceptance:**
- [ ] A1. Эквивалентность: оракул (дословная копия старого `apply_photometric` в тесте, снятая **на коде до задачи**) и новый
      `apply_photometric` на 50 seed × 3 конфига (все 12 эффектов `enabled, prob 1.0`; дефолтный `AugmentConfig`; все
      выключены) × кадр 64×48 — побайтно равные кадры **и** равное `rng.bit_generator.state` после вызова.
- [ ] A1b. Тела функций перенесены дословно: оракул A1 зовёт модульные имена, а после переезда это те же объекты — сам по себе
      он тела не проверяет. Поэтому тестер на коде **до** задачи снимает sha256-литералы: по одному на конфиг A1 (байты 50
      кадров подряд, seed 0…49) и по одному на каждую из 11 функций эффектов на фиксированных параметрах — после задачи те же.
- [ ] A1c. Нестандартный порядок: `apply_effects(frame, [EffectSpec("jpeg"), EffectSpec("noise")], rng)` — работает, выход
      uint8 той же формы; два U8-эффекта подряд — тоже.
- [ ] A2. `apply_effects(frame, [], rng)` — состояние rng не изменилось, кадр равен входу и не является им (`is not`).
- [ ] A3. `list(EFFECTS)` — ровно канонический порядок из DESIGN (литерал в тесте).
- [ ] A4. Для каждого эффекта `EFFECT_PARAMS[n]` равен `getattr(AugmentConfig(), n).model_dump(exclude={"enabled","prob"})`
      (кортеж ↔ список нормализовать).
- [ ] A5. `EffectSpec("nope")` → `ValueError`, в тексте `glare` и `jpeg`; `EffectSpec("noise", params={"sigma": 1})` →
      `ValueError` с `sigma` и `std`; `EffectSpec("noise", prob=1.5)` → `ValueError`.
- [ ] A6. Для каждого из 11 имён `apply_glare, make_motion_kernel, apply_motion_blur, apply_brightness_contrast,
      apply_color_temperature, apply_channel_shift, apply_shadow, apply_occlusion, apply_gamma, apply_vignette, apply_jpeg`:
      `Services.dataset_gen.core.augment.<n> is Services.layer_render.effects.<n>` (`_uniform` — приватный, не реэкспортируется);
      `Services/line_sim/core/factory.py:15` (`apply_occlusion`) работает без правки.
- [ ] A7. `test_augment.py`, `test_engine.py`, `test_export_preview.py` (`Services/dataset_gen/tests/`), золотые эталоны
      ([goldens.md](goldens.md)) и тесты `Services/layer_render/tests/` — зелёные без правки литералов.
- [ ] A8. AST: `Services/layer_render/**` (кроме `tests/`) не импортирует `dataset_gen`/`line_sim`/`ml_train`; `sentrux check .`
      зелёный; grep рамки по `effects.py` — 0.

**Out of scope:** новые эффекты; эффекты слоя и сцены в симе (Ф3); `apply_effects_rgba`; torch-аугментации `ml_train`;
перевод потребителей на новые импорты.

**TRAPS:** `noise` — `rng.standard_normal(x.shape, dtype=np.float32)`: смена dtype или формы ломает поток; `occlusion` —
`rng.integers` числа прямоугольников, затем на каждый 6 вызовов (`uniform` ×5 скалярных — сторона, rw, rh, x, y; цвет — один вызов `size=3`), `augment.py:209-213`;
`shadow` — keyword-аргументы разыгрываются в порядке записи (`angle_deg, offset, strength, softness`), `:198-203`.

---

### Task 2.3 — `layers.py`: `LayerSpec`/`LayerAugment`/`compose_layers` в `layer_render`, `LayeredObject` — обёртка (бывш. 3.2)

- **Статус:** [DONE — `ca0e6203a`] волна 4 · **Level:** Senior+ (Opus 5.5) · **Assignee:** tester → teamlead → инъекции лида → reviewer
- **Module contract:** public-api-change (`layer_render.layers`: `LayerMode`, `RangeF`, `SpriteSource`, `AUGMENT_FIELDS`,
  `LayerAugment`, `LayerSpec`, `ComposedLayers`, `load_layer_sprite`, `transform_layer`, `canvas_size`, `compose_layers` — все 11
  в `Services.layer_render.__all__`; в `line_sim` — реэкспорт шести типов в `interfaces.py`, `canvas_size` и алиас
  `LayeredObject._transform` в `layered_object.py`)
- **CHAIN:** `tester`(RED: литералы на коде до задачи) → `teamlead`(GREEN) → инъекции лида → `reviewer`
- **Dependencies:** 2.1 (DONE), 2.2 (DONE). Параллельно 6.4: общие только `layer_render/README.md`, `STATUS.md` — разные строки, сводит лид
- **Gate:** RED тестера → GREEN; инъекции записаны; `reviewer` APPROVED по SHA; grep рамки по `layers.py` — 0

**Goal:** розыгрыш и композиция стека слоёв объекта — функция `layer_render`, которая не знает паспорта и `line_sim`;
`LayeredObject` остаётся публичным именем `line_sim` и собирает паспорт вокруг неё. Выход сима не меняется ни на байт.

**Files:**
1. `Services/layer_render/layers.py` (новый) — из `Services/line_sim/interfaces.py:21-113` дословно: `LayerMode`, `RangeF`,
   `SpriteSource`, `AUGMENT_FIELDS`, `LayerAugment`, `LayerSpec` (с обоими валидаторами); из
   `Services/line_sim/core/layered_object.py` дословно: `_load_sprite` (`:25-41`) → `load_layer_sprite`, `_rotate`
   (`:44-57`), `_hue_shift` (`:60-67`), `_hue_shift_color` (`:70-82`), `_over` (`:85-95`), `canvas_size` (`:98-107`),
   `LayeredObject._transform` (`:189-209`) → `transform_layer`, `LayeredObject._compose` (`:211-228`) → `_compose_canvas`;
   тело `LayeredObject.__init__` (`:126-185`) → `compose_layers`, **включая** `_compose` и проверку прозрачности (`:183-185`)
2. `Services/line_sim/interfaces.py` — шесть типов из п.1 — явным `import` из `layer_render.layers` + `__all__`; `ObjectPassport` и `Protocol` сцены остаются
3. `Services/line_sim/core/layered_object.py` — в обёртке остаются: разбор `passport.defect` (`:140`), `replace(passport, ...)` (`:182`),
   read-only (`:186`). `canvas_size` — реэкспорт **в `__all__` модуля** (потребитель `core/preview.py:34`; без `__all__` pre-commit
   `ruff --fix` F401 удалит неиспользуемый импорт — `.pre-commit-config.yaml:34-35`). `LayeredObject._transform = staticmethod(transform_layer)`
   (потребители — `core/factory.py:184` и `tests/test_hazards_look_1_2.py:116`, правка тестов запрещена)
4. `Services/line_sim/core/factory.py:17,184` — `_load_sprite` → `load_layer_sprite` из `Services.layer_render` (приватные имена не реэкспортируются, правило `docs/maps/layer_render.md`)
5. `Services/layer_render/__init__.py`, `README.md` (Public API), `STATUS.md`; `docs/maps/layer_render.md` — строка `layers.py`
- тесты тестера: `Services/layer_render/tests/test_acceptance_2_3_layers.py`

**DESIGN:**
- Перенос **дословный**, ни одного «попутного улучшения»: `rng.spawn(len(layers))`, порядок `uniform` по `AUGMENT_FIELDS`,
  `sub.random() < defect_probability`, премультиплицированная канва и распремультипликация, `rot90` на кратных 90°,
  `_hue_shift` через HSV. Импорты `composite`/`rotate_expand` — из `Services.layer_render.compose` (сейчас `layered_object.py:21`
  берёт их через реэкспорт `dataset_gen.core.compose` — тот же объект). Докстринги — дословно, кроме ссылок на переименованные
  имена (`canvas_size` ссылается на `LayeredObject._compose` → `_compose_canvas`).
- Сигнатура: `compose_layers(layers, rng, object_angle_deg=0.0, forced_defects=(), *, label="") -> ComposedLayers`;
  `ComposedLayers` — `NamedTuple(rgba, layer_params, active_defects)`. `rgba` — **записываемый** массив (read-only ставит
  обёртка: функция не знает про кэш). `active_defects` — `tuple[str, ...]` в порядке слоёв.
- **Порядок проверок и тексты ошибок — прежние** (проверено ревью спеки запуском): пустой список → спрайты все
  (`load_layer_sprite`, `TypeError`/`ValueError`) → дубли имён → неизвестный принудительный дефект → розыгрыш → полностью
  прозрачный RGBA. Префикс `LayeredObject '<label>':` остаётся в текстах `compose_layers` (`label` — на месте
  `passport.object_id`; слово `LayeredObject` в тексте — как упоминание `ObjectFactory`, не импорт). Разбор строки
  `passport.defect` (`split(",")`, `strip`) остаётся в обёртке; `compose_layers` получает уже список имён.
- Тексты ошибок содержат входные значения (`sprite_source='{source}'`, `defect={unknown}`, `color_rgb … {value!r}`) —
  сохраняются ради A6; правка текстов вне задачи.
- `layer_render` не импортирует `ObjectPassport` и `Services.line_sim`.
- Имена и типы полей `LayerSpec` не меняются — на них стоят `pult_web` (`plugin.py:1310-1396` — `offset_px`, `angle_deg`,
  `scale`; `:1627-1763` — `sprite_source`) и YAML пресетов. `LayerSpec.__module__` станет `Services.layer_render.layers`;
  pickle/deepcopy `LayerSpec` в рабочем коде нет (ревью спеки: grep → 0), `model_json_schema()` никто не вызывает, заголовок
  ошибки pydantic берётся из имени класса.
- Докстринг модуля `line_sim/interfaces.py` (конвенция поворота, пример-литерал) переезжает в `layers.py` и остаётся
  ссылкой в `line_sim`.

**Acceptance:**
- [ ] A1. Литералы до задачи (тестер снимает в worktree на коммите до кода): sha256 `LayeredObject(...).render()` и
      `passport.layer_params`/`passport.defect` на 6 стеках × 3 seed — {один static; static+augmented; augmented с
      `hue_shift_deg` и `color_rgb`; defect p=0.5; принудительный defect; объект под углом 90° и 37°} — после задачи те же.
- [ ] A2. `compose_layers` напрямую на тех же входах — те же sha256 RGBA и те же `layer_params`, что A1.
- [ ] A3. `test_hazards_1_3h_layout.py:40-44` (15 отпечатков), `test_acceptance_lateral_offset_plugin.py:492-493`,
      `test_acceptance_lateral_offset.py:355`, золотые эталоны ([goldens.md](goldens.md)), все тесты `Services/line_sim/tests/`,
      `Plugins/sim/*/tests/`, `Services/layer_render/tests/` — зелёные без правки (кроме известного флака
      `test_acceptance_r5_page.py::test_a2_undo_highlights_restored_layer_not_the_foreign_one`, запись `c6e04318f`: повтор зелёный — в отчёт).
- [ ] A4. `Services.line_sim.interfaces.<n> is Services.layer_render.layers.<n>` для `LayerSpec`, `LayerAugment`,
      `AUGMENT_FIELDS`; `layered_object.canvas_size is layers.canvas_size`;
      `LayeredObject._transform is Services.layer_render.layers.transform_layer`; `transform_layer(s, 1.0, 0.0, 0.0, None) is s`;
      sha256 `LayeredObject._transform(s, 0.9, 37.0, 30.0, (10, 20, 30))` на RGBA-спрайте из seed — литерал до задачи.
- [ ] A4b. Все 11 имён Module contract — в `Services.layer_render.__all__`; `Services.line_sim.LayerSpec is Services.layer_render.LayerSpec`
      (образец — `test_acceptance_6_1_crop.py:596-602`).
- [ ] A5. Детерминизм и чистота: `compose_layers` дважды с одним seed — побайтно тот же RGBA; входной список слоёв и
      callable-провайдеры не мутированы; провайдер вызван ровно один раз на слой; выход `rgba.flags.writeable is True`,
      `LayeredObject.render().flags.writeable is False`.
- [ ] A6. Ошибки — прежние тип и текст (литералы до задачи, через `LayeredObject(...)`): пустой список, строковый
      `sprite_source`, RGB-спрайт, дубли имён, неизвестный принудительный дефект, прозрачный итог; при одновременных «битый
      спрайт + дубли имён» — ошибка спрайта. Через `compose_layers(..., label="X")` — тот же тип и `"'X'" in str(e)`
      (кроме ошибок спрайта: они называют слой, не объект).
- [ ] A7. AST: `Services/layer_render/**` (кроме `tests/`) не импортирует `dataset_gen`/`line_sim`/`ml_train`; `sentrux check .`
      зелёный; validate без ошибок.

**Out of scope:** эффекты слоя (`LayerSpec.effects`, Ф3/3.1), новые поля слоя, перенос `ObjectFactory`/`ScenePreset`/`preview` (2.4),
субпиксельное размещение (`ponytail:` в `_compose`), правка текстов ошибок, ниты ревью 1.1 сверх уже закрытых.

**TRAPS:** `color_rgb` у defect-слоя пишется в `layer_params` **до** `continue` невыпавшего — и с `dhue = 0.0`; `_hue_shift_color`
при `hue_deg == 0.0` возвращает вход как есть (без HSV-округления); при `scale == 1.0`, `angle_deg == 0.0`, `hue_deg == 0.0`
и `color_rgb is None` `transform_layer` отдаёт **сам спрайт** (кэш фабрики), не копию — идентичность держит A4;
`test_hazards_1_3h_layout.py:287` держит только read-only вид; `canvas_size` в `layered_object.py` без `__all__` снесёт ruff.

---

### Task 2.4a — `ScenePreset` и каталог классов переезжают в `layer_render`, старые места — реэкспорт (часть бывш. 2.4)

Спека вынесена в [phase-2-core-2.4a.md](phase-2-core-2.4a.md) (файл фазы перерос бюджет 32 КБ). Ревью спеки, раунд 1 — CHANGES REQUESTED, правки B1–B4, M1–M4 внесены (2026-10-02).

### Task 2.4b — `ObjectFactory` и превью переезжают в `layer_render`, фабрика отдаёт `RenderedObject` (часть бывш. 2.4)

Спека — в [phase-2-core-2.4b.md](phase-2-core-2.4b.md) (файл фазы у бюджета 32 КБ).

### Task 2.5 — `render_scene(background, placed, effects, rng)`: одна функция кадра; `SceneCompositor` делегирует

Спека — в [phase-2-core-2.5.md](phase-2-core-2.5.md) (файл фазы у бюджета 32 КБ).
