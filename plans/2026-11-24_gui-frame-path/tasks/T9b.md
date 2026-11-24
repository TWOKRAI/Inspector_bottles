# Task T9b — формат сегмента, закрепление диапазона, экспорт и читатель (бриф, ред. 2; часть бывшей T9)

Основание: приложение 2, раздел 6 (формат один: сегмент независимых JPEG + индекс фиксированной длины), раздел 9 (закрепление, `group_id`, событие брака), раздел 12 («T9, дополнения», «T12 (диск), формат решён»), условие У4; решения лида по итогам стадии 0 (reviewer, итерация 1 и итерация 2; применено лидом без третьего круга). Продолжение `tasks/T9a.md`.

- **Level:** Middle+ (Sonnet) · **Assignee:** `developer` (sonnet) · **Priority:** P1 · **Wave:** 2 (до 5 писателей по решению владельца, если файлы не пересекаются; T9b после T9a по коду)
- **Module contract:** lite
- **Gate:** по одному файлу через `bash scripts/machine_gate.sh light <session> .venv/Scripts/python.exe -m pytest -q --tb=short <файл>`: `Services/frame_buffer/tests/test_segment.py`, `test_time_ring_pin_export.py`, `test_time_ring_hazards.py`, затем `test_time_ring.py` (ядро T9a не сломано); код 75 — «не прогнано».
- **Dependencies:** T9a слита. Блокирует T10 (вместе с T8, T9a и подтверждением имени пакета) и T12: формат T9b — вход T12 (T12 пишет те же `.mjs` / `.idx`). Имя пакета `Services/frame_buffer` — решение владельца 12, подтверждения НЕТ; не закреплять окончательно.
- **Goal:** запись индекса фиксированной длины, сборка и читатель сегмента (`segment.py`), закрепление диапазона (`pin`/`unpin`) и поиск по `group_id`, `export` в том же виде, что пойдёт на диск (T12).
- **Files:** 5 файлов developer-а, список — в блоке FILES.
- **ФАЙЛЫ TESTER-А (developer не правит; вне блока FILES):** `Services/frame_buffer/tests/test_segment.py`, `Services/frame_buffer/tests/test_time_ring_pin_export.py`. Переносятся в основное дерево при СТАРТЕ T9b, НЕ при слиянии T9a (иначе на main лежат красные тесты, а `testpaths` с «Services» их соберёт).
- **Acceptance:** в блоке ACCEPTANCE.
- **Кто пишет тесты:** слепой `tester` (один прогон на «кольцо + формат» вместе с T9a) — только по литералам ACCEPTANCE; developer дополняет `tests/test_time_ring_hazards.py` (файл T9a) потоковыми тестами закрепления и экспорта (DESIGN п.7). Каждый новый `.py` — с `__all__` и строкой `Purpose:` в docstring (входит и в бриф tester-а).
- **Слияние DECISIONS:** запись формата в `DECISIONS.md` входит в FILES developer-а; `python -m scripts.sync` developer НЕ запускает (сливает лид). `README.md` пакета делает T9a (T9b его не правит); `STATUS.md` пакета дописывает `docs-writer` после T9b — вне этого брифа.

## Открыто для лида

| № | вопрос | замер | умолчание брифа |
|---|---|---|---|
| О1 | РЕШЕНО: слепой tester назначен вместе с T9a | — | — |
| О2 | РЕШЕНО: формат записи `struct.Struct("<QIqdqqqI")`, little-endian без выравнивания, 56 байт | `calcsize` проверит developer | DESIGN п.1 |
| О3 | РЕШЕНО: биты `flags` 0 и 1 — `has_device_frame_num` и `has_group_id`; пользовательские флаги — биты 2..31 (T9a п.9) | — | DESIGN п.1 |
| О4 | РЕШЕНО: правила закрепления — интервал включающий `[t0, t1]` по обоим концам; «самый старый» пин — по порядку вызова `pin`; повторный `pin` с тем же тегом заменяет интервал; `unpin` неизвестного тега — no-op; `t0 > t1` -> `ValueError`; кадры двух пересекающихся пинов в `pinned_bytes` считаются один раз | — | DESIGN п.3 |
| О5 | РЕШЕНО: имена тестов даны с префиксом `test_` | — | — |
| О6 | ВОПРОС СТАДИИ 0: литерал лида для `pin_budget_exceeded_oldest_pin_released_and_counted` («`pin_max_bytes` 3000, три пина по 2000 байт -> `pins_released == 1`») по арифметике не сходится: после первого освобождения закреплено 4000 > 3000, освобождается и второй, `pins_released == 2` | — | в ACCEPTANCE два пина по 2000 байт (4000 > 3000 -> освобождён первый, `pins_released == 1`); лид подтверждает литерал |
| О7 | ВОПРОС СТАДИИ 0: литерал `pinned_range_survives_eviction` (`frames == 15`, `at(0, prev)["seq"] == 1`) помечен лидом «уточнит developer при первой реализации»; арифметика: буфер 1 с, `newest = 30 × 100000000`, остаются `i = 20..30` (11 кадров) и закреплённые `i = 0..3` (4 кадра) = 15; `seq` кадра `i = 0` равен 1 при нумерации с 1 | — | литерал 15 и 1; расхождение при реализации — отчёт, не правка теста |
| О8 | ВОПРОС СТАДИИ 0: хазард-тесты закрепления и экспорта (DESIGN п.7) в REDS не вошли (лимит 10) | — | запуск файла hazards в ACCEPTANCE |

