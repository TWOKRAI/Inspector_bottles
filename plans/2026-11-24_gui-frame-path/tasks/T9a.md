# Task T9a — `TimeRing`, ядро кольца: вытеснение по времени и байтам, доступ по времени, разрывы (бриф, ред. 3; часть бывшей T9)

Основание: приложение 1, раздел А (арифметика), раздел В («Кадр на момент t»), задача T9; приложение 2, разделы 6 (решение: формат один — сегмент независимых JPEG + индекс), 9, 12 («T9, дополнения»); условие У4; `tasks/T8.md` п.3 (ключ индекса `(capture_ns, seq_id)`). Побеждает приложение 2. T9 разбита на T9a (ядро) и T9b (формат записи, закрепление, экспорт) по итогам стадии 0 (reviewer, итерация 1, 13 REDS > лимит 10); ред. 3 — вердикт итерации 2 стадии 0 и решения лида (применено лидом без третьего круга).

- **Level:** Middle+ (Sonnet) · **Assignee:** `developer` (sonnet) · **Priority:** P1 · **Wave:** 1 (параллельно T1, T8)
- **Module contract:** lite
- **Gate:** по одному файлу через `bash scripts/machine_gate.sh light <session> .venv/Scripts/python.exe -m pytest -q --tb=short <файл>`: `Services/frame_buffer/tests/test_time_ring.py`, `Services/frame_buffer/tests/test_time_ring_hazards.py`; затем `.venv/Scripts/python.exe -m scripts.validate` по части Services (`check_services_decisions`); код 75 — «не прогнано».
- **Dependencies:** нет (библиотека без IPC и Qt; `capture_ns` принимается параметром). Блокирует T9b и T10. Имя пакета `Services/frame_buffer` — решение владельца 12 (приложение 2), ПОДТВЕРЖДЕНИЯ НЕТ: T9a/T9b не закрепляют имя окончательно; подтверждение нужно до T10.
- **Goal:** кольцо кадров по времени: вытеснение по времени (`capture_ns < newest - buffer_seconds`), затем по байтам (`max_bytes`), доступ `at(t_ns, mode)`, `range()`, список разрывов; один писатель, читатели под замком; хранение в RAM.
- **Files:** 5 файлов developer-а, список — в блоке FILES.
- **ФАЙЛЫ TESTER-А (developer не правит; вне блока FILES):** `Services/frame_buffer/tests/__init__.py`, `Services/frame_buffer/tests/test_time_ring.py`.
- **Acceptance:** в блоке ACCEPTANCE.
- **Кто пишет тесты:** слепой `tester` (решение лида: один прогон на механизм «кольцо + формат» для T9a и T9b) пишет `tests/__init__.py` и `tests/test_time_ring.py` только по литералам ACCEPTANCE; developer пишет hazard-тесты (потоки) в `tests/test_time_ring_hazards.py`. Требование к каждому новому `.py` (включая тесты): `__all__` и строка `Purpose:` в docstring (иначе `pre_report_gate` contract-lite красный) — входит и в бриф tester-а.
- **Слияние DECISIONS:** `DECISIONS.md` пакета входит в FILES developer-а (обязателен: `scripts.validate.check_services_decisions` без него даёт FAIL); `python -m scripts.sync` developer НЕ запускает — сливает лид одним проходом.

## Открыто для лида

| № | вопрос | замер | умолчание брифа |
|---|---|---|---|
| О1 | РЕШЕНО: слепой tester назначен (один прогон на T9a + T9b) | — | — |
| О2 | РЕШЕНО: REDS разделены на T9a (10) и T9b (10) | — | — |
| О3 | РЕШЕНО: плоский пакет без `core/`, как `Services/camera_device` | `git ls-files Services/camera_device/__init__.py Services/camera_device/DECISIONS.md` — оба файла есть | принято |
| О4 | РЕШЕНО: граница вытеснения ВКЛЮЧАЮЩАЯ (кадр с `capture_ns == newest - buffer_ns` остаётся, вытесняется строго `<`) | — | DESIGN п.1 |
| О5 | РЕШЕНО: имя пакета не закрепляется (решение владельца 12, подтверждения нет) | — | план: «ждёт подтверждения до T10» |
| О6 | РЕШЕНО лидом (бывший О-П8): порядок кольца по паре `(capture_ns, seq)`; отвергается с `rejected_order` ТОЛЬКО кадр с парой не больше пары последнего принятого; равный `capture_ns` при большем `seq` принимается | равные `capture_ns` бывают (4-59 пар на 1000 в узком цикле, `tasks/T8.md` п.3) | DESIGN п.2 |
| О7 | РЕШЕНО лидом: `bytes_held_peak` считается сразу после добавления нового кадра в хранилище и ДО любого последующего вытеснения | — | DESIGN п.3 (порядок внутри `append`) |
| О8 | РЕШЕНО лидом: тай-брейк `at()` при равных `capture_ns` | — | DESIGN п.4 |
| О9 | ВОПРОС СТАДИИ 0: проверка `ValueError` для `flags & 0b11` не названа в REDS (лимит 10 исчерпан) | — | подслучай в `test_rejected_oversize` (кольцо не трогается и при неверных `flags`) |

