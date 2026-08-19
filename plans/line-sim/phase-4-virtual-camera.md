# Phase 4 — Виртуальная камера

Часть плана [`plan.md`](plan.md). Реализует «Настраивается как настоящая: fps,
размер кадра, цвет/моно» и ROI-рамку из vision.md. Фотометрия — единым проходом на
готовую сцену (переиспользование `dataset_gen.core.augment`), не на отдельные слои.

---

### Task 4.1 — Настройки камеры (fps / размер / цвет-моно)

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** `LineSimCameraPlugin` конфигурируется той же поверхностью настроек, что
боевые камеры прототипа (пресеты + actual) — fps, ширина/высота, цветной/моно.

**Files:**
- `Plugins/sources/line_sim_camera/registers.py` — новый `LineSimCameraRegisters`
  (по образцу `Services/modbus/plugin/registers.py`/`Plugins/processing/center_crop/
  registers.py` — поля для авто-генерации инспектора ноды в GUI)
- `Plugins/sources/line_sim_camera/plugin.py` — прочитать `color_mode: "bgr"|"gray"`
  и применить к выходному кадру
- `Plugins/sources/line_sim_camera/tests/test_cam_actual_section.py` — по прецеденту
  `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/
  test_cam_actual_section.py` (изучить его ПЕРЕД реализацией — это готовый образец
  поверхности "пресеты + actual" для боевых камер)

**Steps:**
1. Изучить `test_cam_actual_section.py` и связанный `inspector/` код (`exec_info_
   section.py`/`process_selector_section.py`/`hikvision_embed.py` в
   `multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/`) — понять
   ТОЧНО, что значит «actual» для боевой камеры (текущие фактические fps/размер,
   в отличие от сконфигурированных) — line_sim-камера обязана давать те же два
   среза (сконфигурировано vs фактически отдаётся).
2. `LineSimCameraRegisters`: поля `resolution_width`, `resolution_height`, `fps`,
   `color_mode`, + readonly `actual_fps` (обновляется на каждый `produce()` —
   скользящее среднее интервалов, как у боевых камер — сверить формулу с
   `hikvision_camera`, не изобретать новую).
3. `color_mode="gray"`: выходной кадр — `(H, W, 1)` или `(H, W)` (сверить, какую
   форму ждёт `color_convert`/дальнейший тракт — не ломать `channels` поле item).

**Acceptance criteria:**
- [ ] `LineSimCameraPlugin` с `color_mode="bgr"` (дефолт) — `item["channels"] == 3`,
      `item["frame"].shape[2] == 3`.
- [ ] `LineSimCameraPlugin` с `color_mode="gray"` — `item["channels"] == 1`,
      `item["dtype"] == "uint8"`, форма кадра без 3-го измерения ИЛИ с
      `shape[2]==1` (зафиксировать ОДНО конкретное поведение и покрыть тестом —
      не оставлять на усмотрение).
- [ ] После 10 вызовов `produce()` подряд с известным контролируемым временем
      между вызовами, `actual_fps` в register отражает реальную частоту вызовов
      (± разумная погрешность, например 10%) — не равен статично
      сконфигурированному `fps`.
- [ ] Смена `resolution_width/height` через `set_register`-подобный live-command
      (или через новый конфиг + рестарт — зафиксировать, какой из двух путей
      выбран) отражается в форме СЛЕДУЮЩЕГО кадра.

**Out of scope:** ROI (Task 4.2), фотометрия (Task 4.3).
**Dependencies:** Task 3.4.
**Module contract:** impl-only.

---

### Task 4.2 — ROI: бэкенд конфига и live-команд

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** прямоугольник ROI (позиция+размер в координатах сцены) конфигурируется и
может быть подвинут/растянут ЖИВОЙ командой (числовой контракт — мышь на канве это
Task 6.3, здесь только backend-поверхность, которую GUI будет вызывать).

**Контекст:** ROI здесь — «какую часть НАРИСОВАННОЙ СЦЕНЫ видит виртуальная камера»
(рамка позиционирования камеры), а НЕ то же самое, что существующий
`Plugins.processing.roi_crop` (который кропает уже готовый кадр камеры дальше по
тракту, значения 246/297/800/481 в рецепте настроены под РЕАЛЬНЫЙ сенсор Hikvision и
эту задачу не трогают вообще). v1: размер ROI == размеру выходного кадра камеры (без
промежуточного масштабирования/зума) — см. Deferred в `plan.md`.

**Files:**
- `Plugins/sources/line_sim_camera/plugin.py` — `commands: {"set_roi": "cmd_set_roi"}`
- `Services/line_sim/core/scene_compositor.py` (из 3.4) — `camera_rect` становится
  mutable-полем, а не конструкторной константой

