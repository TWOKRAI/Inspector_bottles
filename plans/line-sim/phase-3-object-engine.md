# Phase 3 — Движок объектов: слои, буквы-диски, дефекты

Часть плана [`plan.md`](plan.md). Реализует «Объект — группа слоёв, а не картинка» из
vision.md: движок объект-агностичен с первого дня, v1 наполняет его ТОЛЬКО контентом
буквы-диска (бутылки — Deferred). Переиспользует низкоуровневые функции
`Services/dataset_gen` напрямую (импорт, не форк) — см. Decisions log в `plan.md`.

---

### Task 3.1 — Каркас `Services/line_sim`: слои, объект-паспорт, геометрия ленты

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** новый Services-модуль с публичным контрактом (`interfaces.py`) для
объект-агностичного движка сцены: слой (static/augmented/defect), объект (список
слоёв + паспорт: класс/угол/дефект), позиция вдоль ленты по инварианту трекинга
(`FACTOR_MM`/`BELT_UX`/`BELT_UY`, реэкспорт из `Services.robot_comm.core.registers`).

**Контекст:** Это архитектурное решение с долгими последствиями — контракт, который
Task 3.2–3.4 и Ф4–Ф5 будут наполнять и потреблять. Исторический прототип
(`Create_bottles/generate_bottle_module.py`, коммит `6116adf3`) даёт идейную основу
(`LayerImage`: позиция/угол/масштаб/fill-эффект/контур; `BottleGroup`: группа слоёв) —
НЕ копировать 1:1: `Services/dataset_gen/core/compose.py` уже даёт проверенные,
протестированные `rotate_expand`/`crop_to_alpha`/`composite`/`cast_contact_shadow` —
использовать их вместо самодельного `cv2.warpAffine`. Разница с `DatasetEngine`
(`dataset_gen`): тот генерирует ОДИН объект на кадр для обучения; этот движок кладёт
НЕСКОЛЬКО объектов на непрерывно движущуюся ленту — генуинно новая логика (не
натягивать `DatasetEngine.generate_sample()` на многообъектную роль).

**Files (новый пакет — module-contract new-full):**
- `Services/line_sim/__init__.py` — публичный реэкспорт
- `Services/line_sim/interfaces.py` — Protocol: `SceneCompositor` (`spawn`,
  `render_frame`, `despawn_stale`), `ObjectPassport` (dataclass: `object_id`,
  `class_name`, `angle_deg`, `defect: str | None`, `spawn_encoder`), `LayerSpec`
  (dataclass: `mode: Literal["static","augmented","defect"]`, `sprite_source`, ...)
- `Services/line_sim/core/__init__.py`
- `Services/line_sim/core/belt.py` — геометрия: `encoder_to_offset_mm(enc_now,
  spawn_enc) -> float` (реэкспорт `FACTOR_MM`/`BELT_UX`/`BELT_UY` из
  `Services.robot_comm.core.registers` — НЕ копировать числа)
- `Services/line_sim/core/layered_object.py` — `LayeredObject` (список слоёв,
  паспорт, метод `render(rng) -> np.ndarray RGBA`)
- `Services/line_sim/core/preset.py` — `ScenePreset` (Pydantic-конфиг: каталог
  классов, диапазон углов, список слоёв-дефектов + вероятности) — по образцу
  `Services.dataset_gen.core.config.GeneratorConfig` (`from_yaml`/`from_dict`)
- `Services/line_sim/README.md`, `STATUS.md`, `DECISIONS.md`
- `Services/line_sim/tests/__init__.py`, `tests/test_belt.py`,
  `tests/test_layered_object.py`, `tests/test_preset.py`

**Steps:**
1. Загрузить и применить skill `module-contract` (new-full) — README + Protocol +
   Pre/Post в докстрингах + contract-тесты, как требует STRICT-канон проекта для
   новых модулей.
2. `interfaces.py`: `SceneCompositor` Protocol — методы, достаточные для Task 3.3–3.4
   (не более: `spawn_stream_tick(now_encoder, rng) -> list[ObjectPassport]` не нужен
   на этом уровне — конкретный спавн-луп это Task 3.3; здесь только контракт «дать
   сцену» — `render(now_encoder, camera_rect) -> tuple[np.ndarray, list[ObjectPassport
   в кадре]]`).
