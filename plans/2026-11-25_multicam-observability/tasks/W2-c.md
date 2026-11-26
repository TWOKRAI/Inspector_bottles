# Task W2-c: `FramePump` сообщает о тишине ключа (framework)

- **Статус:** [PENDING] · **Level:** Middle+ · **Assignee:** developer
- **Module contract:** public-api-change (`frontend_module/bridge/frame_pump.py`: два именованных параметра `FramePump.__init__`; поправка FE-007)
- **Dependencies:** нет (база волны 2)
- **Gate:** `machine_gate.sh light <session>` по TESTS; радиус `multiprocess_framework/modules/frontend_module/tests/test_frame_pump.py`, `multiprocess_prototype/frontend/tests/test_frame_overload_real_objects.py`, `multiprocess_prototype/frontend/tests/test_frame_intake_wiring.py`
- **Files:** `multiprocess_framework/modules/frontend_module/bridge/frame_pump.py`, `multiprocess_framework/modules/frontend_module/DECISIONS.md`, `multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence_hazards.py`
- **Acceptance:** блок ACCEPTANCE; файл tester-а зелёный
- **Handoff:** reviewer (стадия 0, sonnet) -> tester (слепой RED) -> developer -> лид (инъекции) -> reviewer (стадия 5, sonnet)
- **ФАЙЛ TESTER-А (developer не правит):** `multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py`

Решение владельца 1 (2026-11-25): потерянный источник виден — тёмная плашка «нет сигнала, N с», возврат к кадру при возобновлении; рисует GUI, источники чёрных кадров не подделывают. Факт «на этот ключ N с не показан кадр» — факт самого GUI. Сегодня пустой ящик — тихий пропуск тика (`frame_pump.py:227-233`), метки последнего показа нет. Сигнатура насоса меняется только с ADR (`frame_pump.py:20-21`) — поправка FE-007.

