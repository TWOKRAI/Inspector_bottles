# Phase 3 — Сбор с линии

Часть плана [`plan.md`](plan.md). Цель фазы: кадр с линии попадает в датасет одним кликом с живой камеры или
автоматически, когда инспекция отбраковала изделие. Это главная причина делать разметку своей, а не только внешней
(`constructor-layers.md:160`).

**Честная стартовая точка (сверено 2026-09-26):** «кадров брака из результатов инспекции» сегодня **нет** —
`storage` пишет в `detections` строку без картинки (`Plugins/io/database/schemas.py:27-46`), `inspection_result` несёт
`{action, defect_count, total_inspected, total_rejected, reject_rate}` без кадра и боксов
(`Plugins/control/robot_control/plugin.py:186-192`), вкладки «результатов с кадрами» в GUI нет (греп
`defect|reject` по `multiprocess_prototype/frontend` находит только диалоги и формы). Поэтому «В датасет из
результатов» в этом плане = **автосбор отбраковок на бэкенде** + фильтр «источник: reject» в браузере (2.3).

**Канон:** как в Ф1. Обе задачи фазы — с живым стендом; один live-трек на бэкенд.

---

### Task 3.1 — Плагин `dataset_capture`: кольцо сырых кадров, захват по команде, автосбор отбраковок

**Level:** Senior · **Assignee:** teamlead · **Module contract:** new-lite (`Services/dataset/plugin/capture.py`) · **Layer:** services + prototype
**Handoff:** `investigator`(разведка Step 1, отчёт) → `tester`(RED) → `teamlead`(GREEN) → `reviewer`

**Step 1 — разведка до кода (отчёт в задачу, решение лидом):**
1. Где в `inspection_full` и `hikvision_inspect` встречаются сырой кадр и вердикт: несёт ли элемент процесса
   `inspector` исходный `frame` (не маску, не отрисованный кадр)? Если нет — Join по `seq_id` (режим Join рецептов,
   риск таймаута P1 из `dataset-circle-capture.md`) или плагин в процессе камеры с вердиктом по отдельному проводу.
2. Несёт ли сообщение дисплея GUI `seq`/`frame_id` (`multiprocess_prototype/frontend/bridge_impl.py:103` — что в
   `msg_dict`)? От ответа зависит, захватывает ли клик «тот самый» кадр или «последний сырой».
3. Разрешены ли провода рецепта в процесс из подключаемого фрагмента `dataset.yaml` (`backend/topology/tests/test_base_merge.py`), или плагин
   ставится в процесс рецепта.
4. Разрешение и формат кадра камеры на линии (Hikvision) — для литерала памяти кольца.

**DESIGN (уточняется Step 1, не переписывается):**
- `DatasetCapturePlugin`: вход `frame` (сырой, `image/bgr`), опц. вход `verdict` (dict с `action`), опц. вход
  `detections` (рамки классического детектора — для Ф5, хранятся в `sources.meta_json` как `suggested`).
- Кольцо последних `ring_size` кадров (дефолт 8) с `seq_id`/временем; копия ndarray на входе (буфер SHM не
  удерживается — иначе заём кадра висит).
- Команда `dataset_capture {seq?: int, note?: str}` → кадр из кольца (по `seq` или последний) кодируется
  (`capture_format` png|jpeg, дефолт png) и вставляется через `DatasetStore.add_image_bytes` c источником
  `capture` (`ref` = `<process>.<plugin>`, рецепт, `seq`, время, `session`). Ответ `{success, image_id, duplicate}`
  или `{error: "seq_not_in_ring", oldest, newest}`.
- Автосбор: регистр `auto_capture` ∈ `off|rejects` (дефолт `off`), `max_per_minute` (дефолт 6). На фронте вердикта
  `reject` кадр сохраняется с источником `reject` и копией вердикта в `meta_json`. Превышение лимита — счётчик
  `auto_dropped`, не очередь.
- Сессия захвата: `session` = `<recipe>-<время старта плагина>`; ключ группы для сплита (4.3).
- Состояние: `dataset.capture.<process>.<plugin> = {ring, ring_bytes, last_seq, captured, auto_captured, auto_dropped}`
  — по нему GUI (3.2) находит, куда слать команду.
- Писатель вставляет только новые снимки и строки `sources`; строки `labels` существующих снимков **не трогает**
  (решение в `plan.md` — проверяется тестом ниже).
- Рецепты: провод в `inspection_full.yaml` и `hikvision_inspect.yaml` (по результату Step 1); остальные рецепты не
  меняются.

**FILES:** 1) `Services/dataset/plugin/capture.py` 2) `Services/dataset/plugin/capture_registers.py`
3) `Services/dataset/store.py` (`add_image_bytes`) 4) `multiprocess_prototype/backend/topology/inspection_full.yaml`
5) `multiprocess_prototype/recipes/hikvision_inspect.yaml` 6) `Services/dataset/README.md`.

