# Task T8c — `capture_ns` и `capture_ts` у камеры `camera_device` и у синтетического источника (бриф, ред. 2; продолжение T8)

Основание: приложение 2, раздел 12 («T8 (контракт времени), дополнения»: `Plugins/sources/synthetic_frame_source/plugin.py`, `_build_item`, `capture_ns` из точки `_on_frame`), находки 4 и 5 и раздел 8; приложение 1, T8. Часть T8, выделенная по лимиту «Files <= 6» (см. `tasks/T8.md`). Ред. 2 — по итогам стадии 0 (reviewer, итерация 1, CHANGES REQUESTED) и решениям лида.

- **Level:** Middle (Sonnet) · **Assignee:** `developer` (sonnet; тот же исполнитель, что T8) · **Priority:** P1 · **Wave:** 2
- **Module contract:** public-api-change (состав полей item камеры и синтетики)
- **Gate:** по одному файлу через `bash scripts/machine_gate.sh light <session> .venv/Scripts/python.exe -m pytest -q --tb=short <файл>`: `Services/camera_device/tests/test_plugin_base.py`, `test_plugin_base_hazards.py`, `Plugins/sources/synthetic_frame_source/tests/test_capture_stamps.py`, `Services/hikvision_camera/tests/test_plugin_on_core.py` и `Services/hikvision_camera/tests/test_4_2d_acceptance.py` (по 17 passed каждый); код 75 — «не прогнано».
- **Dependencies:** T8 слит (контракт и запись ADR-177). Зависимость порядка: T8c после T8; T13 после T8c (оба правят `plugin_base.py`); T8b после T13. Блокирует T13.
- **Goal:** `CameraDevicePlugin` ставит `capture_ns` в самой ранней точке (колбэк `_on_frame`, в одной точке с `seq`), а не в `produce()`; `capture_ts` в item = `ts` момента прихода; синтетический источник ставит оба штампа сам.
- **Files:** 7 файлов (6 + `Services/hikvision_camera/plugin/plugin.py`) — снято ограничение «<= 6» лимита гигиены по решению лида; список — в блоке FILES.
- **Acceptance:** в блоке ACCEPTANCE.
- **Кто пишет тесты:** слепой `tester` (один прогон на «контракт времени кадра» вместе с T8; решение лида): `test_plugin_base.py` (правка), `tests/__init__.py` и `tests/test_capture_stamps.py` синтетики — файлы tester-а, developer их не правит. Тесты не читают и не подменяют `_slot` — только реальные `_on_frame` и `produce()` (иначе T13, заменяющий `_slot`, их сломает). Developer-тестов в T8c нет: все три тестовых файла — файлы tester-а; шестой слот FILES занят README; при необходимости developer-тестов — стоп и вопрос лиду.
- **Слияние DECISIONS:** запись о контракте — в T8 (ADR-177); `python -m scripts.sync` developer НЕ запускает (сливает лид).

## Открыто для лида

| № | вопрос | замер | умолчание брифа |
|---|---|---|---|
| О1 | РЕШЕНО: у синтетики тест — новый `tests/test_capture_stamps.py` с `tests/__init__.py` (образец `Plugins/io/frame_saver/tests`); имя RED выбрано мной | `ls Plugins/sources/synthetic_frame_source` — `__init__.py`, `plugin.py` | принято; число файлов 6 |
| О2 | РЕШЕНО: слот — пятиэлементный кортеж `(seq, ts, mono, raw, cap_ns)`; `_build_item(self, seq, ts, mono, raw, cap_ns)` | `plugin_base.py:197` — аннотация четырёхэлементного кортежа | DESIGN п.1 |
| О3 | РЕШЕНО: `capture_ts` синтетики = `time.time()` в начале `produce()` | — | DESIGN п.3 |
| О4 | РЕШЕНО: слепой tester назначен вместе с T8 | — | — |

Сверка строк (`git grep -n` / `sed`): `plugin_base.py:402-406` (`_on_frame`), `:197` (`self._slot: tuple[int, float, float, RawFrame] | None`), `:452` (`publish_metric("pending", ...)`), `:526` (`def produce`), `:534-535` (замок и снятие слота), `:585-601` (`_build_item`; `:594-595` — `timestamp`/`ts`, `:592` — `seq_id`, `:600` — `device_frame_num`); `Services/camera_device/README.md:83-84` — перечень ключей item. Расхождений нет.

## Ревью стадии 0

- р.1 → verdict CHANGES REQUESTED (reviewer, sonnet), правки применены в ред. 2 (текст вердикта не читался; перечень правок получен от лида)

## Инъекции (план)

