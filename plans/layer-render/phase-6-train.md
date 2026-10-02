# Фаза 6 (новая нарезка) — обучение, дорожка B

Родитель: [plan.md](plan.md), архитектура — [cto-verdict-2026-10-01.md](cto-verdict-2026-10-01.md). Старый
[phase-2.md](phase-2.md) — прежняя нарезка (бывш. 2.1 = 6.1, 2.2 = 6.2, 2.3 = 6.3, 2.4 = 6.4), тексты переиспользованы.

---

### Task 6.1 — одна функция выреза для `center_crop`, `holdout_eval` и генератора (бывш. 2.1)

- **Статус:** [PENDING] волна 3 · **Level:** Middle+ (Sonnet 5.5) · **Assignee:** tester → developer (dev-crop) → инъекции лида → reviewer
- **Module contract:** public-api-change (`layer_render.crop`: `side_from_radius`, `square_crop`, `resize_square`)
- **CHAIN:** `tester`(RED: литералы старого поведения на коде до задачи) → `developer`(GREEN) → инъекции лида → `reviewer`
- **Dependencies:** Ф1 (DONE). Параллельно 2.2: общие только `layer_render/__init__.py`, `README.md` — разные строки, сводит лид при слиянии
- **Gate:** RED тестера → GREEN; инъекции записаны; `reviewer` APPROVED по SHA; grep рамки по `crop.py` — 0

**Goal:** вырез квадрата вокруг центра и ресайз ко входу модели живут в одной функции; оба нынешних места зовут её,
их выход не меняется ни на байт.

**Files:**
1. `Services/layer_render/crop.py` (новый) — `side_from_radius(radius, radius_scale, margin_px) -> int`,
   `square_crop(frame, cx, cy, side, oob, pad_value=(0, 0, 0)) -> np.ndarray | None`, `resize_square(crop, out) -> np.ndarray`
2. `Services/layer_render/__init__.py`, `Services/layer_render/README.md` (Public API)
3. `Plugins/processing/center_crop/plugin.py` — `_resolve_side` (`:112-124`), `_crop_square` + `_pad_canvas` (`:137-179`),
   `_resize_output` (`:100-110`) делегируют
4. `Services/ml_train/holdout_eval.py` — `_crop_disk` (`:44-61`) делегирует: `detect_disk` и `half = round(r·(1+margin))`
   остаются, вырез — `square_crop(bgr, cx, cy, 2·half, oob="replicate")`
- тесты тестера: `Services/layer_render/tests/test_acceptance_6_1_crop.py`

**DESIGN:**
- `oob ∈ {"drop", "pad", "clamp", "replicate"}` — ровно четыре нынешних поведения, тела переносятся дословно:
  `drop` → `None`, если квадрат хоть частично вне кадра; `pad` → холст `side×side` цветом `pad_value` по правилу
  `_pad_canvas` (`(color + [0,0,0])[:c]` для 3D, `color[0]` для 2D), пересечение вклеено, без пересечения — чистый холст;
  `clamp` → пересечение (меньше стороны), без пересечения — `None`; `replicate` → `cv2.copyMakeBorder(..., BORDER_REPLICATE)`
  как в `_crop_disk` при частичном пересечении. «Нет пересечения» определяется по обрезанным границам (`sx1 <= sx0` или
  `sy1 <= sy0`, где `sx1 = min(w, x0 + side)`), и у `replicate` это `ValueError`. Сегодня `_crop_disk` в этом случае
  молча отдаёт мусор: отрицательный конец среза заворачивается, и форма выходит неверная (ревью спеки: центр
  (100, −100), r=30 → (230, 70, 3)). Это намеренное изменение, не перенос.
- Привязка: `x0 = cx - side // 2`, ширина и высота ровно `side` — как в обоих местах (у `_crop_disk` `side = 2·half`, чётная).
- **Выход — всегда копия, никогда view кадра** (`plugin.py:148` — «отвязать от SHM-буфера»; с 4.7b кадр — read-only view SHM).
  У `center_crop` это перенос; у `_crop_disk` — **намеренное изменение** (сегодня квадрат внутри кадра отдаётся view), байты те же.
- `side_from_radius` — формула `plugin.py:121-122`: `max(2, int(round(2·r·scale)) + 2·int(margin))`. Fallback «радиус
  неизвестен → `side_px`» (`size_mode`, `radius` пустой) остаётся в плагине — это знание регистра, не выреза.
- `resize_square(crop, out)`: `out <= 0` или уже `out×out` → вход как есть; иначе `INTER_AREA` при уменьшении,
  `INTER_LINEAR` при увеличении (сравнение по `crop.shape[0]`, как `plugin.py:109`).