## Ревью стадии 0

- р.1 → CHANGES REQUESTED (reviewer, sonnet), правки применены в ред. 1
- р.2 → вердикт итерации 2 применён лидом в ред. 2 без третьего круга (текст вердикта не читался; перечень правок получен от лида)

## Инъекции (план)

Инъекции прогоняются против ОБОИХ наборов тестов: файлы tester-а и `test_time_ring_hazards.py` (developer).

- закреплённое вытесняется -> `test_pinned_range_survives_eviction`, `test_pin_covers_future_frames`
- освобождение пина при превышении бюджета не считается / освобождается не самый старый -> `test_pin_budget_exceeded_oldest_pin_released_and_counted`
- `unpin` одного из двух пересекающихся пинов снимает защиту обоих -> `test_two_overlapping_pins_unpin_one_keeps_other`, `test_unpin_releases_range`
- `export` сравнивает только длины -> `test_export_bytes_identical_to_appended` (сравнивать `blob[off:off+len] == payload_i`)
- читатель принимает неполную запись хвоста / падает `struct.error` на обрезанном индексе -> `test_reader_drops_only_last_record_on_truncated_tail`, `test_reader_keeps_all_when_not_truncated`
- запись индекса другой длины / другое смещение поля -> `test_fixed_record_length`
- `find_group` отдаёт чужие кадры или не в порядке `(capture_ns, seq)` -> `test_find_group_returns_frames_of_group`
- склейка блока `export` под замком писателя -> хазард-тест экспорта параллельно с `append`

TASK: T9b — формат сегмента, закрепление, экспорт, читатель   PLAN: plans/2026-11-24_gui-frame-path/plan.md
ROLE: developer
CHAIN: reviewer (стадия 0, sonnet) -> tester (слепой, общий прогон с T9a) -> developer -> инъекции (лид) -> reviewer (стадия 5, sonnet)

FACTS (hand-written; generated block not available):
<!-- atlas:facts 46bdcdf -->
- проверка DECISIONS у сервисов существует — `git grep -n "def check_services_decisions" -- scripts/validate.py` → `def check_services_decisions`
<!-- /atlas:facts -->