- `capture_ns` берётся в `produce()` или `_build_item` -> `test_camera_capture_ns_taken_at_on_frame_not_at_produce` (контроль: между `_on_frame` и `produce()` 50 мс, `produce_ns - capture_ns >= 40 мс`)
- `capture_ts = time.time()` в `_build_item` вместо `ts` -> `test_camera_device_item_has_capture_ns_and_capture_ts`: между `_on_frame` и `produce()` ждать 50 мс и проверять `produce_wall - capture_ts >= 40 мс` (иначе при шаге 1 мс повторный `time.time()` через микросекунды даёт то же значение и мутация выживает); плюс `item["capture_ts"] == item["ts"]` и скобка на `time.time()` вокруг `_on_frame`
- синтетика не ставит штампы / `timestamp` перестал быть монотонным float -> `test_synthetic_item_has_capture_ns_and_capture_ts`

TASK: T8c — `capture_ns` и `capture_ts` у `camera_device` и синтетического источника   PLAN: plans/2026-11-24_gui-frame-path/plan.md
ROLE: developer
CHAIN: reviewer (стадия 0, sonnet) -> tester (слепой; общий прогон с T8) -> developer -> инъекции (лид) -> reviewer (стадия 5, sonnet)

FACTS (hand-written; generated block not available):
<!-- atlas:facts 46bdcdf -->
- слот камеры пока четырёхэлементный — `git grep -n "self._slot: tuple\[int, float, float, RawFrame\] | None" -- Services/camera_device/plugin_base.py` → `197:`
- сигнатура сборки item — `git grep -n "def _build_item" -- Services/camera_device/plugin_base.py` → `def _build_item(self, seq: int, ts: float, mono: float, raw: RawFrame) -> dict:`
- у синтетики штамп только monotonic — `git grep -n "\"timestamp\": time.monotonic()" -- Plugins/sources/synthetic_frame_source/plugin.py` → `91:`
<!-- /atlas:facts -->

DESIGN (decided by the lead — you type it, you do not derive it):
  1. `_on_frame` (`plugin_base.py:402-406`) кладёт в слот пятый элемент `time.perf_counter_ns()` рядом с `time.time()` и `time.monotonic()`, внутри замка, в одной точке с `seq`; аннотация `plugin_base.py:197` обновляется до `tuple[int, float, float, RawFrame, int] | None` (`(seq, ts, mono, raw, cap_ns)`); `produce()` штамп не берёт; сигнатура `_build_item(self, seq, ts, mono, raw, cap_ns)` (`:585`).
  2. `_build_item` (`:585-601`) ставит `capture_ns = cap_ns` и `capture_ts = ts` (wall в момент прихода, НЕ новый `time.time()`); `timestamp` (monotonic) и `ts` остаются (FREEZE); в README пометка «`timestamp` не для сверки камер» (запись о контракте — ADR-177 из T8). Метрика `pending` (`:452`) работает с пятиэлементным кортежем без изменения смысла.
  3. `Plugins/sources/synthetic_frame_source/plugin.py`: `produce()` в начале вызова ставит в item `capture_ns = time.perf_counter_ns()` и `capture_ts = time.time()`; остальные поля как есть, `timestamp` остаётся `time.monotonic()` (FREEZE).
  4. `group_id` камерой и синтетикой не присваивается (отдельный план): только переносится T8.
  5. `Services/camera_device/README.md`: строки 83-84 перечисляют ключи item — добавить `capture_ns`, `capture_ts` и пометку «`timestamp` не для сверки».
  6. `Services/hikvision_camera/plugin/plugin.py` (~:50-52): подкласс `HikvisionCameraPlugin` переопределяет `_build_item` с 4 параметрами и зовёт `super()._build_item(seq, ts, mono, raw)`; сигнатура и вызов `super()` получают пятый параметр `cap_ns`. Причина: `produce()` вызывал бы переопределение с 5 параметрами -> `TypeError` на каждом кадре (найдено Gate: `test_plugin_on_core.py` 17 passed -> 17 failed).

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. Services/camera_device/plugin_base.py — слот, `_build_item`
  2. Services/camera_device/tests/test_plugin_base.py — тесты камеры, ФАЙЛ TESTER-А (правка)
  3. Plugins/sources/synthetic_frame_source/plugin.py — штампы синтетики
  4. Plugins/sources/synthetic_frame_source/tests/__init__.py — новый, ФАЙЛ TESTER-А
  5. Plugins/sources/synthetic_frame_source/tests/test_capture_stamps.py — новый, ФАЙЛ TESTER-А
  6. Services/camera_device/README.md — перечень ключей item (`:83-84`)
  7. Services/hikvision_camera/plugin/plugin.py — `_build_item` (~:50-52): сигнатура и вызов `super()._build_item` получают пятый параметр `cap_ns`