- Регистр `center_crop` не знает слова `oob`: `drop_partial=True` → `drop` (побеждает); иначе `pad_if_oob=True` → `pad`
  цветом `pad_color_bgr`; оба `False` → `clamp` (`registers.py:86-107`). `replicate` — только `holdout_eval`.
- Формула стороны `holdout_eval` **не меняется** — перевод на формулу конвейера — Task 6.4 (О-1).

**Acceptance:**
- [ ] A1. Литералы до задачи (тестер снимает в worktree на коммите до кода): sha256 выхода `center_crop` (через плагин, на
      фиксированном кадре 200×160×3 uint8 из seed) для `drop`/`pad`/`clamp` × {квадрат внутри, у края, центр вне кадра} и
      `holdout_eval._crop_disk` на 3 кадрах с диском у края (`detect_disk` подменён фиксированным `(cx, cy, r)`) — после задачи
      те же sha256.
- [ ] A2. `square_crop` напрямую на тех же входах — те же sha256, что A1 (функция = поведение плагина).
- [ ] A3. Выход `square_crop` не делит память с кадром (`np.shares_memory(out, frame) is False`) во всех четырёх режимах,
      включая «квадрат целиком внутри»; на read-only кадре (`frame.flags.writeable = False`) — работает, выход записываемый.
- [ ] A4. `square_crop(..., oob="bogus")` → `ValueError`, текст называет значение; `replicate` без пересечения → `ValueError`
      в трёх положениях: центр ниже кадра, далеко выше (`cy + side//2 < 0`) и далеко левее (`cx + side//2 < 0`).
- [ ] A5. `side_from_radius(150, 1.0, 14) == 328` (рецепт `letter_robot_sim.yaml:250-254`); `side_from_radius(0, 1.0, 0) == 2`.
- [ ] A6. `resize_square`: 328→128 — `INTER_AREA` (литерал sha256 до задачи), 64→128 — `INTER_LINEAR`, `out=0` — вход `is` выход.
- [ ] A7. Существующие тесты `Plugins/processing/center_crop/tests/` и `Services/ml_train/tests/` — зелёные без правки;
      AST: `layer_render` не импортирует `dataset_gen`/`line_sim`/`ml_train`; `sentrux check .` зелёный.

**Out of scope:** смена формулы `holdout_eval` (6.4); новые режимы выреза; круглая маска; генератор (6.2);
`layer_render/STATUS.md` — его ведёт 2.2, строку про `crop` дописывает лид при слиянии.

---

### Task 6.4 — `holdout_eval` режет кадр по формуле конвейера (решение О-1, бывш. 2.4)

- **Статус:** [PENDING] волна 4 · **Level:** Middle (Sonnet 5.5) · **Assignee:** tester → developer → прогон и инъекции лида → reviewer
- **Module contract:** impl-only (`evaluate_holdout`: аргумент `margin` заменён на `radius_scale`/`margin_px`/`output_size`/`pad_color_bgr`; CLI `eval` — те же флаги)
- **CHAIN:** `tester`(RED) → `developer`(GREEN) → прогон лида (старое/новое число) → инъекции лида → `reviewer`
- **Dependencies:** 6.1 (DONE). Параллельно 2.3: общие только `layer_render/README.md`/`STATUS.md` — разные строки, сводит лид
- **Gate:** RED тестера → GREEN; инъекции записаны; `reviewer` APPROVED по SHA; grep рамки — 0; прогон лида записан

**Goal:** проверка модели режет кадр так же, как конвейер перед `ml_inference`; число точности меряет то, что видит робот.

**Files:**
1. `Services/ml_train/holdout_eval.py` — `_crop_disk(bgr, radius_scale, margin_px, output_size, pad_color_bgr)`:
   `detect_disk` → `side_from_radius(r, radius_scale, margin_px)` → `square_crop(..., oob="pad", pad_value=pad_color_bgr)` →
   `resize_square(crop, output_size)`; `evaluate_holdout(..., radius_scale=1.0, margin_px=14, output_size=128,
   pad_color_bgr=(0, 0, 0), ...)`; аргумент `margin` удаляется; в сводку — ключ `"crop"` с этими четырьмя значениями
2. `Services/ml_train/__main__.py:40-44,119` — флаги `--radius-scale`, `--margin-px`, `--output-size`, `--pad-color-bgr B,G,R`
   с дефолтами рецепта, проброс в `evaluate_holdout`
3. `Services/layer_render/tests/test_acceptance_6_1_crop.py`, `test_hazards_6_1_crop.py` — тесты, закрепившие **старую формулу**
   `_crop_disk` (список ниже), удаляются **намеренно**; тесты самой `square_crop` (в т.ч. `replicate`) остаются
