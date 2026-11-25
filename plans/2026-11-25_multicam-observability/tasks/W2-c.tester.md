# W2-c — бриф tester

Спавн: `python scripts/plans_ledger.py brief W2-c.tester --plan plans/2026-11-25_multicam-observability`. Worktree на коммите ДО реализации; код реализации закрыт.

TASK: W2-c — слепые приёмочные тесты колбэка тишины `FramePump` (RED до кода)   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: tester
CHAIN: лид (бриф, стадия 0) -> tester -> developer (делает тесты зелёными) -> лид (инъекции, ревью)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. КОНТРАКТ. `FramePump(mailbox, sink, parent=None, *, on_silence=None, silence_s=0.0)` (`multiprocess_framework.modules.frontend_module.bridge.frame_pump`). Включено, только если `on_silence` задан и `silence_s > 0`. Возраст — на ключ: время с последнего ПОКАЗАННОГО кадра этого ключа (кадр показан, если `sink` вернулся без исключения и вернул не `False`); ключ без кадров — с `set_keys`. Пустой тик при возрасте `>= silence_s` -> `on_silence(key, age_s)` (`float`), не чаще раза на целую секунду возраста. Показанный кадр после тишины -> `on_silence(key, None)` один раз, ПОСЛЕ `sink`. Кадр без предшествующей тишины колбэк не зовёт. `sink` возвращает `False`, когда кадр не показан; `shown` считает и такие вызовы. Набор ключей `stats()[key]`: `shown`, `errors`, `max_age_ms`, `window_max_age_ms`, `busy_ms_total`.
  2. Стенд: `QCoreApplication`/`QApplication` и фейк ящика (`take(key)`, `pending_keys()`) по образцу `multiprocess_framework/modules/frontend_module/tests/test_frame_pump.py`; время реальное, `silence_s 0.3` (кроме оговорённых); события Qt — циклом с дедлайном 3 с. Общий журнал: `("silence", key, age)` и `("sink", key)`.
  3. Импорт `FramePump` — внутри теста. Новый `.py`: `__all__ = []`, `Purpose:`.
  4. Сценарии:
     - `test_silence_reported_once_per_second_with_bounds`: `set_keys({"cam_a": 30})`, один кадр, пусто 2,4 с -> записи `silence` после записи `sink`: `[int(age) for …] == [0, 1, 2]`, все `age >= 0.3`; первая — `float` и `0.3 <= age <= 1.0`.
     - `test_frame_after_silence_reports_none_once`: предпосылка — в журнале есть запись `silence` и запись `sink`; после тишины кадр -> ровно одна `("silence", "cam_a", None)`, и она стоит сразу после своего `("sink", "cam_a")`; второй кадр сразу следом новой записи `None` не даёт.
     - `test_configured_key_without_any_frame_is_silent`: ключ задан `set_keys`, кадров нет -> за 1 с есть запись `silence`, первая — `0.3 <= age <= 1.0`.
     - `test_disabled_modes_never_call_back`: (1) `on_silence=cb`, `silence_s=0.0`; (2) `on_silence=cb`, `silence_s=-1`; пусто 1 с -> 0 вызовов `cb` в обоих; (3) `silence_s=0.3` без `on_silence`, `set_keys({"cam_a": 30})` -> пусто 1 с, исключений нет, `stats()["cam_a"]["errors"] == 0`.
     - `test_steady_frames_report_nothing`: `silence_s 0.5`, `set_keys({"cam_a": 30})`, кадр каждые 50 мс 1,5 с -> ноль записей `silence` (ни чисел, ни `None`); затем кадры прекратились -> первая запись `0.5 <= age <= 1.0`.
     - `test_silence_is_per_key`: `set_keys({"cam_a": 30, "cam_b": 30})`, `cam_b` кормится каждые 50 мс, `cam_a` нет, 1,5 с -> записи `silence` только для `cam_a`, и для `cam_a` их не меньше одной.
     - `test_unshown_frame_keeps_silence` (параметризован: `sink` возвращает `False` / `sink` бросает исключение): ждать запись `silence` с `int(age) == 1`; положить кадр; `sink` на него не показывает (вариант параметра) -> первая запись `silence` после этого `sink` имеет `int(age) == 2`; записей `None` нет.
     - `test_stats_keys_unchanged`: после тишины и кадра `set(pump.stats()["cam_a"])` == пяти именам п.1.

FORBIDDEN PATHS (no edits, no reads of implementation): multiprocess_framework/modules/frontend_module/bridge/frame_pump.py, multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence_hazards.py, plans/2026-11-25_multicam-observability/tasks/W2-c.md
FILES (complete list — nothing else; need another file -> stop and report):
  1. multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py — new

REDS (expected RED before code):
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_silence_reported_once_per_second_with_bounds
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_frame_after_silence_reports_none_once
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_configured_key_without_any_frame_is_silent
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_disabled_modes_never_call_back
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_steady_frames_report_nothing
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_silence_is_per_key
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_unshown_frame_keeps_silence
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_stats_keys_unchanged

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py

OUT OF SCOPE: плашка в prototype, существующие тесты насоса.
REPORT: STATUS (DONE|BLOCKED), files, число собранных и красных (все 8 — `TypeError` на новом именованном параметре внутри теста, не на сборе).