3. `core/belt.py`: `encoder_to_offset_mm` — чистая функция, использующая ТОЧНО ту же
   формулу трекинга, что `SimJournal._residual_mm`/Lua (`trav = (enc_now - job_enc) *
   FACTOR_MM`) — это не совпадение, это ОДИН И ТОТ ЖЕ инвариант в третьем месте
   (Lua/прошивка, `SimJournal`, здесь) — импортировать константы, не переопределять.
4. `core/layered_object.py`: `LayeredObject.render()` — для каждого слоя в порядке
   (base → augmented-варианты → defect-вариант, если активен): взять RGBA-спрайт
   (источник — `sprite_source`, реализация загрузки — Task 3.2), повернуть
   (`dataset_gen.core.compose.rotate_expand`), обрезать (`crop_to_alpha`),
   скомпоновать поверх предыдущего слоя (`composite`, БЕЗ фона — фон кладёт
   `SceneCompositor`). Pre/Post в докстрингах: Pre — все слои одного паспорта имеют
   согласованный `angle_deg`; Post — итоговый RGBA не пуст (alpha есть хотя бы у
   одного пикселя).
5. Contract-тесты (независимый `tester` пишет по acceptance criteria ниже, БЕЗ
   доступа к Steps выше и к реализации).

**Acceptance criteria:**
- [ ] `from Services.line_sim import ObjectPassport, LayerSpec, LayeredObject,
      ScenePreset` — импортируется без ошибок, без обязательного `torch`/`PySide6`
      (только numpy/opencv/pydantic — как у `dataset_gen`).
- [ ] `encoder_to_offset_mm(enc_now=1000, spawn_enc=1000) == 0.0`;
      `encoder_to_offset_mm(enc_now=1000 + N, spawn_enc=1000) == N * FACTOR_MM`
      (значение `FACTOR_MM` берётся из `Services.robot_comm.core.registers.
      FACTOR_MM`, тест ИМПОРТИРУЕТ константу, а не хардкодит число дважды).
- [ ] `LayeredObject` с ОДНИМ статическим слоем (валидный RGBA-квадрат 64×64,
      непрозрачный по центру) и `angle_deg=0` рендерит RGBA-массив с ненулевой альфой
      хотя бы в одном пикселе.
- [ ] `LayeredObject` с ОДНИМ слоем и `angle_deg=90` даёт РАЗНЫЙ (по пиксельной
      сумме несимметричного тестового спрайта) результат, чем `angle_deg=0` —
      поворот реально применяется, не игнорируется.
- [ ] `ScenePreset.from_dict({...минимальный валидный конфиг...})` создаётся без
      исключения; `ScenePreset.from_dict({})` (пустой) бросает понятную ошибку
      валидации (Pydantic), а не падает на непонятном `AttributeError` ниже по стеку.
- [ ] Слой в режиме `"defect"` с вероятностью `1.0` ВСЕГДА заменяет базовый вариант
      (детерминированный тест на границе: prob=1.0 → 100% замен из 20 рендеров;
      prob=0.0 → 0% замен из 20 рендеров — не мерить промежуточные вероятности,
      только границы, per STRICT-канон "числа теста рядом с дефолтом").
