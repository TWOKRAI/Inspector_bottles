# code-reader-gui — Фаза 1 — показ

Шапка плана, решения, общие правила и лимит итераций: [`../code-reader-gui.md`](../code-reader-gui.md). Статус задач пишется один раз — в разделе «Порядок выполнения» шапки.

### Task 1.1 — ⚑ Базовый прогон `qr_reader_sdk_demo` на новой камере
**Level:** Senior (стенд, не делегируется) · **Assignee:** лидер; сбор чисел — `haiku` · **Gate:** `heavy`
**Goal:** доказать, что существующий канал SDK работает на `MV-ID3013PM-06M-WBPF-5M-OD` (S/N `00DB2156580`,
`V4.0.2.R 260729`, `GEV`) без единой правки кода — до того как на нём строить.
**Что переиспользуем:** рецепт `multiprocess_prototype/recipes/qr_reader_sdk_demo.yaml` как есть; `backend_ctl`
(`state_get_subtree processes.reader_sdk.state.code_reader_sdk`, `send_command reader_sdk get_status`);
`Services/code_reader/tools/mvcr_probe.py` для поиска прибора.
**Что НЕ пишем:** ничего — задача без кода. Ни новых зондов, ни правок рецепта.
**Files:** нет (числа — в раздел «Итоги» этого плана и в `Services/code_reader/STATUS.md` в Task 3.2).
**Steps:**
1. `mvcr_probe.py` — прибор найден по `192.168.1.10`, модель/серийник совпали.
2. Бэкенд `BACKEND_CTL=1`, рецепт `qr_reader_sdk_demo`; `device_state == running`, `device` = IP/модель/S/N.
3. ⚑ Владелец: 20 нажатий триггера (код в поле: ~12; без кода: ~4; прикрытый код: ~4).
4. Снять: `frames`, `total_reads`/`no_reads`/`bad_reads`, `errors`, `dropped`, непрерывность `trigger_index`,
   `frame_pickle_fallbacks`, размер item без кадра, `pixel_format`, `width×height`, `last_quality`.
5. `release_device` → `released: true`; время до `device_held: false` — число.
#### Приёмка
**Acceptance criteria:**
- [ ] 20 срабатываний → 20 item, `trigger_index` без пропусков, `errors 0`, `dropped 0`.
- [ ] `pixel_format == "jpeg"`, кадр `1024×1280` (или фактическое — записать; от него зависит дисплей 1.2).
- [ ] Счётчики ok/no/bad сошлись с тем, что делал владелец (его счёт — в отчёте).
- [ ] `frame_pickle_fallbacks 0` (кадр ушёл в SHM).
**Out of scope:** TCP-нода `reader_tcp` (на новом приборе TCP Client не настроен — её `sink_state` только
записать), параметры прибора (Task 2.x).
**Провал** любой строки → `investigator`, план стоит; гипотезы не чиним наугад.

### Task 1.2 — [VERTICAL SLICE] Кадр с обводкой и текстом в дисплее рецепта
**Level:** Middle+ · **Assignee:** `developer` (sonnet); 3-я итерация → `teamlead` · **Gate:** `light` / `medium`
**Handoff:** `reviewer`(stage 0) → `tester`(RED, worktree) → `developer`(GREEN) → `reviewer`
**Goal:** срабатывание прибора → в дисплее `main` рецепта `qr_reader_sdk_demo` кадр с цветной рамкой по
углам кода, текстом кода и строкой «статус · ok/no/bad».
**Что переиспользуем:**
- `Plugins/render/overlay_draw/plugin.py` — отрисовка линий/точек/подписей и таблица цветов;
- механизм `blueprint.displays` + top-level `displays:` (образец — `recipes/line_filter_inspect.yaml:102–145`);
- `CodeRead.corners` / `status` и счётчики `_snapshot()` в `Services/code_reader/plugin/sdk_plugin.py`;
- SHM-путь кадра и claim check — без изменений (ADR-CR-007).
**Что НЕ пишем и почему:** плагин `code_view` (готовый `overlay_draw` рисует то же); новую вкладку и виджет
(дисплеи рецепта уже есть); третий рецепт (расширяем существующий); join-режим и второй провод (`overlay`
едет в том же item); конвертер gray→BGR отдельным плагином (`color_convert` серый 2D не принимает — две
строки внутри `overlay_draw` дешевле нового процесса).
#### DESIGN
**DESIGN:**
- `sdk_plugin.py::_build_item` — ключ `overlay` (чистая функция `_overlay(frame, counters) -> dict` в том же
  файле): для каждого кода 4 отрезка `corners[i] → corners[(i+1)%4]` в `lines`, цвет BGR: ok `(0,200,0)`,
  bad_code `(0,0,255)`; одна точка в `corners[0]` с `label` = текст кода (у bad_code — `"bad_code"`);
  точка `(10, 30)` с `label` = `"<status> · ok N / no N / bad N"` (счётчики — с учётом `reset_stats`, те же
  числа, что в дереве). `no_code` → только строка статуса. В `outputs` — `Port("overlay", dtype="dict",
  optional=True)`. Остальная форма item не меняется (TCP-совместимость, ADR-CR-006).
- `overlay_draw/plugin.py`: `inputs[0].dtype` → `"image/*"`; в `process` перед рисованием
  `if canvas.ndim == 2: canvas = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)`; `cv2.putText` берёт масштаб из
  `self._reg.label_scale`, толщину `max(1, round(label_scale * 2.5))`. Выход `frame` — BGR, как раньше.