DESIGN (decided by the lead — you type it, you do not derive it):
  1. Запись индекса (`segment.py`): `struct.Struct("<QIqdqqqI")`, little-endian без выравнивания, 56 байт: смещение `u64`, длина `u32`, `capture_ns` `i64`, `capture_ts` `f64`, `seq` `i64`, `device_frame_num` `i64`, `group_id` `i64`, `flags` `u32`. `None` для `device_frame_num`/`group_id` кодируется битами `flags` (бит 0 `has_device_frame_num`, бит 1 `has_group_id`), значение 0 при отсутствии (`calcsize` проверяет developer).
  2. `segment.py` — отдельный модуль: запись индекса, сборка и читатель сегмента; T12 пишет те же `.mjs` / `.idx`. `read_segment(blob, index) -> list[dict]` с теми же ключами, что у `at()` (`payload`, `capture_ns`, `capture_ts`, `seq`, `device_frame_num`, `group_id`, `flags`); `device_frame_num`/`group_id` = `None`, если бит не стоит; `flags` без битов 0 и 1; экспортируется из `__init__.py`. Читатель отбрасывает запись, у которой `смещение + длина > размер blob`; отрезанный хвост блока теряет только последнюю запись; неполная запись в хвосте индекса (`len(index) % 56 != 0`) игнорируется, `struct.error` не поднимается.
  3. Закрепление: `pin(t0_ns, t1_ns, tag)` / `unpin(tag)`; `pin` = реестр интервалов `tag -> (t0, t1)`; интервал включающий по обоим концам; кадр защищён, если его `capture_ns` попадает в интервал живого пина, включая кадр, пришедший ПОСЛЕ `pin` (будущие кадры). «Самый старый» пин — по порядку вызова `pin`; повторный `pin` с тем же тегом заменяет интервал; `unpin` неизвестного тега — no-op; `t0 > t1` -> `ValueError` (константный текст); кадры двух пересекающихся пинов в `pinned_bytes` считаются один раз; `unpin` одного из двух пересекающихся пинов оставляет защиту другого.
  4. Бюджет (два условия): (1) закреплённых байт больше `pin_max_bytes` -> освобождается самый старый пин, `pins_released += 1`, пока не станет не больше; (2) после вытеснения всего незакреплённого места под новый кадр всё ещё нет (при `pin_max_bytes == max_bytes`) -> освобождается самый старый пин, `pins_released += 1`. `max_bytes` — жёсткий общий потолок, включая закреплённое; не превышается никогда (`pin_max_bytes <= max_bytes` проверяет конструктор T9a).
  5. `export(t0_ns, t1_ns) -> {"blob": bytes, "index": bytes}`: границы включающие, порядок `(capture_ns, seq)`, смещения с нуля вплотную; пустой диапазон -> `{"blob": b"", "index": b""}`; кольцо не меняет. Под замком `export` берёт только список ссылок на `bytes`, `join` блока — вне замка (на 120 с блок ≈ 1,2 ГБ: склейка под замком остановила бы писателя). Те же байты и тот же индекс, что пойдут на диск (T12) без перекодирования.
  6. `find_group(group_id) -> list[dict]` тех же ключей, порядок `(capture_ns, seq)`.
  7. Хазард-тесты developer-а в `test_time_ring_hazards.py`: `pin`/`unpin` под потоком-писателем (daemon-потоки, `join` с дедлайном, `sys.setswitchinterval(1e-6)` в `try/finally`) и `export` параллельно с `append`.
  8. Правки `time_ring.py` (T9a): `pin`, `unpin`, `find_group`, `export`; правки `__init__.py`: экспорт читателя; правки `DECISIONS.md`: формат записи, политика пина и условия бюджета; `Stability: lite` — как в T9a. В каждом новом `.py` обязательны `__all__` и строка `Purpose:` в docstring.

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. Services/frame_buffer/segment.py — новый: запись индекса, сборка, читатель
  2. Services/frame_buffer/time_ring.py — правка (`pin`, `unpin`, `find_group`, `export`)
  3. Services/frame_buffer/__init__.py — правка (экспорт читателя)
  4. Services/frame_buffer/DECISIONS.md — правка (формат записи, пины)
  5. Services/frame_buffer/tests/test_time_ring_hazards.py — дополнение (потоки: закрепление, экспорт)

REDS (predicted red tests):
  - Services/frame_buffer/tests/test_time_ring_pin_export.py::test_pinned_range_survives_eviction
  - Services/frame_buffer/tests/test_time_ring_pin_export.py::test_pin_budget_exceeded_oldest_pin_released_and_counted
  - Services/frame_buffer/tests/test_time_ring_pin_export.py::test_find_group_returns_frames_of_group
  - Services/frame_buffer/tests/test_time_ring_pin_export.py::test_export_bytes_identical_to_appended
  - Services/frame_buffer/tests/test_segment.py::test_reader_drops_only_last_record_on_truncated_tail
  - Services/frame_buffer/tests/test_segment.py::test_reader_keeps_all_when_not_truncated
  - Services/frame_buffer/tests/test_time_ring_pin_export.py::test_unpin_releases_range
  - Services/frame_buffer/tests/test_time_ring_pin_export.py::test_two_overlapping_pins_unpin_one_keeps_other
  - Services/frame_buffer/tests/test_time_ring_pin_export.py::test_pin_covers_future_frames
  - Services/frame_buffer/tests/test_segment.py::test_fixed_record_length