- [ ] `Services/line_sim/README.md` присутствует и описывает публичный контракт
      (символы из `interfaces.py`); `STATUS.md` и `DECISIONS.md` присутствуют
      (project rule #2).

**Out of scope:** реальный каталог `real_letters_disk` (Task 3.2), спавн-луп/поток
объектов во времени (Task 3.3), подключение к `LineSimCameraPlugin` (Task 3.4),
фотометрия (Ф4 — фотометрия применяется к ГОТОВОЙ сцене, не к отдельным слоям, см.
`dataset_gen` докстринг про «шов вклейки»).
**Edge cases:** слой без альфа-канала (RGB вместо RGBA) — явная ошибка на загрузке, не
тихий крэш глубже; пустой список слоёв в `LayeredObject` — `ValueError` с понятным
текстом.
**Dependencies:** Task 0.1 (нужны `FACTOR_MM`/`BELT_UX`/`BELT_UY` из перенесённого
`core/registers.py`).
**Module contract:** new-full.

---

### Task 3.2 — Контент пресета `real_letters_disk` + дефект-слой

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** `ScenePreset` из Task 3.1, наполненный реальным каталогом дисков-букв
(`Services/dataset_gen/presets/real_letters_disk.yaml` + уже вырезанные RGBA-эталоны),
плюс минимум один дефект-вариант с конфигурируемой вероятностью и ручным триггером
«выпусти брак сейчас».

**Files:**
- `Services/line_sim/presets/letters_disk.yaml` — новый пресет line_sim (ссылается
  на ТЕ ЖЕ каталоги спрайтов, что `dataset_gen/presets/real_letters_disk.yaml`, не
  копирует изображения)
- `Services/line_sim/core/catalog_bridge.py` — тонкая обёртка над
  `Services.dataset_gen.core.catalog.SpriteCatalog`/`imread_unicode` (переиспользование
  загрузки RGBA, Windows-safe non-ASCII путей — уже решённая проблема в dataset_gen,
  не решать заново)
- `Services/line_sim/tests/test_letters_disk_preset.py`

**Steps:**
1. Проверить актуальное содержимое `data/dataset_gen/ru_letters_real/sprites/`
   (создаётся `tools/cut_real_disks.py` по README dataset_gen) — если каталог пуст на
   момент задачи (эталоны реально не сняты владельцем), задокументировать это явно в
   `STATUS.md` line_sim как известное ограничение ("дефолтный контент отсутствует, см.
   `Services/dataset_gen/README.md` → `cut_real_disks`") и использовать
   ЛЮБОЙ непустой fixture-каталог (2-3 класса) для тестов — не блокировать задачу
   отсутствием реальных фото.
2. `catalog_bridge.py`: обернуть `SpriteCatalog` (из `dataset_gen`) так, чтобы каждый
   класс каталога превращался в `LayerSpec(mode="static", sprite_source=...)` —
   переиспользовать `SpriteCatalog.load()`/`get_sprite()` целиком, не переписывать
   сканирование папок/meta.yaml.
3. Дефект-слой (v1, минимум один вариант — выбрать самый дешёвый в реализации):
   "повреждённый диск" — occlusion-пятно поверх готового слоя, реиспользуя
   `Services.dataset_gen.core.augment.apply_occlusion` (уже есть, тестирован) —
   применяется КАК ОТДЕЛЬНЫЙ `LayerSpec(mode="defect", ...)`, а не примешивается в
   фотометрию сцены (фотометрия — Ф4, общая для ВСЕХ объектов; дефект — свойство
   конкретного объекта, часть его паспорта).
4. Конфигурируемая вероятность дефекта (`defect_probability` в `sim.spawn`, дефолт
   0.0 — по умолчанию брак не появляется без явного включения) + программный хук
   «выпусти брак сейчас» (метод/команда, которую Task 3.3 и Task 6.1 вызовут —
   форсирует дефект на СЛЕДУЮЩЕМ заспавненном объекте, не на текущих).

**Acceptance criteria:**
- [ ] `ScenePreset.from_yaml("Services/line_sim/presets/letters_disk.yaml")`
      загружается без исключений и даёт `num_classes >= 1`.
- [ ] Объект, созданный с `defect=None` (паспорт), рендерится идентично (побитово)
      объекту без дефект-слоя.
- [ ] Объект, созданный с `defect="damaged"` (или выбранным именем дефекта),
      рендерится ОТЛИЧНО (по пиксельной разности > 0) от объекта без дефекта при
      ТОЙ ЖЕ базовой букве/угле.
- [ ] С `defect_probability=1.0` — 20 из 20 спавненных (через `SceneCompositor`-стаб
      или напрямую фабрику объектов) объектов имеют непустой `passport.defect`;
      с `defect_probability=0.0` — 0 из 20.
- [ ] Ручной хук «выпусти брак сейчас», вызванный один раз перед спавном ОДНОГО
      объекта при `defect_probability=0.0`, даёт объекту `passport.defect` не
      `None` — форсированный брак работает независимо от вероятности.

**Out of scope:** несколько типов дефектов одновременно (v1 — один тип, «расширить
позже» тривиально по контракту `LayerSpec`, но не строить впрок); UI кнопки (Ф6).
**Edge cases:** каталог с ровно одним классом (граничный случай `SpriteCatalog`,
уже обработанный в `dataset_gen` — не переоткрывать, только проверить, что line_sim
не ломает это поведение).
**Dependencies:** Task 3.1.
**Module contract:** impl-only (наполняет модуль из 3.1, не меняет его публичный
контракт).

---

### Task 3.3 — Поток спавна объектов на ленте

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** непрерывный поток объектов появляется на ленте с конфигурируемым
интервалом, каждый получает паспорт и `spawn_encoder` (снимок текущего значения из
канала Ф2.2), движется по формуле Task 3.1, и удаляется, покинув видимую зону.

**Files:**
- `Services/line_sim/core/spawner.py` — `ObjectSpawner` (держит список активных
  `LayeredObject`+паспорт, `tick(now_encoder, now_wall_s, rng) -> None`,
  `active_objects() -> list[...]`)
- `Services/line_sim/tests/test_spawner.py`

**Steps:**
1. `ObjectSpawner.tick()`: по интервалу (диапазон `sim.spawn.interval_s`, случайная
   выборка в границах — как `_uniform_val` в `dataset_gen`) решает, спавнить ли новый
   объект; при спавне — выбрать случайный класс (или по конфигу — стрим одинаковых,
   см. vision.md "поток одинаковых или с вариациями"), случайный угол, дефект по
   `defect_probability`/форс-хуку (Task 3.2), запомнить `spawn_encoder=now_encoder`.
2. Despawn: объект удаляется, когда его смещение (`encoder_to_offset_mm`) выходит за
   границу видимой зоны сцены (конфигурируемая длина сцены, например
   `sim.camera.scene_length_mm`).
3. Пауза: `ObjectSpawner.set_paused(bool)` — при паузе `tick()` не спавнит новые
   объекты, НО существующие продолжают двигаться (пауза потока ≠ остановка ленты —
   это два разных контрола, ремонт ленты отдельно в Ф2.1/VfdDriver).
4. Автор пишет hazard-тест: `tick()` вызывается из потока-продюсера кадров (Task 3.4)
   потенциально с высокой частотой (до fps камеры) — убедиться, что список активных
   объектов не мутируется во время итерации (типичная ловушка `list` vs `deque`/копия
   при рендере).

**Acceptance criteria:**
- [ ] С `interval_s=[0.5, 0.5]` (фиксированный интервал для детерминизма теста) и
      `now_wall_s`, продвигаемым вручную на 2.5с шагами по 0.5с — после 5 шагов
      создано РОВНО 5 объектов (не 4, не 6 — граница по включению/исключению
      зафиксирована тестом).
- [ ] Объект с `spawn_encoder=0`, `scene_length_mm=100`, `FACTOR_MM` — реальное
      значение из `robot_comm` — удаляется из `active_objects()` ровно когда
      `encoder_to_offset_mm(now_encoder, 0) > 100` (граничный тест на encoder тик
      до/после порога).
- [ ] `set_paused(True)` останавливает появление НОВЫХ объектов (0 новых за 5
      секунд симулированного времени), но НЕ убирает уже активные из
      `active_objects()`, и их позиция продолжает пересчитываться при росте
      `now_encoder`.
- [ ] Форс-хук «выпусти брак сейчас» (из Task 3.2), вызванный на паузе, НЕ спавнит
      объект немедленно — только помечает следующий реальный спавн (после снятия
      паузы) как дефектный. (Если это архитектурно неверно для UX — альтернатива:
      форс-хук спавнит объект НЕМЕДЛЕННО, игнорируя паузу и интервал; выбрать ОДНО
      поведение, задокументировать в docstring `ObjectSpawner`, и tester пишет тест
      именно под выбранное — это решение фиксируется тут, Developer выбирает и
      объясняет почему в PR-описании).

**Out of scope:** привязка к камере/`produce()` (Task 3.4); GUI-контролы (Ф6) — здесь
только программный API.
**Edge cases:** `interval_s` с `lo > hi` (некорректный конфиг) — валидировать на
входе, не давать тихий `numpy` `ValueError` из недр `rng.uniform`.
**Dependencies:** Task 3.1 (обязательно), Task 2.2 (нужен реальный источник
`now_encoder` для e2e, но unit-тесты `ObjectSpawner` могут подавать `now_encoder`
вручную и не блокированы на 2.2).
**Module contract:** impl-only.

---

### Task 3.4 — Подключить движок к `LineSimCameraPlugin.produce()`

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** заглушка из Task 1.1/2.2 заменена на реальный рендер: `produce()` вызывает
`SceneCompositor.render()` (объединяет `ObjectSpawner` + `LayeredObject` + фон),
возвращает кадр с реальными объектами, и прикрепляет паспорта объектов, попавших в
кадр, как sidecar-метаданные на item (задел для Ф5).

**Files:**
- `Plugins/sources/line_sim_camera/plugin.py` — заменить placeholder-рендер
- `Services/line_sim/core/scene_compositor.py` — `SceneCompositor` (реализация
  Protocol из 3.1: держит `ObjectSpawner`, фон-заглушку/будущий фон-фото, вызывает
  `LayeredObject.render()` для каждого активного объекта, компонует через
  `dataset_gen.core.compose.composite`)

**Steps:**
1. `SceneCompositor.render(now_encoder, camera_rect) -> (frame_rgb, passports_in_view)`
   — для каждого `active_object` в `ObjectSpawner`: вычислить X-позицию
   (`encoder_to_offset_mm` → пиксели через `px_per_mm`), Y — фиксированная линия
   ленты (v1, вид сверху — одна полоса); скомпоновать через `composite()` поверх
   фона (v1 — сплошной цвет/простая текстура, фото реальной ленты — не блокирует эту
   задачу, может быть отдельным follow-up); вернуть также список паспортов объектов,
   чей bbox пересекается с `camera_rect`.
2. В `LineSimCameraPlugin.produce()`: вызвать `render()`, положить `frame_rgb`
   (конвертировать в BGR — конвенция прототипа, см. комментарий в рецепте про
   `color_convert`) в `item["frame"]`; положить `passports_in_view` в
   `item["sim_truth"]` (новое имя поля — зафиксировать здесь как контракт, Ф5.2
   будет его читать) как `list[dict]` (паспорт через `to_dict()`/`asdict`, Dict at
   Boundary).
3. Убедиться, что `sim_truth` — ЧИСТО ДОПОЛНИТЕЛЬНОЕ поле item (Dict at Boundary,
   project rule #1) — не заменяет ни одно существующее поле, которое ждёт
   `color_convert`/`roi_crop` и далее по цепочке.

**Acceptance criteria:**
- [ ] С хотя бы одним активным объектом (форсировать спавн в тесте), кадр из
      `produce()[0]["frame"]` НЕ идентичен кадру без объектов (пиксельная разница
      > 0 в области ожидаемой позиции объекта).
- [ ] `produce()[0]["sim_truth"]` — список словарей, каждый с ключами как минимум
      `object_id`, `class_name`, `angle_deg`, `defect` (значение `None`/строка).
- [ ] Объект вне `camera_rect` (спавнен, но ещё не доехал до видимой зоны) НЕ
      попадает в `sim_truth` этого кадра.
- [ ] Существующие обязательные поля item (`frame`, `camera_id`, `seq_id`,
      `frame_id`, `timestamp`, `width`, `height`, `channels`, `dtype`) присутствуют
      без изменений формы (регрессия к контракту Task 1.1 не допускается).
- [ ] Полный прогон `python multiprocess_prototype/run.py hikvision_letter_robot`
      (`sim.enabled: true`) 30 секунд — дисплей `line_sim` показывает движущиеся
      диски с буквами (визуальная проверка через
      `mcp__backend-ctl__introspect_registers`/скриншот дисплея, если доступно, либо
      описание проверяющего с числом уникальных объектов, увиденных за прогон, > 0).

**Out of scope:** фотометрия (Ф4.3), настройки fps/размер/цвет (Ф4.1), ROI (Ф4.2) —
`camera_rect` здесь фиксированный конфиг, не live-управляемый.
**Edge cases:** `ObjectSpawner` пуст (0 активных объектов) — `produce()` возвращает
валидный кадр (просто фон, без исключений).
**Dependencies:** Task 1.1 (плагин-заглушка), Task 3.2, Task 3.3.
**Module contract:** impl-only.