## Ревью стадии 0

- р.1 → CHANGES REQUESTED (reviewer, sonnet), правки применены в ред. 2
- р.2 → вердикт итерации 2 применён лидом в ред. 3 без третьего круга (текст вердикта не читался; перечень правок получен от лида)

## Инъекции (план)

Инъекции прогоняются против ОБОИХ наборов тестов: `test_time_ring.py` (tester) и `test_time_ring_hazards.py` (developer).

- вытеснение по времени отключено -> `test_evicts_older_than_buffer_seconds`, `test_low_fps_keeps_same_seconds`
- вытеснение только по числу кадров -> `test_low_fps_keeps_same_seconds`
- потолок байтов не применяется -> `test_bytes_cap_evicts_oldest_and_span_reported`, `test_bytes_held_never_exceeds_max_bytes`
- кадр сначала добавляется, потом вытесняется (пик 12000 вместо 9000) -> `test_bytes_held_never_exceeds_max_bytes`
- `at()` с неверным тай-брейком или границами -> `test_at_nearest_prev_next`
- разрыв не считается, рестарт `seq` считается как `missed`, отвергнутый кадр двигает `last_seq` -> `test_seq_gap_recorded`
- кадр с парой не больше последней принятой вставляется / равный `capture_ns` с большим `seq` отвергается -> `test_rejected_order`
- кадр больше `max_bytes` трогает кольцо -> `test_rejected_oversize`
- читатель без замка -> `test_concurrent_append_and_at` (файл hazards)

TASK: T9a — `TimeRing`, ядро (Services/frame_buffer)   PLAN: plans/2026-11-24_gui-frame-path/plan.md
ROLE: developer
CHAIN: reviewer (стадия 0, sonnet) -> tester (слепой, общий прогон с T9b) -> developer -> инъекции (лид) -> reviewer (стадия 5, sonnet)

FACTS (hand-written; generated block not available):
<!-- atlas:facts 46bdcdf -->
- образец плоского пакета Services — `git ls-files Services/camera_device/__init__.py` → `Services/camera_device/__init__.py`
- образец DECISIONS у сервиса — `git ls-files Services/camera_device/DECISIONS.md` → `Services/camera_device/DECISIONS.md`
- проверка DECISIONS у сервисов существует — `git grep -n "def check_services_decisions" -- scripts/validate.py` → `def check_services_decisions`
<!-- /atlas:facts -->

