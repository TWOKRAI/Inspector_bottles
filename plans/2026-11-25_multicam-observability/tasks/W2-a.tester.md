# W2-a — бриф tester

Спавн: `python scripts/plans_ledger.py brief W2-a.tester --plan plans/2026-11-25_multicam-observability`. Worktree на коммите ДО реализации; код реализации закрыт.

TASK: W2-a — слепые приёмочные тесты потери связи и переподключения камеры (RED до кода)   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: tester
CHAIN: лид (бриф, стадия 0) -> tester -> teamlead (делает тесты зелёными) -> лид (инъекции, ревью)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. КОНТРАКТ. `Services.camera_device.interface.LinkEventSource` — `runtime_checkable` протокол с методом `drain_link_events() -> list[str]` (виды `"disconnected"`, `"other"`). Регистр `CameraDeviceRegisters` получает поля `reconnect` (умолч. `True`), `link_silence_s` (умолч. `3.0`), `reconnect_interval_s` (умолч. `2.0`). Новое состояние сеанса `lost`. `DeviceSession.link()` -> словарь с ключами `state` (`up`|`idle`|`silent`|`lost`), `reconnecting`, `outages`, `attempts`, `last_outage_s`, `lost_for_s`. Плагин публикует этот словарь в своём state под ключом `link`.
  2. Литералы. WARNING `session: связь с прибором потеряна (` … `); переподключение каждые 0.5 с` (при `reconnect_interval_s 0.5`); INFO, начинается `session: связь восстановлена за `, содержит `, попыток `. Причина готовности при `lost`: `{"severity": "failure", "reason": "связь с камерой потеряна, переподключение"}`.
  3. Фейк `FakePort` (`Services.camera_device.testing.fake_port`): `disconnect()`, `restore()`, `emit_link_event("disconnected")`; метод `drain_link_events` есть только при `"link_events"` в `capabilities` фейка. Сеанс и плагин — настоящие объекты, по образцу существующих тестов `Services/camera_device/tests/` с настоящим `DeviceSession` (найдите `git grep -l "DeviceSession(" -- Services/camera_device/tests`). Интервалы короткие: `reconnect_interval_s 0.5`, `link_silence_s 0.5`. Ожидание — опрос с дедлайном 5 с; зависающий вызов — в daemon-потоке с `join(timeout)`.
  4. Импорты тестируемых классов — внутри теста. Новый `.py`: `__all__ = []`, `Purpose:`.
  5. Сценарии:
     - `test_disconnect_event_marks_lost_then_reconnects`: захват идёт; `emit_link_event("disconnected")` и `disconnect()` -> состояние `lost`, `link()["state"] == "lost"`, `outages == 1`; `restore()` -> состояние `grabbing`, `link()["state"] == "up"`, `attempts >= 1`.
     - `test_silence_with_failed_probe_marks_lost`: фейк без `link_events`; `link_silence_s 0.5`; `disconnect()` -> не позже 3 с состояние `lost`; одна WARNING из п.2.
     - `test_silence_with_answering_probe_is_idle_not_lost`: кадров нет (скрипт `none`), `get_param` отвечает -> через 2 с состояние `grabbing`, `link()["state"] == "idle"`, WARNING из п.2 нет.
     - `test_recovery_logs_info_once_and_frames_resume`: потеря, `restore()` -> ровно одна INFO из п.2; счётчик кадров плагина растёт после возврата.
     - `test_lost_readiness_is_failure_literal`: плагин при `lost` -> `readiness(ctx)` == список из одного словаря п.2.
     - `test_stop_during_backoff_returns_promptly`: `reconnect_interval_s 10.0`, прибор потерян -> `stop()` возвращается меньше чем за 2,0 с.
     - `test_reconnect_off_keeps_terminal_error`: `reconnect False`, три ошибки `get_frame` -> состояние `error`, после `restore()` 2 с — всё ещё `error`, новых `open` в журнале фейка нет.
     - `test_busy_at_start_retries_until_free`: `open` отвечает `PortError("busy")` два раза, потом успех -> состояние `grabbing`, открытий 3.

FORBIDDEN PATHS (no edits, no reads of implementation): Services/camera_device/interface.py, Services/camera_device/session.py, Services/camera_device/plugin_base.py, Services/camera_device/registers_base.py, Services/camera_device/testing/fake_port.py, Services/camera_device/tests/test_link_reconnect_hazards.py, plans/2026-11-25_multicam-observability/tasks/W2-a.md, docs/reviews/2026-11-25_obs-audit-multicam.md, docs/reviews/2026-11-25_obs-audit-multicam-2-control-tasks.md, docs/reviews/2026-11-25_obs-audit-multicam-3-reliability-cto-map.md
FILES (complete list — nothing else; need another file -> stop and report):
  1. Services/camera_device/tests/test_link_reconnect_contract.py — new

REDS (expected RED before code):
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_disconnect_event_marks_lost_then_reconnects
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_silence_with_failed_probe_marks_lost
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_silence_with_answering_probe_is_idle_not_lost
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_recovery_logs_info_once_and_frames_resume
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_lost_readiness_is_failure_literal
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_stop_during_backoff_returns_promptly
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_reconnect_off_keeps_terminal_error
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_busy_at_start_retries_until_free

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short Services/camera_device/tests/test_link_reconnect_contract.py

OUT OF SCOPE: драйвер `mvs`, GUI, рецепты, существующие тесты пакета.
REPORT: STATUS (DONE|BLOCKED), files, число собранных и красных; RED падает внутри теста (утверждение или `AttributeError`/`TypeError` на новом имени), не на сборе. Фейку не хватает ручки из п.3 — это ожидаемый красный, фейк вы не правите.