**Steps:**
1. `cmd_set_roi(data: dict) -> dict` — принимает `{x, y, width, height}` (координаты
   сцены, мм или px — выбрать одну единицу, задокументировать), валидирует (не
   отрицательные, не за пределами `scene_length_mm`/высоты сцены), применяет к
   `SceneCompositor.camera_rect` атомарно (следующий `produce()` уже использует
   новое значение).
2. По образцу `RoiCropPlugin`, читать `camera_rect` из register КАЖДЫЙ кадр (не
   кэшировать при `configure()`) — live-тюнинг применяется сразу, тот же паттерн,
   что уже используется у `roi_crop`.

**Acceptance criteria:**
- [ ] `cmd_set_roi({"x": 10, "y": 20, "width": 200, "height": 150})` возвращает
      `{"status": "ok", ...}`; следующий `produce()` даёт кадр, где объект,
      находящийся ТОЛЬКО в старом ROI (не в новом), пропадает из `sim_truth`, а
      объект, находящийся только в новом — появляется.
- [ ] `cmd_set_roi({"x": -5, ...})` (некорректные координаты) возвращает
      `{"status": "error", ...}`, `camera_rect` НЕ меняется (текущее значение
      сохраняется, следующий `produce()` использует старый ROI).
- [ ] ROI больше сцены — клампится к границам сцены (не падает, не даёт кадр с
      неопределёнными зонами).

**Out of scope:** мышь/GUI (Task 6.3); масштабирование ROI≠размер кадра камеры
(Deferred).
**Dependencies:** Task 3.4.
**Module contract:** impl-only.

---

### Task 4.3 — Фотометрия сцены (переиспользование `dataset_gen.augment`)

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** готовая скомпонованная сцена (все объекты + фон, ДО передачи в
`item["frame"]`) проходит через `dataset_gen.core.augment.apply_photometric` (блик,
смаз движения, тень, баланс белого, гамма, виньетка, шум, JPEG) — конфигурируемо через
`sim.camera.augment` в рецепте, той же формой конфига, что `AugmentConfig` в
dataset_gen.

**Контекст:** `apply_photometric` уже принимает `AugmentConfig` (Pydantic) — line_sim
переиспользует ЭТОТ тип напрямую (импорт из `Services.dataset_gen.core.config`), не
заводит параллельный дублирующий конфиг-класс с теми же полями.

**Files:**
- `Services/line_sim/core/scene_compositor.py` — вызов `apply_photometric` перед
  возвратом кадра из `render()`
- `Services/line_sim/presets/letters_disk.yaml` — секция `augment:` (та же схема,
  что `dataset_gen/presets/real_letters_disk.yaml`)

**Steps:**
1. `SceneCompositor.__init__` принимает `augment_cfg: AugmentConfig | None` (None —
   фотометрия выключена, кадр как есть — полезно для отладки/тестов без шума).
2. После `composite()` всех объектов на фон, но ДО `color_mode`-конвертации (Task
   4.1) — вызвать `apply_photometric(frame_rgb, augment_cfg, rng)`.
3. Убедиться, что рендер детерминирован при фиксированном `rng` (seed) — критично для
   тестов и для «повторить прогон» (`ScenePreset.seed`, аналогично
   `GeneratorConfig.seed` в dataset_gen).

**Acceptance criteria:**
- [ ] С `augment_cfg=None` — кадр идентичен (побитово) кадру без вызова
      `apply_photometric` (проверка, что интеграция не меняет поведение при
      выключенной фотометрии — регрессия к Task 3.4/4.1/4.2 недопустима).
- [ ] С `augment_cfg`, где ВСЕ блоки `enabled: true, prob: 1.0` (детерминированный
      максимум эффекта) — кадр отличается (пиксельная разница > 0) от кадра с
      `augment_cfg=None`, при одинаковом `rng` seed для геометрии (объекты те же).
- [ ] Два рендера с одинаковым `seed` дают побитово идентичные кадры (детерминизм);
      два рендера с разным `seed` (при прочих равных, `augment` включён) — дают
      разные кадры.
- [ ] `python -m Services.line_sim` (или эквивалентный smoke-запуск, если есть CLI) с
      реальным пресетом не падает при отсутствии `torch`/`PySide6` в окружении (та же
      graceful-degradation дисциплина, что у `dataset_gen`).

**Out of scope:** контактная тень под объектом на сцене-фоне (nice-to-have,
`cast_contact_shadow` уже реализован в dataset_gen и переиспользуем при желании, но не
обязателен для v1 acceptance).
**Dependencies:** Task 3.4.
**Module contract:** impl-only.
