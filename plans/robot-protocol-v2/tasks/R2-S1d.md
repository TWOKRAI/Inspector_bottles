### Task R2-S1d — СТОП оператора не запирается готовностью драйвера

**Ред. 2** (после стадии 0 и вердикта cto). **Level:** Senior+ (Opus). **Assignee:** teamlead.
**Goal:** `stop` и `abort` оператора уходят на робота, когда драйвер «не готов» после обрыва или неудачного connect;
молчаливой потери СТОПа этими двумя командами нет.
**Module contract:** `OpSpec.needs_link` (есть); новый `ModbusDevice.drop_link()`. **Dependencies:** R2-S1a.

#### Правило и факты
Правило — `docs/reviews/2026-11-27_task-R2-S1a-cto.md`: СТОП пишется, когда прошивка v2 этим клиентом подтверждена и
связь не закрыта законченным намеренным `disconnect()`; готовность его не запирает. Воспроизведено: затвор
`manager.py:742`; `probe()` сбрасывает `_probed` в начале (`client_v2.py:398-399`); `disconnect()` в
`driver.py:365` и `:627` обнуляет клиента SDK — СТОП в этот миг не уходит.

#### Дизайн
1. `client_v2.py`: отдельный факт «прошивка подтверждена» (поле и свойство). Ставится удачной пробой, снимается только
   `WrongFirmware` или сменой клиента; в начале пробы НЕ сбрасывается. Его читают `issue_stop` и `_stop_reachable`
   (`stop.py:91-99`). `probed` для остального без изменений.
2. `spi.py`: `needs_link=False` у `_ABORT` и у `stop` v2. `manager.py` не менять.
3. `ops.py::_operator_stop`: отказ, когда не `_stop_reachable`. Запись через помощник в `stop.py` (рядом с
   `_write_stop_twice`): **повтор ровно один и только** когда `__cause__` первой ошибки — встроенный `ConnectionError`
   (10053, 10054, `BrokenPipeError`: мгновенный отказ мёртвого сокета). Без повтора: причина из pymodbus (таймаут,
   `ConnectionException`), `ModbusIOError` без причины, `ModbusConnectionError`, всё прочее. Итоговая неудача —
   `stop_unconfirmed`, «стоп не подтверждён роботом» один раз на нажатие. Запись прошла, а чтение эха упало
   транспортом — `ok`, `echo: False`. Любой отказ `stop`/`abort` (в том числе «нет связи» и «драйвер не создан»)
   несёт ключи `message` и `error`; форму отказа по плохому уровню не менять (`test_t53r2_stop_hazards.py:637`).
4. `Services/modbus/core/device.py`: `drop_link()` — под замком устройства закрыть сокет БЕЗ обнуления клиента SDK,
   связь снята, `session += 1`; `on_error` и счётчики не трогаются. `ExchangeLogTransport` пропускает вызов (разрешение
   владельца 2026-11-27). `ExchangeLogTransport` передаёт вызов внутреннему транспорту; `core` зовёт приватный
   `_drop_socket` (`sdk/client.py:259`) через публичный метод SDK-клиента.
5. `driver.py:365` и `:627`: звать `drop_link`, если он есть у транспорта, иначе `disconnect()` как раньше (дублёры
   транспорта не меняются). В `_link_lost` дополнительно не трогать транспорт, который уже не подключён. Явный reconnect
   в путь СТОП не добавлять.
6. `state.py`: `stop_unconfirmed` переживает неудачный connect (убрать сброс из `_connect_reset_locked`, снимать в
   удачной ветке `connect_finish`; `connect_reset()` снимает явно).
7. `robot_driver.py` (v1): `_op_abort` без связи — прежний отказ «не подключено», 0 записей.
8. `plugin.py::_driver_call`: «журнала нет: драйвер не создан» — только у операций журнала, у остальных нейтрально.
9. Из ревью R2-S1a (minor): повторный `disconnect` после jog с упавшим стопом не объявляет «не подтверждён», когда
   связь уже закрыта намеренно; `_stop_jog(run, write=None)` вместо копии в `_request_stop`.