**Acceptance criteria:**
- [ ] Unit (синтетические кадры с `seq` 1..20, `ring_size=8`): `dataset_capture {seq: 15}` → снимок с байтами кадра 15
      (декодированный PNG равен исходному массиву побайтно); `{seq: 3}` → `seq_not_in_ring`, `oldest == 13`.
- [ ] Unit: 30 вердиктов `reject` за 10 с при `max_per_minute=6` → `auto_captured == 6`, `auto_dropped == 24`.
- [ ] Unit: снимок уже размечен (`rev=3`), тот же кадр захвачен повторно → `duplicate: true`, у снимка `rev == 3`,
      `boxes_json` не изменился, строк `sources` стало на 1 больше.
- [ ] Живой стенд `inspection_full` (синтетический источник или камера), 60 с при 25 кадр/с: `ring_bytes` в
      состоянии = `ring_size × байты кадра` (литерал из Step 1, ±5 %); `fps` пайплайна до/после включения плагина —
      падение ≤ 5 % (числа в отчёте).
- [ ] Живой стенд: `backend_ctl send_command(<process>, dataset_capture)` → `dataset_list {filter: {source_kind:
      "capture"}}` показывает снимок ≤ 2 с.
- [ ] Живой стенд, `auto_capture=rejects`: за 60 с число снимков с источником `reject` = `min(число фронтов reject,
      6 в минуту)` (фронты — из счётчика `robot_control`).
- [ ] Два писателя: 200 захватов подряд во время `dataset_import` 1000 файлов → ни одной ошибки `database is locked`
      в ответах; максимальное ожидание блокировки — число в отчёте (не утверждение).

**Hazard-тесты автора:** кольцо под записью (data-поток) и чтение по команде (system-поток) — под замком, без
разрыва кадра (тест на целостность паттерна в кадре при параллельных записи и захвате); кодирование PNG не под
замком кольца (иначе data-поток ждёт кодирования).

**Инъекции:**
| Сломать | Должны упасть |
|---|---|
| хранить ссылку на буфер кадра вместо копии | тест целостности паттерна (кадр 15 содержит пиксели кадра 23) |
| лимит частоты не применять | тест `auto_captured == 6` |
| повторный захват переписывает `labels` | тест «rev == 3» |
| кодировать под замком кольца | hazard «data-поток ждёт» (время `process()` > литерала) |

**Out of scope:** загрузка кадров с клиента; ретенция захваченных (бюджет — 1.4); подсказки (Ф5).
**Dependencies:** 1.1 (для `session` в сплите — 4.3 читает поле, не зависит от задачи).

---

### Task 3.2 — «В датасет» у живой камеры и счётчик входящих

**Level:** Middle · **Assignee:** developer · **Module contract:** impl-only · **Layer:** services + prototype
**Handoff:** `tester`(RED) → `developer`(GREEN) → `reviewer`

**Goal:** оператор видит интересный кадр и одним кликом (или клавишей) отправляет его в датасет, не уходя со
вкладки камеры.

**DESIGN:**
- `Services/dataset/gui/capture_button.py` — кнопка + счётчик «входящих сегодня / не размечено», порты — те же
  `AnnotationPorts`; куда слать команду — из `dataset.capture.*` в состоянии (если захватчиков несколько —
  выпадающий список по узлу, дефолт — первый).
- Если сообщение дисплея несёт `seq` (ответ Step 1 задачи 3.1) — команда с `seq` показанного кадра, иначе без него,
  и подсказка у кнопки «последний сырой кадр».
- Место в прототипе: рядом с видом камеры — это прикладной код инспекции (`constructor-layers.md` → слой prototype);
  в конструкторе — отдельный виджет `dataset.capture_button`, который раскладка ставит рядом с камерой.
  `frontend/app.py` не трогать; если без него не встраивается — стоп и вопрос лиду.
- Ответ: «Сохранено» с миниатюрой (через `ports.files`) 2 с; `duplicate` — «уже в датасете»; нет захватчика в
  рецепте — кнопка неактивна с подсказкой «в рецепте нет `dataset_capture`».

**FILES:** 1) `Services/dataset/gui/capture_button.py` 2) файл вида камеры прототипа (определяет Step 1 3.1; один файл)
3) тест.

**Acceptance criteria:**
- [ ] pytest-qt, фейковые порты: клик → ровно одна команда `dataset_capture` на адрес из состояния; двойной клик за
      300 мс → одна команда (защита от дребезга).
- [ ] Рецепт без захватчика → кнопка `isEnabled() == False`, подсказка содержит `dataset_capture`.
- [ ] Живой стенд: клик в собранном GUI → снимок в `dataset_list` ≤ 2 с, счётчик «входящих» вырос на 1.
- [ ] UI-поток не блокируется командой: бэкенд отвечает с задержкой 2 с (тестовый хук) → тики таймера идут.

**Инъекции:** убрать защиту от дребезга → тест двойного клика; адрес команды захардкодить → тест «адрес из
состояния» (фейк с другим именем процесса).
**Out of scope:** выделение области на кадре перед захватом (размечается потом на холсте).
**Dependencies:** 3.1, 2.1.