- `overlay_draw/registers.py`: `label_scale: float = 0.4`, `FieldMeta("Размер подписей", min=0.2, max=4.0)`.
- Рецепт: процесс `draw` (`GenericProcessApp`, `chain_targets: [gui]`, плагин `overlay_draw`,
  `label_scale: 1.2`); провод и дисплей — решение 3; `gui_positions` для `draw.overlay_draw`.
**Files:**
1. `Services/code_reader/plugin/sdk_plugin.py`
2. `Plugins/render/overlay_draw/plugin.py`
3. `Plugins/render/overlay_draw/registers.py`
4. `multiprocess_prototype/recipes/qr_reader_sdk_demo.yaml`
5. `multiprocess_prototype/recipes/tests/test_qr_reader_sdk_demo.py`
6. `multiprocess_prototype/frontend/forms/tests/snapshots/catalog_register_fields.txt` (строка `overlay_draw.label_scale`)
Тестовые файлы `tester`: `Services/code_reader/tests/test_sdk_overlay.py`, `Plugins/render/overlay_draw/tests/test_gray_and_scale.py`.
**REDS (предсказание до кода):**
- `Services/code_reader/tests/test_sdk_overlay.py::*` — ключа `overlay` нет;
- `Plugins/render/overlay_draw/tests/test_gray_and_scale.py::*` — серый 2D рисуется одним каналом, `label_scale` нет;
- `multiprocess_prototype/frontend/forms/tests/test_catalog_kind_roundtrip.py::test_resolve_kind_stable_across_json_roundtrip_for_all_register_fields` — снапшот без `label_scale`;
- `multiprocess_prototype/recipes/tests/test_qr_reader_sdk_demo.py::*` — новые тесты на `draw`/провод/дисплей.
#### Приёмка
**Acceptance criteria:**
- [ ] Item с одним кодом `ok` (углы `(100,100),(300,100),(300,300),(100,300)`) → `overlay.lines` — ровно 4
      отрезка по этим точкам, цвет `(0,200,0)`; есть подпись с текстом кода в `(100,100)`.
- [ ] Кадр `bad_code` → цвет `(0,0,255)`, подпись `"bad_code"`; кадр `no_code` → `lines == []`, строка статуса есть.
- [ ] Строка статуса содержит три числа, равные `total_reads`/`no_reads`/`bad_reads` дерева на том же проходе;
      после `reset_stats` — нули.
- [ ] `overlay` проходит `json.dumps`; в item по-прежнему нет `bytes`; размер item без кадра с 3 кодами ≤ 2 048 Б.
- [ ] `overlay_draw`: серый кадр `uint8 (1024,1280)` + `overlay` с линией цвета `(0,0,255)` → выход
      `(1024,1280,3)`, пиксель на линии `== (0,0,255)`, пиксель вне линии равен исходной яркости во всех
      трёх каналах.
- [ ] `overlay_draw` с `label_scale 1.2`: число ненулевых пикселей разности «с подписью − без» в полосе подписи
      больше, чем при `0.4` (литералы порогов — у tester).
- [ ] Прежнее поведение `overlay_draw` на BGR-кадре без `label_scale` в рецепте — пиксель в пиксель как до
      правки (эталон — выход текущего кода на фиксированном входе, снят tester'ом до реализации).
- [ ] Рецепт: gate-валидатор проходит; `are_ports_compatible(image/gray → image/*)`; провод
      `reader_sdk.code_reader_sdk.frame → draw.overlay_draw.frame`; дисплей `main` на `draw.overlay_draw.frame`;
      `reader_sdk.chain_targets` по-прежнему содержит `gui`.
- [ ] Рецепты с `overlay_draw` (`line_filter_inspect`, `letter_angle_inspect`, `letter_robot_sim`,
      `hikvision_letter_robot`, `dataset_circle_capture`) проходят свои тесты без правок.
**Break-injection (лидер, до прогона записать набор падений):** цвет по статусу константой; углы без
замыкания `(i+1)%4`; `overlay` без счётчиков; gray→BGR снят; `label_scale` игнорируется; порт обратно в
`image/bgr`.
#### Ловушки
**TRAPS:**
- Гипотеза H1, не проверена: провод доставляет в `draw` **весь** item (с `overlay`), а не только порт `frame`.
  Первый красный шаг developer'а — найти и процитировать место в framework, где data-сообщение собирается
  из item (claim check `frame_shm_middleware.py::strip_and_write`); не подтвердилось → стоп, `ESCALATION -> teamlead`.
- Гипотеза H2: незаподключённый вход `overlay` у `overlay_draw` не валит `validate_recipe_blueprint`.
- `test_sdk_нода_отдаёт_кадр_в_gui` проверяет `chain_targets == ["gui"]` — если провод меняет `chain_targets`,
  менять ассерт на «содержит `gui`», не удалять.
- Golden-снапшоты рецептов `phone_sketch`, `hikvision_letter_robot` — `overlay_draw` в последнем есть:
  прогнать, при расхождении — стоп и вопрос лидеру (память: `feedback_a_decision_orphans_what_encoded_the_previous_one.md`).
**Out of scope:** настройки (Ф2), живой стенд (3.1), latency «триггер → экран» (нет метки времени триггера на ПК).