4. `Services/ml_train/README.md`, `STATUS.md` (база выреза, числа прогона лида); `docs/maps/crop.md` (потребитель 2)
- тесты тестера: `Services/ml_train/tests/test_acceptance_6_4_holdout_crop.py`

**DESIGN:**
- Дефолты = рецепт `multiprocess_prototype/recipes/letter_robot_sim.yaml:249-255` (`size_mode: radius`, `radius_scale 1.0`,
  `margin_px 14`, `output_size 128`, `pad_if_oob: true`, `drop_partial: false`) и дефолт регистра `pad_color_bgr = [0, 0, 0]`
  (`Plugins/processing/center_crop/registers.py:103-110`). В коде `holdout_eval` литералы только в сигнатуре — не в теле.
- `resize_square` до `engine.predict` — как в конвейере: `center_crop` отдаёт 128×128 (`INTER_AREA` при уменьшении), потом движок
  делает свой resize (sidecar `input_size: [128, 128]` → no-op). Без этого шага уменьшение было бы другой интерполяцией движка.
- `oob="pad"` при отсутствии пересечения отдаёт чистый холст (`crop.py`, карта `docs/maps/crop.md`) — `ValueError` у
  `_crop_disk` больше нет. Из реального `detect_disk` этот случай недостижим (ревью 6.1: 300 кадров, 0 случаев).
- `oob="replicate"` в `crop.py` **остаётся**: после задачи у него нет потребителя, но он закреплён тестами 6.1 как контракт
  (память «неиспользуемый путь = контракт»). README `layer_render` помечает: «потребителей нет с 6.4». Удаление — решение владельца.
- Детектор диска не меняется: в конвейере радиус даёт `circle_detector`, здесь `detect_disk` (HoughCircles). Расхождение
  детекторов — вне задачи, в отчёт лида одной строкой.
- **Тесты 6.1 на старую формулу — удаляются в этой задаче** (поведение меняется намеренно, О-1):
  `test_acceptance_6_1_crop.py::test_a1_crop_disk_output_matches_literals_taken_before_the_task` (3 параметра),
  `test_hazards_6_1_crop.py::test_crop_disk_is_a_copy_and_side_formula_is_unchanged`,
  `::test_crop_disk_center_outside_frame_raises_value_error`. Литералы `_A1_DISK` остаются: на них стоит
  `test_a2_square_crop_replicate_matches_the_crop_disk_literals` (это тест `square_crop`, не `_crop_disk`). Коммит называет
  каждый удалённый тест и причину.

**Acceptance:**
- [ ] A1. Синтетический кадр 640×480×3 с диском `r=150` в центре (`detect_disk` подменён фиксированным `(320, 240, 150)`):
      `_crop_disk` с дефолтами → форма `(128, 128, 3)`; побайтно равен выходу `CenterCropPlugin` с регистром
      `size_mode: radius, radius_scale 1.0, margin_px 14, output_size 128, pad_if_oob true, drop_partial false` на том же кадре и
      том же `(cx, cy, r)`.
- [ ] A2. Сторона до ресайза: при `output_size=0` (без ресайза) выход `(328, 328, 3)` для `r=150` (`2·150·1.0 + 2·14`).
- [ ] A3. У края кадра (`cx=20`) — заливка `pad_color_bgr`, не репликация: левые столбцы выхода (при `output_size=0`)
      равны `(7, 8, 9)` при `pad_color_bgr=(7, 8, 9)`. Квадрат без пересечения с кадром → холст цвета `pad_color_bgr`, не исключение.
- [ ] A4. Выход не делит память с кадром (`np.shares_memory is False`); read-only кадр работает.
- [ ] A5. `evaluate_holdout` не принимает `margin` (`TypeError`); CLI `eval --help` перечисляет четыре новых флага;
      `--pad-color-bgr 7,8,9` доходит до `_crop_disk` как `(7, 8, 9)`; в сводке ключ `"crop"` с четырьмя значениями.
- [ ] A6. Остальные тесты `Services/ml_train/tests/`, `Services/layer_render/tests/`, `Plugins/processing/center_crop/tests/` —
      зелёные без правки, кроме трёх удалённых из списка DESIGN.
- [ ] A7. Прогон лида (данные вне git), модель `mobilenet_v3_large_20260616_050828`: точность буквы, MAE угла и доля ≤5°
      по **старой** и **новой** формуле рядом — в `Services/ml_train/STATUS.md` и в отчёте. Настоящей отложенной выборки на диске
      нет (2026-10-02): прогон идёт на `data/real_photos` (8 кадров, 2 буквы, участвовали в обучении), это пишется рядом с числами.

**Out of scope:** смена модели; правка `detect_disk`; удаление `replicate`; сбор настоящей отложенной выборки (→ letters-retrain).
