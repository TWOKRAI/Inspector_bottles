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