REDS (predicted red tests):
  - Services/camera_device/tests/test_plugin_base.py::test_camera_device_item_has_capture_ns_and_capture_ts
  - Services/camera_device/tests/test_plugin_base.py::test_camera_capture_ns_taken_at_on_frame_not_at_produce
  - Plugins/sources/synthetic_frame_source/tests/test_capture_stamps.py::test_synthetic_item_has_capture_ns_and_capture_ts

ACCEPTANCE (every number with its command):
  - тесты камеры зелёные — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/camera_device/tests/test_plugin_base.py` → exit 0
  - capture_ns: скобка n0 не больше capture_ns и capture_ns не больше n1 вокруг _on_frame, затем сон 50 мс, затем produce; контроль produce_ns минус capture_ns не меньше 40 мс — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/camera_device/tests/test_plugin_base.py -k test_camera_capture_ns_taken_at_on_frame_not_at_produce` → exit 0
  - capture_ts: НЕ допуск 5 мс (шаг time.time равен разрешению системного таймера Windows: 1 мс при поднятом разрешении, 15,6 мс при штатном; time.monotonic всегда 15-16 мс); проверяется item capture_ts равно item ts, между _on_frame и produce сон 50 мс и produce_wall минус capture_ts не меньше 40 мс, и скобка на time.time вокруг _on_frame; capture_ns int, capture_ts float — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/camera_device/tests/test_plugin_base.py -k test_camera_device_item_has_capture_ns_and_capture_ts` → exit 0
  - синтетика: capture_ns int, capture_ts float, скобка perf_counter_ns вокруг produce, timestamp остаётся монотонным float — `.venv/Scripts/python.exe -m pytest -q --tb=short Plugins/sources/synthetic_frame_source/tests/test_capture_stamps.py` → exit 0
  - гарды камеры не сломаны — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/camera_device/tests/test_plugin_base_hazards.py` → exit 0
  - подкласс Hikvision принимает пятый параметр: 17 passed — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/hikvision_camera/tests/test_plugin_on_core.py` → `17 passed`
  - приёмка 4.2d Hikvision: 17 passed — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/hikvision_camera/tests/test_4_2d_acceptance.py` → `17 passed`
  - тесты T8c не обращаются к _slot — `git grep -n "_slot" -- Services/camera_device/tests/test_plugin_base.py Plugins/sources/synthetic_frame_source/tests` → exit 1

TESTS: .venv/Scripts/python.exe -m pytest -q --tb=short Services/camera_device/tests/test_plugin_base.py Services/camera_device/tests/test_plugin_base_hazards.py Plugins/sources/synthetic_frame_source/tests/test_capture_stamps.py (через `machine_gate.sh light <session>`; каталог `Services/camera_device/tests` целиком — medium)

OUT OF SCOPE: очередь кадров источника (T13), штампы SDK `dev_ts`/`host_ts_ms`/`lost_packets` (T8b), прочие файлы `Services/hikvision_camera` (кроме `plugin/plugin.py`), framework (T8), назначение `group_id`, `python -m scripts.sync` (лид).
TRAPS: фейковый порт в `test_plugin_base.py` (`_Built`) — штамп проверять через реальный `_on_frame`, не подменять часы после; `grep` по `_slot` в тестах T8c должен быть пуст (иначе T13 их ломает).
HANDOFF IN: T8 слит.

## Что оставил открытым / ненадёжно

- Правка подкласса `HikvisionCameraPlugin` пропущена двумя кругами стадии 0 и поймана Gate (`test_plugin_on_core.py`: 17 passed -> 17 failed после правки слота). Число файлов T8c — 7 (6 + hikvision plugin), ограничение «<= 6» лимита гигиены снято по решению лида.
- Точность: штамп ставится после копирования кадра из SDK (`driver.py:403`) — момент прихода на хост, не экспозиции; постоянный сдвиг у каждой камеры свой, дрожание не измерено (приложение 2, раздел 8).
- Правки применены по перечню лида; вердикт ревью стадии 0 не читался.
- Шаг `time.time()` (1 мс при поднятом разрешении таймера Windows, 15,6 мс при штатном; `time.monotonic` всегда 15-16 мс) взят у лида, мной не перемерялся. Вывод: допуск 5 мс для `capture_ts` не вводить, проверять `capture_ts == ts` и скобку на `time.time()`.
- Пятиэлементный слот — решение лида (О2).
