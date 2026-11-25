# Task W2-a: камера — потеря связи видна, сеанс переподключается сам [VERTICAL SLICE]

- **Статус:** [PENDING] · **Level:** Senior+ · **Assignee:** teamlead
- **Module contract:** public-api-change (`Services/camera_device/interface.py`: новый `LinkEventSource`, новое состояние сеанса `lost`; новые поля регистра)
- **Dependencies:** волна 1 слита в `integ/multicam-obs` (W1-a + W1-a2); решение Р-W2-1 нужно только для рецепта (W2-h), не для кода
- **Gate:** `machine_gate.sh light <session>` по файлам TESTS; радиус `Services/camera_device/tests` (medium) против снимка лида на базе волны 2
- **Files:** `Services/camera_device/interface.py`, `Services/camera_device/session.py`, `Services/camera_device/plugin_base.py`, `Services/camera_device/registers_base.py`, `Services/camera_device/testing/fake_port.py`, `Services/camera_device/tests/test_link_reconnect_hazards.py`
- **Acceptance:** блок ACCEPTANCE; файл tester-а зелёный
- **Handoff:** reviewer (стадия 0, opus) -> tester (слепой RED) -> teamlead -> лид (инъекции) -> reviewer (стадия 5, opus)
- **ФАЙЛ TESTER-А (teamlead не правит):** `Services/camera_device/tests/test_link_reconnect_contract.py`

Основание (стенд 2026-11-25, `main` `743641727`): кабель камеры вынут — `state grabbing`, health ok, errors 0, ноль строк лога; после возврата кабеля кадров нет больше минуты. Код (`mco-d-w1-a`): `get_frame` по таймауту отдаёт `None` (`driver.py:426-428`), `_grab_loop` считает `None` успехом (`session.py:649`), очередь `port.exceptions` никто не читает (`driver.py:232,243-245`), пути переподключения нет (`session.py:10`, ADR-CR-009). Решение владельца 3 (2026-11-25): переподключение в прогоне без администратора — пересматривает ADR-CR-009 для камеры (триггер возврата записан в самом ADR).

TASK: W2-a — потеря связи камеры распознаётся, сеанс сам переподключается в своём потоке-владельце   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: teamlead
CHAIN: reviewer (стадия 0) -> tester (слепой RED) -> you -> лид (инъекции) -> reviewer (стадия 5)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. `interface.py`: `type LinkEvent = Literal["disconnected", "other"]`; `@runtime_checkable class LinkEventSource(Protocol)` с одним методом `drain_link_events(self) -> list[LinkEvent]` (не блокирует; события с прошлого вызова; зовётся только из потока-владельца). В `DevicePort` член НЕ добавляется (урок W1-a: новый член `@runtime_checkable` красит `isinstance` у `MvsPort` до слияния W2-a2). Состояние `lost` добавить в каждый список/`Literal` состояний сеанса (найти: `git grep -n '"not_found"' -- Services/camera_device/interface.py Services/camera_device/session.py`).
  2. `registers_base.py`, поля `CameraDeviceRegisters` (без `apply`, как `device_ip`): `reconnect: bool = True` («Переподключаться при потере связи»), `link_silence_s: float = 3.0` (`min 0`, `max 60`; 0 — проверка тишины выключена), `reconnect_interval_s: float = 2.0` (`min 0.5`, `max 60`).
  3. `session.py`, конструктор `DeviceSession`: три именованных параметра с теми же именами; умолчания сеанса — `reconnect=False`, `link_silence_s=0.0`, `reconnect_interval_s=2.0` (прежние тесты сеанса не меняют поведения). Плагин передаёт значения регистра там, где строит сеанс (`_ensure_session`).
  4. `_grab_loop` возвращает исход `Literal["stopped", "failed", "lost"]` вместо `bool` (все вызовы — в `_owner_main`). Внутри: `last_frame = time.monotonic()` на входе и на каждом кадре; `last_probe = last_frame`. После каждого возврата `get_frame`: (а) порт `isinstance(port, LinkEventSource)` и `"disconnected" in port.drain_link_events()` -> `self._lost_reason = "событие прибора disconnected"`, `return "lost"`; (б) `link_silence_s > 0`, `now - last_frame >= link_silence_s`, `now - last_probe >= link_silence_s` -> `last_probe = now`; проба `self._port_call("probe", self._port.get_param, <узел>)`, где `<узел>` — узел первого шага текущего плана run (`self._run`); плана нет -> `self._link = "silent"` без пробы; `PortError` пробы -> `self._lost_reason = f"тишина {silence:.1f} с, проба: {describe_error(exc)}"`, `return "lost"`; проба ответила -> `self._link = "idle"` (прибор жив, кадров нет: триггер). Кадр -> `self._link = "up"`. Три `PortError` подряд -> прежний `_fail("error", exc)`, `return "failed"`.
  5. `_owner_main`: тело от `acquire` до `_grab_loop` — в цикле переподключения. Исход `"stopped"` или `stop_evt()` -> выход как сейчас. Исход `"lost"`/`"failed"` или `PortError` при `acquire/open/apply/start_grabbing`, и `self._reconnect`: `_cleanup(hold.grabbing, False, hold.opened, hold.acquired)` (без `rest`), `hold = _Hold()`; состояние `lost` (для `"lost"`) или вид отказа (`busy`/`not_found`/`error`, как `_failed_state`); `self._reconnecting = True`; первая потеря выхода — WARNING `session: связь с прибором потеряна (<причина>); переподключение каждые <interval:g> с`, `self._outages += 1`, `self._lost_since = time.monotonic()`; пока не вернулся — WARNING не чаще раза в 60 с `session: прибора нет <s:.0f> с, попыток <k>`; ожидание `cycle_stop.wait(reconnect_interval_s)` с проверкой `worker_stop` (стоп прерывает ожидание); `self._attempts += 1`; снова `acquire`. Вход в `grabbing` после потери -> INFO `session: связь восстановлена за <s:.1f> с, попыток <k>`, `_reconnecting = False`, `_last_outage_s = s`, `_link = "up"`. Без `self._reconnect` — поведение прежнее (терминальное состояние). Команда старта (`cmd.finish`) получает итог ПЕРВОЙ попытки; дальнейшие попытки команд не ждут.
  6. Свойство сеанса `link() -> dict` (без замка, голые атрибуты, как `state` для `readiness`): `{"state": "up"|"idle"|"silent"|"lost", "reconnecting": bool, "outages": int, "attempts": int, "last_outage_s": float | None, "lost_for_s": float | None}`.
  7. `plugin_base.py`: блок `link` (п.6) в state плагина рядом с `stream` (там, где публикуются `device`/`params`, `_sync_events`); `readiness`: `st == "lost"` -> `[{"severity": "failure", "reason": "связь с камерой потеряна, переподключение"}]`; при `reconnecting` для `busy`/`not_found`/`error` к прежнему тексту добавить `", переподключение"`. Ключа `code` в причине НЕТ (форма причин, ADR-PM-061). `_FAILED` плагина += `"lost"` (инцидент и `degraded` на входе, `set_status("ok")` на выходе — прежняя ветка `_report_incidents`). `_FAILED` сеанса (`session.py:53`) не меняется: стоп во время `lost` даёт финальное `closed`.
  8. `testing/fake_port.py`: `disconnect()` — далее `get_frame` -> `None`, `get_param` -> `PortError("network", "get_param")`, `open` -> `PortError("not_found", "open")`; `restore()` — всё как до `disconnect`; `emit_link_event(kind)`; `drain_link_events()` есть, только если в `capabilities` фейка есть `"link_events"` (иначе атрибута нет — `isinstance` ложен); `ALL_CAPABILITIES` += `"link_events"`.

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. Services/camera_device/interface.py — `LinkEvent`, `LinkEventSource`, состояние `lost`
  2. Services/camera_device/session.py — параметры, исход `_grab_loop`, цикл переподключения, `link()`
  3. Services/camera_device/plugin_base.py — передача полей, блок `link`, `readiness`, `_FAILED`
  4. Services/camera_device/registers_base.py — три поля
  5. Services/camera_device/testing/fake_port.py — `disconnect`/`restore`/`emit_link_event`/`drain_link_events`
  6. Services/camera_device/tests/test_link_reconnect_hazards.py — новый, опасности (REDS 9-10)

