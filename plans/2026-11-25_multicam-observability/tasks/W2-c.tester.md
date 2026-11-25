# W2-c — бриф tester

Спавн: `python scripts/plans_ledger.py brief W2-c.tester --plan plans/2026-11-25_multicam-observability`. Worktree на коммите ДО реализации; код реализации закрыт.

TASK: W2-c — слепые приёмочные тесты колбэка тишины `FramePump` (RED до кода)   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: tester
CHAIN: лид (бриф, стадия 0) -> tester -> developer (делает тесты зелёными) -> лид (инъекции, ревью)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. КОНТРАКТ. `FramePump(mailbox, sink, parent=None, *, on_silence=None, silence_s=0.0)` (`multiprocess_framework.modules.frontend_module.bridge.frame_pump`). При `silence_s > 0` и заданном `on_silence`: ключ без нового кадра `silence_s` секунд и дольше -> `on_silence(key, age_s)` не чаще одного раза на целую секунду `age_s`; первый кадр после тишины -> `on_silence(key, None)` раньше, чем `sink(key, item)`. По умолчанию колбэк не зовётся никогда. Набор ключей словаря `stats()` прежний: `shown`, `errors`, `max_age_ms`, `window_max_age_ms`, `busy_ms_total`.
  2. Стенд: `QCoreApplication` (или `QApplication`) и фейк ящика с методами `take(key)` и `pending_keys()` по образцу `multiprocess_framework/modules/frontend_module/tests/test_frame_pump.py`; время — реальное, короткие пороги (`silence_s 0.3`), события Qt прокручиваются циклом с дедлайном 3 с. Порядок вызовов фиксирует общий список-журнал (`("silence", key, age)`, `("sink", key)`).
  3. Импорт `FramePump` — внутри теста. Новый `.py`: `__all__ = []`, `Purpose:`.
  4. Сценарии:
     - `test_silence_reported_after_threshold_once_per_second`: ключ `cam_a` через `set_keys({"cam_a": 30})`, один кадр, затем пусто 2,4 с -> в журнале не больше трёх записей `silence` (секунды 0, 1, 2), все `age >= 0.3`.
     - `test_frame_after_silence_reports_none_before_sink`: после тишины кладётся кадр -> в журнале `("silence", "cam_a", None)` стоит прямо перед `("sink", "cam_a")`.
     - `test_configured_key_without_any_frame_is_silent`: ключ задан `set_keys`, кадров нет вовсе -> через 1 с есть запись `silence` для него.
     - `test_disabled_by_default_no_callback`: `FramePump(mailbox, sink)` без новых параметров, пусто 1 с -> записей `silence` 0.
     - `test_stats_keys_unchanged`: после тишины и кадра `set(pump.stats()["cam_a"])` == пяти именам п.1.

FORBIDDEN PATHS (no edits, no reads of implementation): multiprocess_framework/modules/frontend_module/bridge/frame_pump.py, multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence_hazards.py, plans/2026-11-25_multicam-observability/tasks/W2-c.md
FILES (complete list — nothing else; need another file -> stop and report):
  1. multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py — new

REDS (expected RED before code):
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_silence_reported_after_threshold_once_per_second
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_frame_after_silence_reports_none_before_sink
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_configured_key_without_any_frame_is_silent
  - multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py::test_stats_keys_unchanged

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_framework/modules/frontend_module/tests/test_frame_pump_silence.py

OUT OF SCOPE: плашка в prototype, существующие тесты насоса.
REPORT: STATUS (DONE|BLOCKED), files, число собранных и красных; RED — `TypeError` на новом именованном параметре внутри теста, не на сборе; `test_disabled_by_default_no_callback` до кода зелёный (охранный) — это верно, он не в REDS.