10. `DECISIONS.md` (device_hub): ADR-DH-016 — правило, инвариант «клиента SDK обнуляет только намеренное отключение»,
    отмена `R2-S1a.md:35`, **принятые исключения**: `pause_all` («ОСТАНОВИТЬ») пропускает неготового робота до R2-S1e;
    СТОП идёт на потоке приёма команд (мгновенный отказ плюс один бюджет записи; держит остальные команды хаба) — до
    R2-S1f; `stop_unconfirmed` держится и после удачного следующего СТОПа, до удачного connect.

#### Файлы
`Services/robot_comm/core/client_v2.py`; `Services/modbus/`: `core/device.py`, `sdk/client.py` (+ `interfaces`/
`__init__`, если там список), `README.md`, `STATUS.md`; `Services/device_hub/`: `spi.py`, `DECISIONS.md`, `STATUS.md`,
`drivers/exchange_log.py`, `drivers/robot_driver.py`, `drivers/robot_driver_v2/{ops,driver,stop,state,jog}.py`;
`Plugins/hub/device_hub/plugin.py`; тесты: новые (в т. ч. в `Services/modbus/tests` — причина ошибки записи
сохраняется через `from exc`); `tests/test_spi_contract.py:197-198`; `tests/test_r2s1a_hazards.py` (tick_first теперь
«STOP на проводе» — авторский тест, лид разрешает).

#### Приёмка
Команды через хаб устройств (`robot_stop` HARD, `robot_abort`), робот — сим v2 по TCP, тик включён.
- [ ] A1. Робот движется; повторный connect уже подключённого устройства не удался (`on_connect.servo: false` и
  занятый робот, либо введённый сбой в `_run_on_connect`): ответ `ok`, `STOP_REQ` на проводе, робот встал — для обеих.
- [ ] A2а. Обрыв и возврат связи во время движения, тик обрыв заметил; СТОП до удачного переподключения: записан,
  робот встал.
- [ ] A2б. Обрыв (FIN и RST), после него обменов не было, ОДНО нажатие: ответ `ok`, кадры STOP ровно `[2]`, < 0,5 с.
- [ ] A3. После законченного намеренного отключения: ответ-ошибка, 0 кадров, нового TCP нет.
- [ ] A4. Прошивка этим клиентом ни разу не подтверждена, или `WrongFirmware`: 0 кадров, ответ-ошибка.
- [ ] A5. Мёртвая связь (порт закрыт; `timeout_sec=1.0`, `retries=1`): ответ-ошибка за < 3 с, «стоп не подтверждён
  роботом» опубликован один раз на нажатие, `stop_unconfirmed` True и после следующей неудачной попытки connect. При
  таймауте записи второй записи драйвера нет. Задержку команды второго устройства измерить числом (не ассерт).
- [ ] A6. v1 без связи: `robot_abort` — `status: error`, `message` «Устройство '<id>' не подключено», 0 записей.
- [ ] A7. Порядок «тик первым» при задании после обрыва: STOP на проводе (`disconnect` и `request_stop`).
- [ ] A8. `robot_servo`, `robot_jog_step` в неготовности по-прежнему отклоняются, 0 кадров.
- [ ] A9. СТОП, навязанный в окно между закрытием и открытием транспорта в connect: записан.
- [ ] A10. СТОП во время идущей повторной пробы и после пробы, упавшей на вводе-выводе: `STOP_REQ` на проводе.
- [ ] A11. Повторный `disconnect` после jog с упавшим стопом: второго «не подтверждён» нет.

**Out of scope:** `manager.py`; `pause_all` (R2-S1e); СТОП вне потока приёма (R2-S1f); `jog_release` и `program_abort`
остаются под затвором; `_run_on_connect` и серво (R2-S1); явный reconnect; GUI; прошивка.
**Gate:** наборы `Services/{modbus,vfd_comm,robot_comm,device_hub}/tests`, `Plugins/{hub/device_hub,sinks/modbus_sink}/
tests`; через `scripts/machine_gate.sh`; в worktree `PYTHONPATH=<корень>`, `uv sync` не делать.
**Handoff:** `docs/handoffs/<дата>_task-R2-S1d-<роль>.md`, если не закончил.