ACCEPTANCE (every number with its command; tester работает только по этим литералам):
  - файл segment зелёный — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_segment.py` → exit 0
  - файл закрепления и экспорта зелёный — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring_pin_export.py` → exit 0
  - файл hazards (потоки закрепления и экспорта) зелёный — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring_hazards.py` → exit 0
  - ядро T9a не сломано — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring.py` → exit 0
  - buffer_seconds 1, 10 Гц, capture_ns равен i умножить на 100000000, по 1000 байт, max_bytes и pin_max_bytes с запасом, pin(0, 300000000, e1) при четырёх кадрах i 0..3, затем кадры до i 30: range frames 15 (окно i 20..30 это 11 кадров плюс 4 закреплённых), at(0, prev) seq 1; литерал уточняет developer при первой реализации и помечает — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring_pin_export.py -k test_pinned_range_survives_eviction` → exit 0
  - pin(500, 900, e) до прихода кадров 600 и 700, затем поток кадров: оба кадра на месте — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring_pin_export.py -k test_pin_covers_future_frames` → exit 0
  - два пересекающихся пина: unpin одного оставляет кадры другого — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring_pin_export.py -k test_two_overlapping_pins_unpin_one_keeps_other` → exit 0
  - unpin единственного пина возвращает кадры вытеснению — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring_pin_export.py -k test_unpin_releases_range` → exit 0
  - группы 7, 7, 9, None: find_group(7) даёт два кадра в порядке (capture_ns, seq); find_group(5) пустой список; find_group(None) пустой список — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring_pin_export.py -k test_find_group_returns_frames_of_group` → exit 0
  - pin_max_bytes 3000, два пина по 2000 байт (литерал «три пина» лида по арифметике даёт pins_released 2, см. О6): первый, самый старый, освобождён, pins_released 1 — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring_pin_export.py -k test_pin_budget_exceeded_oldest_pin_released_and_counted` → exit 0
  - export: blob[off:off+len] равно payload каждого кадра (сравнение байтов, не длин); пустой диапазон даёт пустые blob и index — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_time_ring_pin_export.py -k test_export_bytes_identical_to_appended` → exit 0
  - кадры по 1500 байт, 40 кадров, срез 1000 байт с хвоста блока, читатель возвращает 39 — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_segment.py -k test_reader_drops_only_last_record_on_truncated_tail` → exit 0
  - без среза читатель возвращает 40 из 40; индекс, обрезанный посреди записи (len индекса по модулю 56 не ноль), читатель не роняет struct.error — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_segment.py -k test_reader_keeps_all_when_not_truncated` → exit 0
  - запись индекса: len индекса равно 56 умножить на 40, поле записи k по смещению 56 умножить на k, литералами — `.venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_segment.py -k test_fixed_record_length` → exit 0
  - слой: пакет не импортирует Qt и верхние слои (после создания файлов; до git add добавить --untracked; прежний шаблон по словам даёт ложный красный на README и DECISIONS) — `git grep -n --untracked -E "^\s*(from|import) +(PySide6|PyQt[0-9]*|multiprocess_framework|Plugins|multiprocess_prototype)" -- 'Services/frame_buffer/*.py'` → exit 1

TESTS: .venv/Scripts/python.exe -m pytest -q --tb=short Services/frame_buffer/tests/test_segment.py Services/frame_buffer/tests/test_time_ring_pin_export.py Services/frame_buffer/tests/test_time_ring_hazards.py (через `machine_gate.sh light <session>`)

OUT OF SCOPE: запись на диск, сегменты `.mjs` / `.idx` в файлах, квоты, ротация (T12); плагин буфера и кодирование JPEG (T10); `payload` — непрозрачные байты (кольцо JPEG не декодирует и не проверяет); рассылка события брака и каталог события; `Services/STATUS.md` и `.sentrux`; `README.md` пакета (T9a) и `STATUS.md` пакета (docs-writer после T9b); `python -m scripts.sync` (лид).
TRAPS: `export` сравнивается по содержимому (`blob[off:off+len] == payload_i`), а не по суммарной длине; склейка блока — вне замка; пин, пришедший до кадра, защищает и кадры, которые придут позже; освобождение пина — самый старый, со счётчиком.
HANDOFF IN: T9a слита; файлы tester-а T9b перенесены в основное дерево при старте T9b.

## Что оставил открытым / ненадёжно

- Формат записи — решение лида, `calcsize` мной не проверялся.
- Литерал «три пина» (О6) по арифметике не сходится; в ACCEPTANCE поставлены два пина — требует подтверждения лида.
- Литерал `frames == 15` и `seq == 1` (О7) лид пометил как уточняемый.
- Хазард-тесты T9b вне REDS (лимит 10), но в ACCEPTANCE.
- Вердикт итерации 2 reviewer-а не читался; правки по перечню лида.
