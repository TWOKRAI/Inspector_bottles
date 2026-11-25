# W2-b — бриф tester (общий файл на W2-b и W2-b1)

Спавн: `python scripts/plans_ledger.py brief W2-b.tester --plan plans/2026-11-25_multicam-observability`. Worktree на коммите ДО реализации; код реализации закрыт.

TASK: W2-b — слепые приёмочные тесты потока-владельца считывателя (RED до кода)   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: tester
CHAIN: лид (бриф, стадия 0) -> tester -> teamlead W2-b и W2-b1 (делают тесты зелёными) -> лид (инъекции, ревью)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. КОНТРАКТ. Живая запись поля триггера ставится в очередь: `register_update` возвращается, не дожидаясь перезапуска; очередь применяется ОДНИМ применением (последнее значение поля). Поля `CodeReaderSdkRegisters`: `reconnect` (умолч. `False`), `link_silence_s` (`3.0`), `reconnect_interval_s` (`2.0`). `CodeReaderSdkPlugin.readiness(ctx)` — новый хук. `get_status` несёт блок `link` с ключами `state`, `outages`, `attempts`, `last_outage_s`, `last_frame_age_s`. Режим: непрерывный = `trigger_mode "Off"` или `"On"` + `trigger_source "SelfTrigger"`; пустой режим — неизвестен (тишина -> `link.state "silent"`, без `failure`); `Line0` — тишина `silent`.
  2. Литералы: INFO `CodeReaderSdkPlugin[id_a]: queued field=trigger_mode policy=restart`; WARNING начинается `CodeReaderSdkPlugin[id_a]: нет кадров ` и оканчивается ` с, прибор молчит`; INFO начинается `CodeReaderSdkPlugin[id_a]: кадры возобновились через `; INFO начинается `CodeReaderSdkPlugin[id_a]: прибор возвращён, попыток `. Причины: `{"severity": "failure", "reason": "считыватель: нет кадров"}`; `{"severity": "failure", "reason": "считыватель: ошибка прибора, переподключение"}`; при `reconnect False` — `{"severity": "failure", "reason": "считыватель: ошибка прибора"}`. Строки исхода W1-b (`... apply field=<поле> policy=restart restarted=True applied=True` и др.) — прежние.
  3. Настоящие объекты: `RegistersManager` + `PluginOrchestrator._on_register_update` по образцу `Services/code_reader/tests/test_sdk_trigger_live_contract.py`. Фейк — `FakeNodeApi` из `Services/code_reader/tests/test_sdk_trigger.py`: его `get_frame` по умолчанию даёт `None` (кадров нет); кадры — подклассом в СВОЁМ файле, возвращающим `make_raw(...)` из `Services/code_reader/tests/test_sdk_reader.py:129`; задержка `stop_grabbing`, «прибора нет» (перечисление пусто) и ошибки `get_frame` — тоже подклассом. `test_sdk_trigger.py` не правится. `reader_id "id_a"`, `link_silence_s 0.5`, `reconnect_interval_s 0.5`. Ожидание — опрос с дедлайном 5 с; зависающий вызов — в daemon-потоке с `join(timeout)`.
  4. Импорты тестируемых классов — внутри теста. Новый `.py`: `__all__ = []`, `Purpose:`.
  5. Сценарии:
     - `test_register_update_returns_before_restart_finishes`: `stop_grabbing` задержан на 1,5 с; `register_update trigger_mode "On"` при захвате -> вызов вернулся быстрее 0,5 с; затем (опрос) одна INFO `... restarted=True applied=True`.
     - `test_burst_of_writes_is_one_application`: `auto_start True`, `trigger_mode "On"`, `trigger_source "SelfTrigger"`, `stop_grabbing` задержан на 0,3 с; пять записей `trigger_period_ms` 41..45 подряд -> последняя запись узла в журнале фейка — `("set_int", "TriggerSelfTriggerPeriod", 45)`; открытий за тест не больше 3.
     - `test_silence_in_free_run_marks_lost_with_warning`: `reconnect True`, `trigger_mode "Off"`, кадры шли и прекратились -> одна WARNING п.2; `readiness` == `[{"severity": "failure", "reason": "считыватель: нет кадров"}]`; `link.state == "lost"`.
     - `test_silence_with_unknown_mode_is_silent`: триггер не задан, кадры прекратились, 2 с -> WARNING нет, `readiness == []`, `link.state == "silent"`.
     - `test_silence_in_hardware_trigger_is_silent`: `trigger_mode "On"`, `trigger_source "Line0"`, кадров нет 2 с -> WARNING нет, `readiness == []`, `link.state == "silent"`.
     - `test_frames_resume_logs_info_and_clears_readiness`: продолжение «free_run»: кадры пошли -> одна INFO «кадры возобновились», `readiness == []`, `link.outages == 1`.
     - `test_retake_keeps_trying_while_device_absent`: `reconnect True`; три ошибки `get_frame` -> отказ; перечисление пусто не меньше 3 интервалов -> всё это время причина «… переподключение»; прибор вернулся -> без команды `take_device` состояние `running`, `link.attempts >= 2`, INFO «прибор возвращён» (после первого кадра).
     - `test_reconnect_off_readiness_literal`: `reconnect False`, три ошибки -> `readiness == [{"severity": "failure", "reason": "считыватель: ошибка прибора"}]`; 2 с — новых открытий нет; команда `take_device` возвращает прибор.
     - `test_take_after_pause_is_not_lost`: `reconnect True`, `trigger_mode "Off"`; `release_device`, пауза 2 с, `take_device`, первый кадр через 0,3 с -> WARNING нет, `link.state` не `lost`.

