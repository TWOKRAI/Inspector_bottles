# R2-S1d: СТОП оператора не запирается готовностью — отчёт teamlead (2026-11-27)

**Статус:** DONE_WITH_CONCERNS. Дерево `.claude/worktrees/r2-stopgate`, ветка `fix/robot-stop-gate`.
**Коммиты:** `e51c607bc` feat(modbus) drop_link · `8d551e68d` feat(robot_comm) firmware_confirmed ·
`f841dc40b` fix(services) СТОП не запирается готовностью · (cherry-pick лида `9d6fd4c7d` — шов `_link_lost` сторожа).
**Не пушил, не сливал.** Этот отчёт не закоммичен.

## Прогоны приёмки (SHA `f841dc40b`)

Импорт из дерева (тот же cwd, что у pytest):
`D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\.claude\worktrees\r2-stopgate\Services\device_hub\__init__.py`.
Команда: `machine_gate.sh medium inspector-bottles-22 <main>/.venv/Scripts/python.exe -m pytest <каталог> -q --tb=long
-p no:cacheprovider -rfE -rP`. Полные журналы: scratchpad сессии, `acc_*.log`.

| Набор | Итог |
|-------|------|
| `Services/modbus/tests` | 217 passed |
| `Services/vfd_comm/tests` | 53 passed |
| `Services/robot_comm/tests` | **NO WINDOW** (rc 75, класс timed); light `test_client_v2.py`: 124 passed |
| `Plugins/hub/device_hub/tests` | 585 passed |
| `Plugins/sinks/modbus_sink/tests` | 14 passed |
| `Services/device_hub/tests` | **NO WINDOW** (rc 75, класс timed); light — см. ниже |
| light: слепой `test_r2s1d_stop_gate_acceptance.py` + `test_r2s1d_hazards.py` | 62 passed (43 + 19) |
| light: `test_r2s1a_hazards`, `test_r2s1a_link_drop_acceptance`, `test_spi_contract`, сторож, `test_robot_driver`, `test_exchange_log` | 222 passed |
| `python scripts/validate.py` | rc 0, «Ошибок нет» |
| `ruff check` / `ruff format --check` (17 изменённых .py) | чисто |

