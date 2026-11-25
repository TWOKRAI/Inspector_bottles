# W2-a — бриф tester (общий файл на W2-a и W2-a1)

Спавн: `python scripts/plans_ledger.py brief W2-a.tester --plan plans/2026-11-25_multicam-observability`. Worktree на коммите ДО реализации; код реализации закрыт.

TASK: W2-a — слепые приёмочные тесты потери связи и переподключения камеры (RED до кода)   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: tester
CHAIN: лид (бриф, стадия 0) -> tester -> teamlead W2-a и developer W2-a1 (делают тесты зелёными) -> лид (инъекции, ревью)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. КОНТРАКТ СЕАНСА. `DeviceSession(..., run=<непустой план>, timeout_ms=100, reconnect=False, link_silence_s=0.0, reconnect_interval_s=2.0)` — три новых именованных параметра, умолчания указаны. План — непустой кортеж `Step` (`Services.camera_device.params`) с `binding` узла фейка: проба идёт на `run[0].binding`. Шаг поля `trigger_mode` в плане задаёт режим: `"On"` — аппаратный триггер (тишину решает проба), другое значение — свободный поток (тишина `link_silence_s` = потеря без пробы), шага нет — решает проба. Новое состояние `lost` держится от потери до `grabbing` или стопа. `session.link()` -> `{"state": "up"|"idle"|"silent"|"lost"|"off", "reconnecting", "outages", "attempts", "last_outage_s", "lost_for_s"}`; `session.reconnecting` — `bool`. `Services.camera_device.interface.LinkEventSource` — `runtime_checkable` протокол с `drain_link_events() -> list[str]`.
  2. КОНТРАКТ ПЛАГИНА. Поля `CameraDeviceRegisters`: `reconnect` (умолч. `False`), `link_silence_s` (`3.0`), `reconnect_interval_s` (`2.0`). Плагин публикует `session.link()` в своём state под ключом `link`; при `lost` health `degraded`, после возврата — `ok`. Причина готовности при `lost`: `[{"severity": "failure", "reason": "связь с камерой потеряна, переподключение"}]`.
  3. Литералы лога (логгер `camera_device.session`): WARNING начинается `session: связь с прибором потеряна (` и оканчивается `); переподключение каждые 0.5 с` (при `reconnect_interval_s 0.5`); INFO начинается `session: связь восстановлена за ` и содержит `, попыток `.
  4. Фейк (`Services.camera_device.testing.fake_port`): `make_port(**opts)` / `FakePort(nodes, *, busy_for_s=0.0, capabilities=ALL_CAPABILITIES, open_delay_s=0.0, frame_period_s=0.0, get_frame_errors=0, get_frame_script=(), ...)`; новая фабрика `make_link_event_port(**opts)` — те же параметры; `port.calls` — список `(имя, args, thread_ident)`; `port.max_open_handles`. Новое: `disconnect()` — `get_frame` ждёт `timeout_ms` и даёт `None`, `get_param` -> `PortError("network")`, `open` -> `PortError("not_found")`; `restore()` — `open` снова работает, но кадры идут только после нового `open` (прибор бросил сеанс). `LinkEventFakePort(FakePort)` — с `emit_link_event(kind)` и `drain_link_events()`; у `FakePort` этих методов нет. Узлы фейка и план — по образцу существующих тестов с настоящим `DeviceSession` (`git grep -l "DeviceSession(" -- Services/camera_device/tests`). `open` повторов считайте своей обёрткой над `port.open` или по `port.calls`.
  5. Интервалы: `reconnect_interval_s 0.5`, `link_silence_s 0.5` (кроме оговорённых). Ожидание — опрос с дедлайном 5 с; зависающий вызов — в daemon-потоке с `join(timeout)`. Импорты тестируемых классов — внутри теста. Новый `.py`: `__all__ = []`, `Purpose:`. Имена тестов плагина содержат `plugin`, сеанса — нет. Каждый сценарий, кроме охранного и `test_plugin_register_defaults`, передаёт `reconnect=True` (плагину — конфиг `reconnect: true`).
  6. Сценарии сеанса:
     - `test_disconnect_event_marks_lost_then_reconnects`: `make_link_event_port(...)`, `reconnect True`, `link_silence_s 0`; только `emit_link_event("disconnected")` (без `disconnect()`), и только ПОСЛЕ входа в `grabbing` -> `lost`, `link()["outages"] == 1`; затем второй `open`, состояние `grabbing`, `link()["state"] == "up"`.
     - `test_free_run_silence_is_lost_even_if_probe_answers`: шаг `trigger_mode "Off"`, `frame_period_s 60`, `timeout_ms 100`, `get_param` отвечает -> не позже 3 с `lost`, одна WARNING п.3.
     - `test_hw_trigger_silence_with_answering_probe_is_idle`: шаг `trigger_mode "On"`, `frame_period_s 60`, `timeout_ms 100` -> через 2 с `grabbing`, `link()["state"] == "idle"`, WARNING п.3 нет.
     - `test_recovery_requires_reopen_and_logs_info_once`: `disconnect()`, `lost`, `restore()` -> второй `open` после `restore()` обязателен, ровно одна INFO п.3, кадры идут, `last_error is None`, `link()["state"] == "up"`.
     - `test_lost_holds_until_grabbing`: потеря из `grabbing`, `disconnect()` держится 2 с (повторы падают `not_found`) -> всё это время состояние `lost` (опрос каждые 0,1 с), `last_error` содержит `not_found`, `link()["attempts"] >= 2`.
     - `test_stop_during_backoff_returns_promptly`: `reconnect_interval_s 10.0`, `lost` -> `stop(2.0)` вернулся быстрее 2,0 с; `device_held False`; состояние `closed`; за следующую 1 с нового `open` нет.
     - `test_stop_after_failed_busy_attempt_ends_loop`: `busy_for_s 60`, `reconnect True` -> после хотя бы одного повтора `stop()` -> `closed`, `device_held False`, за следующую 1 с нового `open` нет.
     - `test_reconnect_off_free_run_silence_is_error`: `reconnect False`, шаг `trigger_mode "Off"`, кадры шли и прекратились (`link_silence_s 0.5`) -> состояние `error`, `link()["state"] == "lost"`, `last_error` непуст, одна ERROR, начинается `session: связь с прибором потеряна (`; за 2 с нового `open` нет.
     - `test_free_run_reopen_without_frames_stays_lost`: шаг `trigger_mode "Off"`, потеря, `frame_period_s 60` всё время -> за 3 × `link_silence_s` после `lost` состояние ни разу не `grabbing`, WARNING ровно одна, INFO «восстановлена» ноль.
     - `test_busy_at_start_retries_until_free`: `busy_for_s 1.0`, `reconnect True` -> `start()` вернул `False` и в этот момент `reconnecting True`; затем `grabbing`, открытий не меньше 2.
     - `test_write_during_outage_reaches_reopened_device`: потеря, во время `lost` — `apply([Step(ExposureTime=5000)], "restart")` -> после возврата в журнале фейка запись `ExposureTime 5000` после второго `open`.
     - `test_reconnect_off_keeps_terminal_error` (ОХРАННЫЙ, зелёный до кода): сеанс без новых параметров, `get_frame_errors 3` -> `error`; после 2 с нового `open` нет.
  7. Сценарии плагина (настоящий плагин камеры + `DeviceSession` + фейк, по образцу тестов `plugin_base` в каталоге):
     - `test_plugin_lost_readiness_is_failure_literal`: `reconnect True`, потеря -> `readiness(ctx)` == список п.2.
     - `test_plugin_publishes_link_and_degrades_on_loss`: в state плагина ключ `link`, `link.state == "lost"` при потере и health `degraded`; после возврата `link.state == "up"` и health `ok`.
     - `test_plugin_register_defaults`: `reconnect False`, `link_silence_s 3.0`, `reconnect_interval_s 2.0`.