REDS (predicted red tests; восемь — файл tester-а, `W2-a.tester.md`):
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_disconnect_event_marks_lost_then_reconnects
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_silence_with_failed_probe_marks_lost
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_silence_with_answering_probe_is_idle_not_lost
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_recovery_logs_info_once_and_frames_resume
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_lost_readiness_is_failure_literal
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_stop_during_backoff_returns_promptly
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_reconnect_off_keeps_terminal_error
  - Services/camera_device/tests/test_link_reconnect_contract.py::test_busy_at_start_retries_until_free
  - Services/camera_device/tests/test_link_reconnect_hazards.py::test_one_owner_thread_across_reconnects (счёт живых потоков-владельцев по имени: ровно 1 после 3 переподключений)
  - Services/camera_device/tests/test_link_reconnect_hazards.py::test_live_apply_accepted_before_loss_reaches_reopened_device (правка `exposure_time` при `grabbing`, потеря, возврат -> после второго `open` в журнале фейка записан НОВЫЙ `ExposureTime`)

ACCEPTANCE (every number with its command):
  - оба файла зелёные — `<py> -m pytest -q --tb=short Services/camera_device/tests/test_link_reconnect_contract.py Services/camera_device/tests/test_link_reconnect_hazards.py` -> exit 0
  - радиус — `<py> -m pytest -q --tb=no -rfE Services/camera_device/tests` (medium) -> красные = снимок лида
  - `ruff check -q` по шести путям FILES -> 0

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short Services/camera_device/tests/test_link_reconnect_contract.py Services/camera_device/tests/test_link_reconnect_hazards.py   (`<py>` — python основного `.venv`, `PYTHONPATH=<корень worktree>`)

OUT OF SCOPE: драйвер `mvs` (`drain_link_events`, короткий кадр — W2-a2); `device_select ip/index` и `device_host_ip` (W2-g); рецепт и политика `readiness` узла (W2-h, Р-W2-1); GUI-плашка (W2-c, W2-c2); `backend_ctl` (W2-d).
TRAPS: применённые вживую правки должны дойти до переоткрытого прибора — проверьте, обновляет ли принятая правка `self._run`; если нет — стоп и вопрос лиду (иначе после переподключения прибор получит план старта, а регистр — новое значение). Аппаратный триггер: тишина — норма, поэтому решает проба, а не тишина. Ожидание переподключения — только `Event.wait`, не `time.sleep` (стоп процесса 4,0 с). Сторож (`_start_watchdog`) один на цикл владельца: не запускать второй на попытке. `_port_call` ведёт сторож — проба идёт через него.
HANDOFF IN: none
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, раздел «Что оставил открытым / ненадёжно».
