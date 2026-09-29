# Инвентарь крупных грузов в data-очередях и разбор `SHM fallback failed` (Task 4.0)

**План:** [`transport-single-policy`](../../plans/transport-single-policy.md), Фаза 4, Task 4.0.
**Дата:** 2026-09-29. **Исполнитель:** investigator (только диагностика, код не правился).
**Стенд:** Windows 10 (spawn), ветка `feat/qr-code-reader` на `78d587c8`+ (после ADR-SRM-017).
**Метод:** `sitecustomize.py` с хуком на `multiprocessing.queues.Queue.put`, считает
`len(ForkingPickler.dumps(msg))` тем же pickler'ом, что у feeder. Очередь определялась по
`process_name`/`queue_type` из кадра `QueueRegistry.send_to_queue`. Скрипты в scratchpad сессии, в репо не попали.

**Прогоны:**
- `inspection_full`: три прогона (60 / 30 / 30 с), 1734 / 1094 / 1103 кадров. Остановка 1.93 / 1.18 / 1.55 с.
- `letter_robot_sim` + `apps/line_sim`: один прогон (60 с), 1443 кадра.
- Хвостов процессов нет.

Размеры между прогонами совпадают до 1–2 Б (min == max), поэтому avg ≈ max.

## 1. Таблица data-очередей

### inspection_full

| очередь | отправитель | крупный ключ (тип) | байт msg avg / max | кто кладёт | почему не через SHM |
|---|---|---|---|---|---|
| processor/data | camera_0 | — (`frame` ушёл ссылкой) | 454 / 454 | — | claim check работает |
| renderer/data | processor | `mask` ndarray(480,640) uint8, 307 364 | 307 853 / 307 855 | `Plugins/processing/blob_detector/plugin.py:106` | claim check берёт только ключ `frame` (`frame_shm_middleware.py:660`) |
| inspector/data | processor | `mask` | 307 854 / 307 855 | там же | то же |
| storage/data | inspector | `mask` | 307 979 / 307 980 | транзит: `robot_control/plugin.py:153/209` (`return item`) | то же + item не обрезается по проводам |
| gui/data | renderer | `rendered_frame` ndarray(480,640,3) uint8, 921 766 + `mask` 307 364 | 1 229 554 / 1 229 554 | `Plugins/render/render_overlay/plugin.py:163`; маска — транзит | то же |
| gui/data | inspector | `mask` | 307 975 / 307 976 | транзит | то же |

- **Откуда у `gui/data` в среднем 745 КБ (замер CTO на Mac):** в очередь поровну идут 1 229 554 Б и 307 975 Б, среднее 768 764 Б. Max на Mac был 1 229 548 Б, на 6 Б меньше.
- **Лишняя запись у renderer:** исходный `frame` renderer заново пишет в своё кольцо (`frame_boundary_crossings` = 1353), а GUI его не показывает — дисплей привязан к `rendered_frame`.

### letter_robot_sim

| очередь | отправитель | крупный ключ | байт avg / max | кто кладёт | почему не через SHM |
|---|---|---|---|---|---|
| vision/data | camera_0 | — | 448 / 448 | — | claim check работает |
| line/data, recog/data, draw/data, maskview/data | vision | `mask` ndarray(481,800) uint8, 384 964 | 385 452…385 456 | `Plugins/processing/hsv_mask/plugin.py:88`, `morphology/plugin.py:78`; `circle_detector` оставляет маску (`keep_mask: true`, `circle_detector/plugin.py:127`) | только `frame` |
| gui/data | draw | `mask` (транзит) | 385 611 / 385 612 | транзит | то же |
| gui/data | maskview | `mask` (транзит; `frame` едет через SHM) | 385 460 / 385 460 | `mask_to_frame/plugin.py:58` (`{**item, "frame": bgr}`) | то же |
| recog/data, draw/data | line | — | 391 / 390 | — | `line_filter` заменяет item |
| mjpeg/data (сим) | camera | — | 424 | — | claim check работает |

**Не измерено:** `recog`→`gui`/`layout` и `phone`. От них за прогон не пришло ни одного сообщения: кроп срабатывает только по триггеру линии, а phone стоит с `auto_start: false`.

**Объём pickle на кадр:**
- `inspection_full`: 2 461 215 Б, то есть около 61 МБ/с при 25 fps.
- `letter_robot_sim`: около 2.31 МБ, то есть около 58 МБ/с.

**Вложенные ndarray:**
- Ниже верхнего уровня хук их не нашёл.
- Оговорка: симулятор `inspection_full` не даёт красных объектов, поэтому `contours`/`detections` пусты во всех 1500 последних строках БД. Список контуров cv2 — это список ndarray (N×1×2 int32 = 8N Б); с реальными дефектами он может перейти порог.

**Крупные сообщения вне data-очередей:**
- `ProcessManager→*/system`: до 33 260 Б (`inspection_full`).
- `gui/system`: до 56 051 Б (`letter_robot_sim`).
- По два сообщения больше 16 КБ за прогон.

Это не data-очереди. В приёмку «≤ порога» они не входят, и это нужно оговорить в Task 4.1.

## 2. `SHM fallback failed … '/output_frames_0'`

**На Windows не воспроизводится.** Четыре прогона дали 0 строк `SHM fallback failed | pickle-fallback | не восстановлен`. У всех процессов `frame_pickle_fallbacks` = 0, `frame_torn_reads` = 0, `middleware_dropped` = 0.