Полный `Services/device_hub/tests` прошёл раньше на коде до решения (c'), сессия `inspector-bottles-5d`:
`5 failed, 1256 passed, 6 skipped`. Все 5 разобраны: 2 — сторож (литерал файлов 77 + шов `_link_lost` лида),
1 — мой авторский тест R2-S1a (поведение поменялось по дизайну, тест переписан), 2 — R2-S1a A15 (эскалация, решение
лида c'). После правок каждый из них зелёный отдельным light-прогоном. Полный каталог на финальном SHA — у лида.

## MEASURE

- Таймаут записи STOP (A5 сторож): 2,016 с, кадры `[6, 6]` (повтор pymodbus тем же значением, второй записи драйвера нет).
- Мёртвый хост (A5): ответ-ошибка за 1,000–1,016 с; «не подтверждён» — один раз на нажатие.
- Задержка второго устройства тем же потоком после СТОП мёртвого: 1,015 с (СТОП 1,015 с).
- Нажатие во время идущего connect тика (мёртвый хост, `timeout_sec=1.0`, `retries=1`): 2,016–2,031 с (замок устройства
  до конца connect тика + своя попытка записи). Ответ-ошибка, «не подтверждён» один раз.
- СТОП в окне «сокет закрыт, не открыт» в connect: 0,016–0,031 с, `ok`, эхо есть.
- A2б (обрыв без обменов, одно нажатие): 0,031–0,047 с, `ok`, кадры `[2]`.
- v1 `abort` на мёртвом хосте (c'): 1,000–1,016 с (раньше затвор отказывал мгновенно).

## Инъекции (решения 1–6 и v1)

1. `Services/robot_comm/core/client_v2.py:810` (`firmware_confirmed` вместо `_probed`) и
   `Services/device_hub/drivers/robot_driver_v2/stop.py:110` — откат на `probed`: красные слепые A2а (4), A10 (4).
2. `Services/device_hub/spi.py:161` (`_ABORT`) и `:211` (`stop` v2) — убрать `needs_link=False`: красные слепые A1 (2),
   A2а (4), A9 (2), A10 (4), A5 `tick_noticed` (2); `test_spi_contract.py::test_command_table_routes_and_links`.
3. `stop.py:190` (`if not _dead_socket(exc): raise`) — (а) без повтора (`_write_operator_stop` -> `_write_stop`):
   красные мои `test_operator_stop_retries_once_only_on_builtin_connection_error[reset|aborted|broken_pipe]`,
   `..._both_writes_failed_publishes_once`, вероятно слепые A2б (4); (б) повтор на любой ошибке: красные слепой
   `test_a5_guard_timed_out_stop_write_is_not_written_again`, мои `...[pymodbus_timeout|pymodbus_connect|no_cause|session]`.
4. `Services/modbus/core/device.py:138` (`drop_socket()` -> `close()`): красные
   `test_r2s1d_drop_link.py::test_write_after_drop_link_opens_new_tcp_and_counters_stay`, мои
   `test_stop_between_drop_and_open_in_connect_is_written`, `test_stop_after_link_lost_then_connect_then_disconnect`,
   слепой A9 (2).
5. `driver.py:367` (`_drop_link()` -> `self._transport.disconnect()`): красные слепой A9 (2), мой connect-окно.
   `driver.py:631-634` (вернуть `disconnect()` и убрать `or not transport.is_connected`): красные слепой A7 (4),
   `test_r2s1a_hazards.py::test_stop_during_job_after_drop[tick_first-*]` (4), `test_link_lost_by_tick_stop_is_on_the_wire`,
   мой `_link_lost`-тест. `exchange_log.py:498` (всегда `disconnect`): мой `test_exchange_log_transport_drop_link_*`
   (2 случая `_InnerWithDrop`) и всё из п.4.
6. `state.py:308-312` `_connect_reset_locked` (вернуть `self._stop_unconfirmed = False`): красные слепой A5 `dead_link`
   (4, проверка после неудачного connect), мой `test_stop_unconfirmed_survives_failed_connect`.
7. v1 (c'): `Services/device_hub/drivers/robot_driver.py:613-622` — откат к «отказ без попытки»: красные
   `test_r2s1a_link_drop_acceptance.py::test_a15_v1_abort_arrives_and_link_recovers_after_drop` (2), мои
   `test_v1_abort_on_dead_host_one_attempt_measured` (`[3]` -> `[]`),
   `test_v1_abort_without_link_after_deliberate_close_has_no_frame_and_no_tcp[deliberate_disconnect]`.

Прогнозы не прогонялись (матрица — у лида). Пункт 3(а) для A2б — «вероятно»: что первая запись в A2б падает на мёртвом
сокете, доказано только косвенно (`test_dead_socket_write_keeps_builtin_connection_error_cause[fin|rst]`).

## Швы сторожа

Слепой файл приватных швов драйвера не добавляет (счёт функциями сторожа). Изменение сторожа — только литерал
`_SCANNED_FILES = 77`. Шов `_link_lost: 1` — из R2-S1a (`test_r2s1a_hazards.py:304`, `_force_order`), добавлен коммитом
лида `8856b5414` (у меня cherry-pick `9d6fd4c7d`). Мой `test_r2s1d_hazards.py` швов не добавляет: готовность через
`drv.state.set_ready`, подмены — на классах `RobotClientV2` / `RobotClient` / `ModbusDevice` / `ModbusSdkClient`.

## What I interpreted rather than followed

- Отказ v2 «не достижим» — текст драйвера «нет связи с роботом» (+ `error`), а не «Устройство '<id>' не подключено»:
  через хаб после намеренного отключения текст СТОПа сменился.
- Неудача записи СТОПа оператора — ответ `стоп не доставлен: <исключение>` с `error`.
- Эхо после удачной записи упало любым исключением (не только транспорта) — `ok`, `echo: False`, `tx_err` +1.
- П.9: повторный `disconnect` после намеренного не пишет стоп вовсе (не только молчит) — по правилу cto.
- `drop_link()` ставит `state=DISCONNECTED` и зовёт `on_status`, как `disconnect()`.
- ADR-DH-016: полный текст вынесен в `Services/device_hub/docs/adr/ADR-DH-016.md` (образец ADR-DH-009..012), в
  `DECISIONS.md` — суть и ссылка (иначе файл 38 КБ при бюджете 32 КБ).
- Ветку `_link_lost` «транспорт ещё подключён» тест достигает сырым `OSError` из `kick_heartbeat` (подмена класса).
- Мой старый авторский тест R2-S1a `test_link_lost_by_tick_keeps_stop_attempt_and_says_unconfirmed` переименован в
  `test_link_lost_by_tick_stop_is_on_the_wire`: ожидание теперь `[SOFT]`, новый TCP, без «не подтверждён».

## What I left open / unreliable

- `Services/device_hub/tests` и `Services/robot_comm/tests` целиком на финальном SHA не прогнаны: NO WINDOW.
- Ни одна инъекция не прогнана мной; прогнозы выше — по чтению тестов.
- `stop_unconfirmed`, уже стоящий после упавшего СТОПа оператора, гасит в `echo_check_plan` (`state.py:538`) новое
  сообщение «не подтверждён» при остановке процесса с упавшей записью — флаг держится дольше, чем
  раньше. Не проверено.
- `request_stop` после намеренного `disconnect` при оставшемся `_jog` с невыставленным `stop_sent` — пишет попытку
  (клиент SDK обнулён, кадра нет), сообщения нет из-за флага. Тестом не закрыто.
- `DECISIONS.md` 33,3 КБ (было 31,3 КБ) — выше бюджета 32 КБ; `robot_comm/README.md` 50 КБ (было выше бюджета).
- Коды 10053/10054 и «порт закрыт -> таймаут 1 с» — поведение Windows на localhost; настоящий робот не проверен.
- `pause_all`, поток приёма команд (2,0 с при нажатии во время connect тика) — принятые исключения до R2-S1e/R2-S1f.