FORBIDDEN PATHS (no edits, no reads of implementation): Services/code_reader/core/sdk_reader.py, Services/code_reader/plugin/sdk_plugin.py, Services/code_reader/plugin/sdk_registers.py, Services/code_reader/tests/test_reader_owner_hazards.py, Services/code_reader/tests/test_reader_link_hazards.py, plans/2026-11-25_multicam-observability/tasks/W2-b.md, plans/2026-11-25_multicam-observability/tasks/W2-b1.md, docs/reviews/2026-11-25_obs-audit-multicam.md, docs/reviews/2026-11-25_obs-audit-multicam-2-control-tasks.md, docs/reviews/2026-11-25_obs-audit-multicam-3-reliability-cto-map.md
FILES (complete list — nothing else; need another file -> stop and report):
  1. Services/code_reader/tests/test_reader_link_contract.py — new

REDS (expected RED before code):
  - Services/code_reader/tests/test_reader_link_contract.py::test_register_update_returns_before_restart_finishes
  - Services/code_reader/tests/test_reader_link_contract.py::test_burst_of_writes_is_one_application
  - Services/code_reader/tests/test_reader_link_contract.py::test_silence_in_free_run_marks_lost_with_warning
  - Services/code_reader/tests/test_reader_link_contract.py::test_silence_with_unknown_mode_is_silent
  - Services/code_reader/tests/test_reader_link_contract.py::test_silence_in_hardware_trigger_is_silent
  - Services/code_reader/tests/test_reader_link_contract.py::test_frames_resume_logs_info_and_clears_readiness
  - Services/code_reader/tests/test_reader_link_contract.py::test_retake_keeps_trying_while_device_absent
  - Services/code_reader/tests/test_reader_link_contract.py::test_reconnect_off_readiness_literal
  - Services/code_reader/tests/test_reader_link_contract.py::test_take_after_pause_is_not_lost

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short Services/code_reader/tests/test_reader_link_contract.py

OUT OF SCOPE: read-back триггера, TCP-плагин, существующие тесты пакета.
REPORT: STATUS (DONE|BLOCKED), files, число собранных и красных; RED падает внутри теста (утверждение, `AttributeError` на `readiness`/`link`, неизвестное поле регистра), не на сборе. Подкласс фейка не может дать нужное поведение — STOP и отчёт лиду.