**Причина на POSIX — одно имя сегмента у всех процессов** (статика, уверенность высокая):
- `generic_process.py:207-213`: у каждого `GenericProcess` кольцо `slot="output_frames"`.
- `memory/platform/shm.py:221-232`, `_unique_base_name`: при `FW_SHM_OWNER_INCARNATION` = 0 (дефолт, `config_module/feature_flags.py:101`) на POSIX отдаёт голое `output_frames`, а на Windows — `output_frames_<pid>`.
- Проверено вызовом функции с подменой `is_windows`:
  - posix без флага: `['output_frames', 'output_frames', 'output_frames']`;
  - posix с флагом: `['output_fra_feb55d1d', 'output_fra_64283200']`.
- `create_shm_block` (`shm.py:248-262`) перед созданием зовёт `cleanup_stale_shm`. Тот делает unlink по имени, в том числе живого сегмента соседа.
- Первый завершившийся владелец делает unlink `/output_frames_N` через `close_memory` (`manager.py:406-420`), а остальные ещё читают ссылки в полёте.
- Строку печатает **читатель**: `restore_frame`, попытка 2, `frame_shm_middleware.py:629`.

**Совпадение с наблюдениями:**
- На ошибку жалуются именно читатели колец (processor, renderer, inspector).
- macOS с `FW_SHM_OWNER_INCARNATION=1`: 0 таких строк за 25 минут (`docs/reviews/2026-09-21_line-sim-f1-stand.md:67,88`).
- Дефект уже записан: `docs/claude/OPEN_QUESTIONS.md`, раздел «SHM-кольца на POSIX: голое имя».

**Отвергнуто:** «отрисованный кадр откатывается в pickle». На самом деле `rendered_frame` идёт inline потому, что claim check этот ключ просто не видит; `frame_pickle_fallbacks` = 0.

**Следствие для 4.1:** новые кольца на POSIX до флипа флага унаследуют тот же дефект голых имён.

## 3. Кто на самом деле читает маску

- **storage (`DatabasePlugin`)** маску не использует.
  - `_add_to_buffer` (`Plugins/io/database/plugin.py:120-126`) пишет `timestamp`, `frame_id`, `camera_id`, `event_type` и `"data": str(item)`.
  - Строка в БД — 1698 символов. От маски в ней только усечённый repr `array([[0, 0, 0, ..., 0]], shape=(480, 640), dtype=uint8)`: мусор без содержимого.
- **inspector (`robot_control`)**: 0 обращений к `mask`, чистый транзит.
- **renderer (`render_overlay`)**: использует маску для смешивания (~`plugin.py:112`).
- **gui**: в `multiprocess_prototype/frontend` обращений к `["mask"]` / `get("mask")` нет; дисплей берёт `rendered_frame`.
- **letter_robot_sim**: из четырёх получателей маски её читает только `maskview`. В `line`, `recog`, `draw`, `word_layout` — 0 вхождений.
- **Вывод:** item везёт все ключи через все хопы, провода его не обрезают. Обрезка item по объявленным проводам убрала бы 4 из 5 хопов маски в `inspection_full` и 5 из 6 в `letter_robot_sim`, вообще без SHM.

## 4. Порог

- **Предложение:**
  - claim check — для массива с `nbytes ≥ 8192`;
  - приёмка — сообщение `≤ 16384 Б`;
  - оба значения — литералами.
- **Разрыв в трафике около трёх порядков:**
  - самый маленький массив — 307 200 Б;
  - всё, что не массив, — не больше 1 КБ (1 229 554 − 921 766 − 307 364 = 424 Б).
- **Почему на массив 8 КБ, а не 16 КБ:** два-три массива чуть ниже порога сами дали бы сообщение больше 16 КБ.

## 5. Что в кольце и пуле рассчитано на один массив

- `generic_process.py:207-213` — один `FrameShmMiddleware` на процесс, один `slot="output_frames"`.
- `frame_shm_middleware.py:117,149,153-157` — один `_slot`, `_write_index`, `_alloc_shape`/`_alloc_dtype`, `_slot_seqlock`. Если в одном кольце смешать формы, realloc (L700-756) пойдёт по кругу, и каждый `close_memory` будет делать unlink под читателями.
- `frame_shm_middleware.py:243-249` — один `LoanLedger`. `num_consumers` считается на процесс, а не на ключ (`generic_process.py:201`).
- `frame_shm_middleware.py:467-472` — ссылка записывается плоскими полями item (`owner`, `shm_owner`, `shm_name`, `shm_index`, `shm_actual_name`, `shm_seqlock`). Второй массив затёр бы первый.
- `frame_shm_middleware.py:660-665` — берётся только `item["frame"]`; fan-out-повтор распознаётся по `item["shm_name"]`.
- `restore_frame` (`578-641`) и `on_receive` (`875-920`) восстанавливают только `frame`.
- `data_receiver.py:300-312` — копирует плоские поля ссылки в item.
- `pipeline_executor.py:278-286` — один тикет возврата на item.
- `router_manager.py:836` — отпуск при вытеснении по одному `data["shm_index"]`.
- `memory/pool/interfaces.py:117`, `loan_ledger.py:36` — `LoanTicket` без ключа и без кольца.
- **Уже подходит:** `MemoryManager.create_memory_dict` принимает словарь имён на владельца (`manager.py:181-240`).

## Что осталось открытым и что ненадёжно

- **Mac/POSIX не запускался.** Причина `/output_frames_0` выведена из кода, демонстрации имён и чужого замера с флагом. Живого `ENOENT` нет. Когда именно это случается чаще, при стопе или при старте, — вывод по коду, а не по временным меткам.
- **Хук удваивает pickle и нагружает стенд:** camera 21.35 Гц против 25. На размеры это не влияет.
- **Флаги SHM (loan, zero-copy, incarnation) по дефолту выключены** — пути пула и займов в замере не участвовали.
- **`letter_robot_sim` — один прогон, не три.** Контуры с реальными дефектами, `recog`, `phone` не замерены.
- **Прогоны дописали строки в `data/inspection_results.db`** (gitignored).