DESIGN (decided by the lead — you type it, you do not derive it):
  1. Конструктор `TimeRing(buffer_seconds, max_bytes, pin_max_bytes)` БЕЗ значений по умолчанию (умолчания ждут замера 100 настоящих кадров, У5); `pin_max_bytes <= max_bytes`, иначе исключение при создании (параметр используется T9b). `append(capture_ns, capture_ts, payload: bytes, seq, device_frame_num=None, group_id=None, flags=0)`. Порядок действий внутри `append`: проверка отказов (п.2) -> вытеснение по времени -> вытеснение по байтам до освобождения места -> добавление кадра -> обновление `bytes_held_peak` (сразу после добавления, до любого последующего вытеснения; поэтому пик не выше `max_bytes`). Вытеснение всегда самого старого: по времени строго `capture_ns < newest - buffer_ns` (кадр с `capture_ns == newest - buffer_ns` остаётся — граница ВКЛЮЧАЮЩАЯ), затем по байтам. Кольцо считает секунды, не штуки.
  2. Отказы: порядок кольца по паре `(capture_ns, seq)` (условие `tasks/T8.md` п.3). Отвергается со счётчиком `rejected_order` и не вставляется ТОЛЬКО кадр, у которого пара `(capture_ns, seq)` не больше пары последнего принятого кадра; кадр с `capture_ns`, равным последнему, но с БОЛЬШИМ `seq` — принимается; отвергнутый кадр `last_seq` не двигает. Литерал: вход `[(100,1),(200,2),(150,3),(200,4),(300,5)]` -> `frames == 4` (в кольце `(100,1),(200,2),(200,4),(300,5)`), `rejected_order == 1`; затем повторная подача пары `(200,2)` -> `rejected_order == 2`, `frames == 4`. `len(payload) > max_bytes` отвергается со счётчиком `rejected_oversize`, кольцо не трогается.
  3. Потолок: `max_bytes` — жёсткий общий потолок, не превышается никогда; `bytes_held_peak` — по п.1 (О7).
  4. `at(t_ns, mode)` -> `dict | None` с ключами `payload` (bytes без копии), `capture_ns`, `capture_ts`, `seq`, `device_frame_num`, `group_id`, `flags` (`flags` возвращается как принят). Порядок кольца — пара `(capture_ns, seq)`; `prev(t)` = последний кадр пары с `capture_ns <= t` (больший `seq`); `next(t)` = первый с `capture_ns >= t` (меньший `seq`); `nearest` = выбор между `prev(t)` и `next(t)` по `|Δ|`, при равенстве — `prev`. `t` вне диапазона: `prev` ниже `t_min` и `next` выше `t_max` дают `None`; `nearest` на непустом кольце не `None`; совпадение с отсчётом даёт его кадр. Литералы — в ACCEPTANCE.
  5. `range()` -> `{"t_min_ns", "t_max_ns", "frames", "gaps"}`; пустого кольца -> `{"t_min_ns": None, "t_max_ns": None, "frames": 0, "gaps": []}`.
  6. Разрыв: единые ключи `{after_seq, before_seq, missed, capture_ns, restart}`; `capture_ns` разрыва = штамп кадра, обнаружившего разрыв (кадр `before_seq`); `seq` идущий назад (рестарт камеры) — новая эпоха: разрыв с `restart: True` и `missed: 0`; разрыв отбрасывается, когда его `capture_ns` СТРОГО меньше `capture_ns` самого старого оставшегося кадра (предел).
  7. Хранение в RAM: дека записей, один объект `bytes` на кадр (не `bytearray` с `del buf[:k]`); смещения считаются только при `export` (T9b).
  8. Счётчики: `bytes_held`, `bytes_held_peak`, `span_s` (= `(t_max - t_min) / 1e9`, `float`), `evicted_by_time`, `evicted_by_bytes`, `rejected_order`, `rejected_oversize`, `pins_released` (последний заполняет T9b).
  9. `flags`: пользовательские занимают биты 2..31; биты 0 и 1 зарезервированы T9b (`has_device_frame_num`, `has_group_id`); `append` с `flags & 0b11` -> `ValueError` с константным текстом без значения входа.
  10. Один писатель, читатели под замком. `payload` — непрозрачные байты: кольцо JPEG не декодирует и не проверяет.
  11. В каждом новом `.py` обязательны `__all__` и строка `Purpose:` в docstring. `README.md` и `DECISIONS.md` пакета: `Stability: lite` и одна строка, почему нет `interface.py` (один класс, одна реализация); `DECISIONS.md` — ADR вытеснения (почему по секундам, почему граница включающая, почему жёсткий потолок и отказ, а не вытеснение сверх потолка, почему порядок по паре); обязателен, без него `scripts.validate.check_services_decisions` даёт FAIL. README делает T9a; `STATUS.md` пакета — `docs-writer` после T9b (не в этой задаче).

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. Services/frame_buffer/__init__.py — экспорт `TimeRing`
  2. Services/frame_buffer/time_ring.py — новый (плоский пакет, без `core/`)
  3. Services/frame_buffer/DECISIONS.md — ADR вытеснения
  4. Services/frame_buffer/README.md — назначение, API, инварианты, `Stability: lite`
  5. Services/frame_buffer/tests/test_time_ring_hazards.py — новый, файл developer-а (потоки)

REDS (predicted red tests):
  - Services/frame_buffer/tests/test_time_ring.py::test_evicts_older_than_buffer_seconds
  - Services/frame_buffer/tests/test_time_ring.py::test_low_fps_keeps_same_seconds
  - Services/frame_buffer/tests/test_time_ring.py::test_bytes_cap_evicts_oldest_and_span_reported
  - Services/frame_buffer/tests/test_time_ring.py::test_at_nearest_prev_next
  - Services/frame_buffer/tests/test_time_ring.py::test_seq_gap_recorded
  - Services/frame_buffer/tests/test_time_ring.py::test_range_empty
  - Services/frame_buffer/tests/test_time_ring_hazards.py::test_concurrent_append_and_at
  - Services/frame_buffer/tests/test_time_ring.py::test_bytes_held_never_exceeds_max_bytes
  - Services/frame_buffer/tests/test_time_ring.py::test_rejected_order
  - Services/frame_buffer/tests/test_time_ring.py::test_rejected_oversize

