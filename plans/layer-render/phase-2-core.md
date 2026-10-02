# Фаза 2 (новая нарезка) — ядро сервиса `Services/layer_render`

Родитель: [plan.md](plan.md), архитектура — [cto-verdict-2026-10-01.md](cto-verdict-2026-10-01.md). Старый
[phase-3.md](phase-3.md) — прежняя нарезка (бывш. 3.1 = 2.1, 3.3 = 2.2, 3.2 = 2.3), тексты переиспользованы.

Итог фазы: примитивы композиции, эффекты, слои, пресет, фабрика, каталог и превью живут в `layer_render`; одна
функция кадра `render_scene`. Это переезд: внешнее поведение не меняется ни на байт. Старые места импорта остаются
реэкспортом (явные имена, не `*`); ни один потребитель вне `Files` не правится.

---

### Task 2.1 — `compose.py` + `io.py` переезжают, старые модули — реэкспорт (бывш. 3.1)

- **Статус:** [IN PROGRESS] волна 2 · **Level:** Middle (Sonnet 5.5) · **Assignee:** tester → developer → инъекции лида → reviewer
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

- **Статус:** [PENDING] волна 3 · **Level:** Middle+ (Sonnet 5.5, решение владельца 2026-10-02: dev-effects) · **Assignee:** tester → developer → инъекции лида → reviewer
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
  Эффекты, работающие на uint8 (`jpeg` — множество `_U8_EFFECTS` рядом с `EFFECTS`), получают `clip→uint8` кадр; clip —
  один раз перед первым таким эффектом и в конце; выход uint8 той же формы.
- `EffectSpec` — frozen dataclass `(name, prob=1.0, params={})` (как `SolidFill` в `background.py`): неизвестное `name` →
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
- [ ] A2. `apply_effects(frame, [], rng)` — состояние rng не изменилось, кадр равен входу и не является им (`is not`).
- [ ] A3. `list(EFFECTS)` — ровно канонический порядок из DESIGN (литерал в тесте).
- [ ] A4. Для каждого эффекта `EFFECT_PARAMS[n]` равен `getattr(AugmentConfig(), n).model_dump(exclude={"enabled","prob"})`
      (кортеж ↔ список нормализовать).
- [ ] A5. `EffectSpec("nope")` → `ValueError`, в тексте `glare` и `jpeg`; `EffectSpec("noise", params={"sigma": 1})` →
      `ValueError` с `sigma` и `std`; `EffectSpec("noise", prob=1.5)` → `ValueError`.
- [ ] A6. Для каждого имени `n` из `augment.py:27-177`: `Services.dataset_gen.core.augment.<n> is Services.layer_render.effects.<n>`;
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
