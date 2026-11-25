# Task W2-c: `FramePump` сообщает о тишине ключа (framework)

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer
- **Module contract:** public-api-change (`frontend_module/bridge/frame_pump.py`: два новых именованных параметра `FramePump.__init__`)
- **Dependencies:** нет (база волны 2)
- **Gate:** `machine_gate.sh light <session>` по файлам TESTS; радиус `multiprocess_framework/modules/frontend_module/tests/test_frame_pump.py` и `multiprocess_prototype/frontend/tests/test_frame_overload_real_objects.py`
- **Files:** `multiprocess_framework/modules/frontend_module/bridge/frame_pump.py`, `multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence_hazards.py`
- **Acceptance:** блок ACCEPTANCE; файл tester-а зелёный
- **Handoff:** reviewer (стадия 0, sonnet) -> tester (слепой RED) -> developer -> лид (инъекции) -> reviewer (стадия 5, sonnet)
- **ФАЙЛ TESTER-А (developer не правит):** `multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py`

Решение владельца 1 (2026-11-25): потерянный источник виден — тёмная плашка «нет сигнала, N с», возврат к кадру при возобновлении. Ограничение лида, принятое владельцем: рисует GUI; источники НЕ подделывают чёрные кадры в конвейер (их бы проинспектировали). Факт «на этот дисплей N с не пришёл кадр» — факт самого GUI (то, что видит оператор), поэтому он считается в насосе, а не выводится из состояния бэкенда. Сегодня (`frame_pump.py:227-233`) пустой ящик — тихий пропуск тика; метки последней доставки нет.

TASK: W2-c — насос кадров зовёт колбэк тишины ключа и колбэк возврата   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: developer
CHAIN: reviewer (стадия 0) -> tester (слепой RED) -> you -> лид (инъекции) -> reviewer (стадия 5)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. `FramePump.__init__(self, mailbox, sink, parent=None, *, on_silence: Callable[[str, float | None], None] | None = None, silence_s: float = 0.0)`. `silence_s <= 0` или `on_silence is None` — механизм выключен: ни одного лишнего вызова часов в `_tick` (нулевая цена выключенного).
  2. Состояние только Qt-потока (без замка): `self._last_shown: dict[str, float]` — `time.monotonic()` при заведении ключа в `_ensure_key` (новый таймер) и при каждом непустом `take` в `_tick`; `self._silent: dict[str, int]` — последняя сообщённая целая секунда тишины.
  3. `_tick`, ветка `taken is None` при включённом механизме: `age = time.monotonic() - self._last_shown.get(key, now)`; `age >= silence_s` и `int(age) != self._silent.get(key)` -> `self._silent[key] = int(age)`, `on_silence(key, age)`. Ветка непустого `take`: ключ есть в `_silent` -> `self._silent.pop(key)`, `on_silence(key, None)` ДО `self._sink(key, item)`.
  4. Исключение `on_silence` не роняет насос и не мешает `sink`: ловится, счётчик ключа `errors` += 1 под `self._lock` (как у `sink`), строка лога — тем же дросселем, что у `sink` (`_last_error_log`).
  5. `_drop_key` снимает ключ из `_last_shown` и `_silent`. `stats()` и набор его ключей НЕ меняются (инвариант фазы A: один сбрасывающий читатель окна, `app.py:1049`). `stop()` — после него `on_silence` не зовётся (как `sink`).

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. multiprocess_framework/modules/frontend_module/bridge/frame_pump.py — параметры, `_last_shown`, `_silent`, ветки `_tick`, `_drop_key`
  2. multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence_hazards.py — новый (REDS 6-7)

REDS (predicted red tests; четыре — файл tester-а, `W2-c.tester.md`; его `test_disabled_by_default_no_callback` — охранный, зелёный до кода):
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_silence_reported_after_threshold_once_per_second
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_frame_after_silence_reports_none_before_sink
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_configured_key_without_any_frame_is_silent
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_stats_keys_unchanged
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence_hazards.py::test_on_silence_exception_counts_error_and_pump_continues
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence_hazards.py::test_no_callback_after_stop

ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence_hazards.py` -> exit 0
  - прежние зелёные — `<py> -m pytest -q --tb=short multiprocess_framework/modules/frontend_module/tests/test_frame_pump.py multiprocess_prototype/frontend/tests/test_frame_overload_real_objects.py` -> exit 0
  - `ruff check -q` по двум путям -> 0

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence_hazards.py

OUT OF SCOPE: рисование плашки, привязка ключа к дисплею, порог из рецепта (W2-c2); текст по состоянию источника (Р-W2-10).
TRAPS: `_tick` — горячий путь Qt-потока при N дисплеях: в выключенном режиме — одна проверка флага; включённый — одно чтение `monotonic` на пустой тик. Ключ, найденный сканом (`_scan`), заводится только когда кадр уже в ящике: его «тишина с начала» не наступает — это верно. Ключи из `set_keys` до первого кадра — тишина с момента заведения (плашка с самого старта).
HANDOFF IN: none
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, раздел «Что оставил открытым / ненадёжно».