FORBIDDEN PATHS (no edits, no reads of implementation): Services/camera_device/interface.py, Services/camera_device/session.py, Services/camera_device/plugin_base.py, Services/camera_device/registers_base.py, Services/camera_device/testing/fake_port.py, Services/camera_device/tests/test_link_reconnect_hazards.py, Services/camera_device/tests/test_link_plugin_hazards.py, plans/2026-11-25_multicam-observability/tasks/W2-a.md, plans/2026-11-25_multicam-observability/tasks/W2-a1.md, docs/reviews/2026-11-25_obs-audit-multicam.md, docs/reviews/2026-11-25_obs-audit-multicam-2-control-tasks.md, docs/reviews/2026-11-25_obs-audit-multicam-3-reliability-cto-map.md
FILES (complete list — nothing else; need another file -> stop and report):
  1. Services/camera_device/tests/test_link_reconnect_contract.py — new

REDS (expected RED before code):
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_disconnect_event_marks_lost_then_reconnects
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_free_run_silence_is_lost_even_if_probe_answers
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_hw_trigger_silence_with_answering_probe_is_idle
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_recovery_requires_reopen_and_logs_info_once
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_lost_holds_until_grabbing
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_stop_during_backoff_returns_promptly
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_stop_after_failed_busy_attempt_ends_loop
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_busy_at_start_retries_until_free
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_write_during_outage_reaches_reopened_device
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_reconnect_off_free_run_silence_is_error

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short Services/camera_device/tests/test_link_reconnect_contract.py

OUT OF SCOPE: драйвер `mvs`, GUI, рецепты, существующие тесты пакета.
REPORT: STATUS (DONE|BLOCKED), files, число собранных и красных (15 тестов: 14 красных, охранный зелёный; `test_free_run_reopen…` и три теста `plugin` — тоже красные, в REDS не уместились); RED падает внутри теста (`TypeError` на новом параметре, `AttributeError`, утверждение), не на сборе. Фейку не хватает ручки п.4 — ожидаемый красный, фейк вы не правите.