TASK: W2-c — насос зовёт колбэк тишины ключа и колбэк возврата   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: developer
CHAIN: reviewer (стадия 0) -> tester (слепой RED) -> you -> лид (инъекции) -> reviewer (стадия 5)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. `FramePump.__init__(self, mailbox, sink, parent=None, *, on_silence: Callable[[str, float | None], None] | None = None, silence_s: float = 0.0)`. Включено = `on_silence is not None and silence_s > 0` (флаг `self._silence_on` считается один раз в `__init__`). Выключено — ни одного лишнего чтения часов нигде (ни в `_tick` пустого ящика, ни в `_ensure_key`). Часы — `time.perf_counter` (как у насоса, FE-007; тесты подменяют модуль `time` только с `perf_counter`, `test_frame_pump.py:618-624`); `now = time.perf_counter()`.
  2. Возраст — НА КЛЮЧ: `self._last_shown: dict[str, float]` — время последнего ПОКАЗАННОГО кадра этого ключа; ключ без кадров — время заведения ключа в `_ensure_key` (новый таймер; только при включённом механизме). `self._silent: dict[str, int]` — последняя сообщённая целая секунда тишины ключа. Оба словаря — только Qt-поток, без замка.
  3. `_tick`, пустой ящик, механизм включён: `age = now - self._last_shown[key]`; `age >= silence_s` и `int(age) != self._silent.get(key)` -> `self._silent[key] = int(age)`, `on_silence(key, age)`.
  4. Кадр «показан», только если `sink` вернулся без исключения И вернул не `False`. Только тогда: `self._last_shown[key] = now`; ключ был в `_silent` -> `self._silent.pop(key)` и `on_silence(key, None)` ПОСЛЕ `sink`. Кадр без предшествующей тишины колбэк не зовёт. Не показанный кадр (`False` или исключение) тишину не прерывает. Тип `sink` — `Callable[[str, Any], object]`: `sink` возвращает `False`, когда кадр не показан. Счётчики `stats()`: `shown` и `max_age_ms` считают и такие вызовы (`sink` без исключения, как сейчас) — постоянно падающая копия растит `shown`, пока стоит плашка; `errors` += 1 также на исключение `on_silence`. (Смысл `shown` не меняется — мой выбор ради инвариантов фазы A, ждёт подтверждения лида.)
  5. `on_silence` зовётся в Qt-потоке ВНЕ `self._lock`; после его возврата — проверка `self._stopped` перед любым следующим вызовом потребителя (`sink` или `on_silence`). После `sink` — проверка `self._stopped` ДО `on_silence(key, None)`. Исключение `on_silence` ловится; лог — свой дроссель `self._last_silence_error_log: dict[str, float]` (часы `perf_counter`, период как у `sink`), текст называет `on_silence`.
  6. `_drop_key` снимает ключ из `_last_shown`, `_silent`, `_last_silence_error_log`; колбэк при снятии ключа не зовётся (плашки снимает потребитель при `set_keys`, W2-c2). Насос не знает о намеренной остановке источника; порог на дисплей — фильтр потребителя по `age_s` (Р-W2-10). `stats()` и набор его ключей НЕ меняются (инвариант фазы A: один сбрасывающий читатель окна, `app.py:1049`).
  7. Докстринг модуля (раздел публичного API), Pre/Post `__init__` и `stop` (после `stop()` ни `sink`, ни `on_silence`), новый смысл `errors`; `sink` возвращает `False`, когда кадр не показан (`Callable[[str, Any], object]`); `shown` и `max_age_ms` считают и такие вызовы — постоянно падающая копия растит `shown`, пока стоит плашка.
  8. `DECISIONS.md`: поправка к FE-007 — параметры, смысл тишины (время с последнего ПОКАЗАННОГО кадра ключа), возврат `False` у `sink` и то, что `shown`/`max_age_ms` считают и не показанные кадры, часы, снятие ключа, цена выключенного режима, отвергнутое (тишина в источнике — нельзя: источник не знает, что показано; чёрный кадр — нельзя: его проинспектируют).
  9. Обязательные тесты опасности (файл 3 FILES): `test_disabled_reads_no_clock` (подменённый `perf_counter` со счётчиком: `set_keys` и 20 пустых тиков в выключенном режиме -> 0 чтений), `test_stop_inside_on_silence_ends_calls` (два случая: `on_silence` зовёт `stats()`, затем `stop()`; и `sink` кадра после тишины зовёт `stop()` -> после этого ни `sink`, ни `on_silence`, в том числе ни `on_silence(key, None)`; `stats()` внутри колбэка зовётся из daemon-потока зонда с `join`, как `test_frame_pump.py:542-573`), `test_on_silence_exception_on_number_and_none` (бросает на числе и на `None` -> `errors` += 2, насос жив, кадр показан).

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. multiprocess_framework/modules/frontend_module/bridge/frame_pump.py — п.1-7
  2. multiprocess_framework/modules/frontend_module/DECISIONS.md — п.8
  3. multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence_hazards.py — новый, п.9

REDS (predicted red tests; 1-7 — файл tester-а `W2-c.tester.md`, там же `test_stats_keys_unchanged` — тоже красный, в REDS не уместился):
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_silence_reported_once_per_second_with_bounds
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_frame_after_silence_reports_none_once
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_configured_key_without_any_frame_is_silent
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_disabled_modes_never_call_back
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_steady_frames_report_nothing
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_silence_is_per_key
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_unshown_frame_keeps_silence
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence_hazards.py::test_disabled_reads_no_clock
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence_hazards.py::test_stop_inside_on_silence_ends_calls
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence_hazards.py::test_on_silence_exception_on_number_and_none

ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence_hazards.py` -> exit 0
  - прежние зелёные — `<py> -m pytest -q --tb=short multiprocess_framework/modules/frontend_module/tests/test_frame_pump.py multiprocess_prototype/frontend/tests/test_frame_overload_real_objects.py multiprocess_prototype/frontend/tests/test_frame_intake_wiring.py` -> exit 0
  - `ruff check -q` по путям 1 и 3 -> 0

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence_hazards.py

OUT OF SCOPE: рисование плашки, привязка ключа к дисплею, снятие плашек при `set_keys`, порог из рецепта (W2-c2, Р-W2-10).
TRAPS: `_tick` — горячий путь Qt-потока при N дисплеях: выключено — одна проверка флага; включено — одно чтение часов на пустой тик. Ключ, найденный сканом (`_scan`), заводится, когда кадр уже в ящике: тишина «с заведения» у него короче периода — это верно. `sink` сегодня возвращает `None` — это «показан» (только `False` — нет).
HANDOFF IN: none
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, раздел «Что оставил открытым / ненадёжно».