ACCEPTANCE (every number with its command; tester работает только по этим литералам):
  - тесты tester-а зелёные — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring.py` → exit 0
  - тесты hazards зелёные — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring_hazards.py` → exit 0
  - 25 Гц, период 40000000 нс, 400 кадров по 100 байт, max_bytes 1000000 (названо числом), буфер 10 с, осталось 251 (при любом start) — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring.py -k test_evicts_older_than_buffer_seconds` → exit 0
  - 11,7 Гц, период 85470085 нс (целое), 400 кадров по 100 байт, max_bytes 1000000, буфер 10 с, осталось 118; 118 зависит от округления периода (при 85470086 было бы 117), а не от границы — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring.py -k test_low_fps_keeps_same_seconds` → exit 0
  - 25 кадров по 1000 байт, capture_ns равен i умножить на 100000000, max_bytes 10000, буфер 100 с: frames 10, span_s 0.9 (float, t_max минус t_min делить на 1e9) — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring.py -k test_bytes_cap_evicts_oldest_and_span_reported` → exit 0
  - max_bytes 10000, 50 кадров по 3000 байт: bytes_held 9000 и bytes_held_peak 9000 (равенство, не не больше) — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring.py -k test_bytes_held_never_exceeds_max_bytes` → exit 0
  - отсчёты 100, 200, 300: at(250, nearest) 200, at(200, prev) 200, at(200, next) 200, at(50, prev) None, at(350, next) None; ПЛЮС вход (100,1), (200,2), (150,3), (200,4), (300,5), в кольце (100,1), (200,2), (200,4), (300,5): at(200, prev) seq 4, at(200, next) seq 2, at(200, nearest) seq 4, at(150, prev) seq 1, at(150, next) seq 2, at(150, nearest) seq 1, at(250, nearest) seq 4; flags возвращается как принят — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring.py -k test_at_nearest_prev_next` → exit 0
  - seq 1, 2, 3, 7, 8 дают gaps равно [after_seq 3, before_seq 7, missed 3, capture_ns штамп кадра seq 7, restart False]; вход (100,1), (200,2), (150,3), (200,4), (300,5) даёт gaps равно [after_seq 2, before_seq 4, missed 1, capture_ns 200, restart False]; рестарт seq 5, 6, 1, 2 при растущем capture_ns даёт gaps равно [after_seq 6, before_seq 1, missed 0, restart True, capture_ns штамп кадра seq 1] — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring.py -k test_seq_gap_recorded` → exit 0
  - вход (100,1), (200,2), (150,3), (200,4), (300,5): frames 4 и rejected_order 1; затем повтор пары (200,2): rejected_order 2 и frames 4 — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring.py -k test_rejected_order` → exit 0
  - max_bytes 1000, pin_max_bytes 500, payload 1001 байт: rejected_oversize 1, frames 0, bytes_held 0; затем payload 1000 байт принимается, rejected_oversize остаётся 1 — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring.py -k test_rejected_oversize` → exit 0
  - range() пустого кольца равно t_min_ns None, t_max_ns None, frames 0, gaps пустой список — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring.py -k test_range_empty` → exit 0
  - два потока (писатель и читатель), daemon, join с timeout 5 и is_alive False, setswitchinterval 1e-6 в try/finally, 20000 итераций, payload несёт свой capture_ns, читатель сверяет с метаданными — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring_hazards.py -k test_concurrent_append_and_at` → exit 0
  - слой: пакет не импортирует Qt и верхние слои (после создания файлов; до git add добавить --untracked; прежний шаблон по словам даёт ложный красный на README и DECISIONS) — `git grep -n --untracked -E "^\s*(from|import) +(PySide6|PyQt[0-9]*|multiprocess_framework|Plugins|multiprocess_prototype)" -- 'Services/frame_buffer/*.py'` → exit 1

TESTS: .venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring.py Services/frame_buffer/tests/test_time_ring_hazards.py (через `machine_gate.sh light <session>`)

OUT OF SCOPE: формат записи индекса, сборка и читатель сегмента, закрепление, экспорт, поиск по группе (T9b); плагин буфера и кодирование JPEG (T10); запись на диск (T12); схема рецепта (T11); производный архив (T16); `Services/STATUS.md` и `.sentrux` не трогать; `STATUS.md` пакета (docs-writer после T9b); `python -m scripts.sync` (лид).
TRAPS: `bytes_held` не превышает `max_bytes` даже на пике `append` (вытеснять до добавления); `at()` под нагрузкой писателя — daemon-поток с join-дедлайном; значения 251, 118, 0.9, 9000 — литералы, не вычисляются из кода; в тестах 251/118 `max_bytes` заведомо большой, чтобы вытеснение по байтам не смешивалось с вытеснением по времени.
HANDOFF IN: none

## Что оставил открытым / ненадёжно

- Размеры JPEG в источниках сняты на прокси (разброс 2-4 раза); умолчания `buffer_max_mb` не фиксируются (У5).
- Имя пакета ждёт решения владельца 12 (подтверждения нет).
- Литералы 251, 118, 0.9, 9000, gaps и `at()` продиктованы лидом; арифметику 251 и 118 я проверял, остальное нет.
- Тест `ValueError` для `flags` помещён подслучаем (О9) — моё размещение.
- Вердикт итерации 2 reviewer-а не читался; правки по перечню лида.
