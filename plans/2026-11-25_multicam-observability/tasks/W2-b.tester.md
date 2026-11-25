# W2-b — бриф tester

Спавн: `python scripts/plans_ledger.py brief W2-b.tester --plan plans/2026-11-25_multicam-observability`. Worktree на коммите ДО реализации; код реализации закрыт.

TASK: W2-b — слепые приёмочные тесты потока-владельца считывателя (RED до кода)   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: tester
CHAIN: лид (бриф, стадия 0) -> tester -> teamlead (делает тесты зелёными) -> лид (инъекции, ревью)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. КОНТРАКТ. Регистр `CodeReaderSdkRegisters` получает `reconnect` (умолч. `True`), `link_silence_s` (`3.0`), `reconnect_interval_s` (`2.0`). Живая запись поля триггера ставится в очередь: `register_update` возвращается, не дожидаясь перезапуска; применяется последнее значение поля. `CodeReaderSdkPlugin.readiness(ctx)` — новый хук. `get_status` несёт блок `link` с ключами `state`, `outages`, `attempts`, `last_outage_s`, `last_frame_age_s`. Непрерывный режим: триггер не задан, или `trigger_mode "Off"`, или `trigger_mode "On"` + `trigger_source "SelfTrigger"`.
  2. Литералы: INFO `CodeReaderSdkPlugin[id_a]: apply field=trigger_mode policy=restart queued`; WARNING, начинается `CodeReaderSdkPlugin[id_a]: нет кадров ` и оканчивается ` с, прибор молчит`; INFO, начинается `CodeReaderSdkPlugin[id_a]: кадры возобновились через `; INFO, начинается `CodeReaderSdkPlugin[id_a]: прибор возвращён, попыток `. Причины готовности: `{"severity": "failure", "reason": "считыватель: нет кадров"}`; `{"severity": "failure", "reason": "считыватель: ошибка прибора, переподключение"}`; при `reconnect False` — `{"severity": "failure", "reason": "считыватель: ошибка прибора"}`.
  3. Настоящие объекты: `RegistersManager` + `PluginOrchestrator._on_register_update` по образцу `Services/code_reader/tests/test_sdk_trigger_live_contract.py` (W1-b). Фейк прибора — `FakeNodeApi` из `Services/code_reader/tests/test_sdk_trigger.py`; «кадров нет» и «ошибка get_frame» — подклассом в СВОЁМ файле (`test_sdk_trigger.py` не правится). `reader_id "id_a"`, `link_silence_s 0.5`, `reconnect_interval_s 0.5`. Ожидание — опрос с дедлайном 5 с; зависающий вызов — в daemon-потоке с `join(timeout)`.
  4. Импорты тестируемых классов — внутри теста. Новый `.py`: `__all__ = []`, `Purpose:`.
  5. Сценарии:
     - `test_register_update_returns_before_restart_finishes`: фейк задерживает `stop` на 1,5 с; `register_update trigger_mode "On"` при захвате -> вызов вернулся меньше чем за 0,5 с; затем (опрос) одна INFO `... restarted=True applied=True` (литерал W1-b).
     - `test_burst_of_writes_applies_last_value_once`: пять записей `trigger_period_ms` 41..45 подряд -> последнее записанное в фейк значение `TriggerSelfTriggerPeriod` равно 45; перезапусков не больше 2.
     - `test_silence_in_free_run_marks_lost_with_warning`: триггер не задан, захват идёт, кадры прекратились -> одна WARNING из п.2; `readiness` == `[{"severity": "failure", "reason": "считыватель: нет кадров"}]`; `link.state == "lost"`.
     - `test_silence_in_hardware_trigger_is_not_lost`: `trigger_mode "On"`, `trigger_source "Line0"`, кадров нет 2 с -> WARNING нет, `readiness == []`, `link.state == "silent"`.
     - `test_frames_resume_logs_info_and_clears_readiness`: продолжение третьего сценария, кадры пошли -> одна INFO «кадры возобновились», `readiness == []`, `link.outages == 1`.
     - `test_error_state_is_retaken_automatically`: три ошибки `get_frame` подряд -> состояние читателя `error`, причина с «переподключение»; фейк снова отдаёт кадры -> без команды `take_device` состояние `running`, INFO «прибор возвращён».
     - `test_reconnect_off_keeps_adr_cr_009`: `reconnect False`, три ошибки -> `error`; 2 с — новых открытий нет; команда `take_device` возвращает прибор.

FORBIDDEN PATHS (no edits, no reads of implementation): Services/code_reader/core/sdk_reader.py, Services/code_reader/plugin/sdk_plugin.py, Services/code_reader/plugin/sdk_registers.py, Services/code_reader/tests/test_reader_owner_hazards.py, plans/2026-11-25_multicam-observability/tasks/W2-b.md, docs/reviews/2026-11-25_obs-audit-multicam.md, docs/reviews/2026-11-25_obs-audit-multicam-2-control-tasks.md, docs/reviews/2026-11-25_obs-audit-multicam-3-reliability-cto-map.md
FILES (complete list — nothing else; need another file -> stop and report):
  1. Services/code_reader/tests/test_reader_link_contract.py — new

REDS (expected RED before code):
  - Services/code_reader/tests/test_reader_link_contract.py::test_register_update_returns_before_restart_finishes
  - Services/code_reader/tests/test_reader_link_contract.py::test_burst_of_writes_applies_last_value_once
  - Services/code_reader/tests/test_reader_link_contract.py::test_silence_in_free_run_marks_lost_with_warning
  - Services/code_reader/tests/test_reader_link_contract.py::test_silence_in_hardware_trigger_is_not_lost
  - Services/code_reader/tests/test_reader_link_contract.py::test_frames_resume_logs_info_and_clears_readiness
  - Services/code_reader/tests/test_reader_link_contract.py::test_error_state_is_retaken_automatically
  - Services/code_reader/tests/test_reader_link_contract.py::test_reconnect_off_keeps_adr_cr_009

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short Services/code_reader/tests/test_reader_link_contract.py

OUT OF SCOPE: read-back триггера, TCP-плагин, существующие тесты пакета.
REPORT: STATUS (DONE|BLOCKED), files, число собранных и красных; RED падает внутри теста, не на сборе. Если `FakeNodeApi` не умеет «кадров нет» без ошибки — подкласс в своём файле; не умеет и так — STOP и отчёт лиду.
