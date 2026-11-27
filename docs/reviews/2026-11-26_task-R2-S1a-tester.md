# R2-S1a — отчёт слепого тестера

Дерево `772d351dc` (до реализации). Реализацию, симуляцию и чужие отчёты я не читал. Коммита нет.

## Файлы

| Файл | Тестов | Приёмка |
|---|---|---|
| `Services/modbus/tests/test_r2s1a_transport_acceptance.py` | 54 | A1–A10 |
| `Services/device_hub/tests/test_r2s1a_link_drop_acceptance.py` | 40 | A11–A15 |

Второй файл импортирует `LoopbackServer`, `Call`, `Frame`, `run` из первого. Настоящий клиент везде, дублёр только в A5.

## Прогон на `main`

Команда (через `machine_gate.sh light inspector-bottles-8d`, из корня worktree, `PYTHONPATH=$PWD`):
`python -m pytest <файл> [-k <группа>] -v -p no:cacheprovider --tb=line`. Класс `medium` дал `NO WINDOW`, поэтому файл device_hub шёл тремя группами `-k`.

| Группа | Итог |
|---|---|
| файл modbus | 50 failed, 4 passed |
| `a11_command or a11_program or a11_jog or op_list` | 14 failed, 5 passed |
| `a11_queued or a11_park or a12` | 8 failed, 1 passed |
| `a13 or a14 or a15` | 4 failed, 8 passed |
| всего | 76 красных, 18 зелёных из 94 |

После прогона `ruff format` переписал оформление файла device_hub; затем `ruff check` чист, 94 теста собираются, прогон не повторялся.

## Таблица

| Тест (`test_…`) | Приёмка | `main` | Первая строка ошибки |
|---|---|---|---|
| `a01_dropped_read_raises_modbus_io_error` (8) | A1 | красные 8 | `ConnectionException: … Connection unexpectedly closed` (fin); `ConnectionResetError 10054` (rst) |
| `a02_dropped_read_marks_device_error` (8) | A2 | красные 8 | то же |
| `a03_dropped_write_marks_device_error` (6), `a03_…transaction_stops_the_series` (2) | A3 | красные 8 | то же |
| `a04_idle_drop_before_request_…` (2) | A4 | красные 2 | `ConnectionAbortedError 10053` (fin); `ConnectionResetError 10054` (rst) |
| `a05_slave_branch_errors_…` (4) | A5 | красные 4 | сырой `OSError` / `ModbusException` из ветки `slave=` |
| `a06_connect_after_error_opens_new_tcp` | A6 | fin зелёный; rst, idle красные | `ConnectionResetError 10054` / `ConnectionAbortedError 10053` |
| `a07_silent_server_timeout_…` | A7 | красный | `ModbusIOException: No response received after 0 retries` |
| `a08_normal_read_and_write_unchanged`, `a08_error_reply_…` (2) | A8 | зелёные 3 | — |
| `a09_session_grows_…`, `a09_stale_session_write_…` (8) | A9 | красные 9 | `AttributeError: 'ModbusDevice' object has no attribute 'session'` |
| `a10_waiting_writer_with_old_session_…` (8) | A10 | красные 8 | `AssertionError: у ModbusDevice нет session` |
| `a11_op_list_matches_op_specs` | A11 | зелёный | — |
| `a11_command_admitted_before_drop_…` (servo on, jog_step, jog_hold × 3 режима) | A11 | fin, fin-reconnected красные 6; rst зелёные 3 | `[(4097, (…, 65, 1, 1)), (4096, (1,))] == []` |
| `a11_program_admitted_before_drop_…` (draw_polyline, program_run × 3) | A11 | красные 6 | fin: `[(5120, …), (4097, (…, 48, …))…] == []`; rst: `не дождались за 40.0 с: программа после переподключения` |
| `a11_jog_lease_stops_writing_after_drop` (3) | A11 | fin, fin-reconnected красные; rst зелёный | `[(4130, (3,)), (4130, (4,))] == []` |
| `a11_queued_job_admitted_before_drop_…` (enqueue_job, return_job × fin, rst) | A11 | красные 4 | `[(4097, (…, 32, 10, 0)), …] == []`; return: SC_BUF + SC_RUN |
| `a11_park_admitted_before_drop_…` (2) | A11 | fin красный; rst зелёный | `[(4097, (…, 65, 1, 0)), (4096, (1,))] == []` |
| `a12_running_program_next_chunk_…` (3) | A12 | красные 3 | fin: записи SC_BUF после обрыва; rst: `jog_step` после переподключения отвечает `[WinError 10054]` |
| `a13_stop_after_drop_writes_exactly_one_stop_req` (4) | A13 | rst красные 2; fin зелёные 2 | `assert 0 == 1` |
| `a13_stop_op_without_echo_…` (2), `a13_request_stop_without_echo_…` (2) | A13 | зелёные 4 | — |
| `a14_vfd_stop_over_robot_bridge_…` (2) | A14 | fin зелёный; rst красный | `{'status': 'error', 'message': '[WinError 10054] …'}, 0 кадров` |
| `a15_v1_abort_arrives_and_link_recovers_…` (2) | A15 | fin зелёный; rst красный | то же |

## Расхождения с прогнозом REDS

1. A11: пять случаев `rst` зелёные на `main` (3 команды, поводок, park). Причина: pymodbus держит мёртвый сокет, кадр не уходит. Эти случаи сторожат инъекцию «не проверять `expected_session`».
2. A13: мои 4 теста про эхо зелёные на `main`. Прогноз «A13 (RST) красный» верен для теста на один кадр `STOP_REQ`.
3. A14 `rst` и A15 `rst` красные на `main`. В прогнозе названы только сторожа `fin`.
4. Остальное совпало.

## Операции A11

- Движение: `jog_hold`, `jog_step`, `servo` (on), `enqueue_job`, `return_job`, `program_run`, `draw_polyline`, `park`.
- Не движение: `stop`, `abort`, `program_abort`, `jog_release` (останавливают, должны проходить всегда); `get_telemetry`, `exchange_log_get`, `exchange_log_set`, `point_capture` (не пишут роботу); `do_set` (выход, не ход); `param_set`, `param_apply`, `calib_belt` (параметры).

## Режим `fin-reconnected`

Связь поднята заново раньше, чем операция продолжила: `on_error` настоящего `ModbusDevice`, отданного через `transport=`, зовёт `connect()`. Без этого режима программы и A12 защищает один флаг `is_connected`, и инъекция «не проверять `expected_session`» остаётся незамеченной.

## Проверка тел тестов

Одноразовая заплатка Д1–Д4, Д6 (monkeypatch из scratchpad, вне репозитория, не доказательство дизайна):

- Файл modbus: 54 passed.
- Файл device_hub: каждый тест хотя бы раз зелёный с заплаткой; одним финальным прогоном все 40 не гонялись.
- Инъекция «`session` не проверяется»: 15 красных из 21 (команды, поводок, программы и A12 в `fin-reconnected`).
- Инъекция «вернуть проверку флага связи в стоп»: 6 красных (4 кадра `STOP_REQ`, 2 `request_stop` без эха).
- Остальные инъекции из задачи не проверялись.

## Находки и вопросы лиду

1. **Решить до реализации: задания в очереди.** Я считаю допуском вызов `enqueue_job` / `return_job` (там проверяется связь). Принятое до обрыва задание после переподключения не должно уйти. DESIGN об очереди молчит. Если допуск — это раздача тиком, 4 теста `a11_queued_job_…` неверны.
2. **Метка «в полёте» после отказа.** Вход: с заплаткой `jog_step` отклонён по сеансу, затем переподключение и новый `jog_step`. Выход: `{'status': 'error', 'message': 'Робот не ответил вовремя (этап response)'}`; то же для `jog_hold`. Причина по чтению: `client_v2.cmd()` ставит `_inflight` до `_wr` (`Services/robot_comm/core/client_v2.py:511-518`). Отказ значит «на провод ничего не ушло», а метка остаётся. Тест это не требует для A11 (парная проверка перенесена до обрыва); A12 задевает это, только если отклонён `SC_RUN`. Автору стоит снимать метку при отказе, либо лиду добавить строку приёмки.

## Не покрыто и оставлено открытым

- A16 не мой.
- A13: стоп только простаивающего робота. Не покрыты стоп при идущей программе, задании, jog.
- A13: обрыв замечен чтением до стопа. Случай «стоп — первая операция на мёртвой связи» и «разрыв простоя» не тестируются. Предположение без замера: `disconnect()` пишет стоп один раз и может дать 0 кадров.
- A11: `do_set`, `param_set`, `param_apply`, `calib_belt` не проверяются (классифицированы как не движение). В описании дефекта назван `PARAM_APPLY` — лиду решить. `start_toolchange` нет в `OP_SPECS`.
- A11: перехват опирается на то, что первый обмен операции ждёт замок устройства. Значение сеанса, взятое после этого ожидания, тест считает ошибкой.
- Поведение pymodbus 3.13.0 на Windows (замер): FIN во время запроса — исключение, следующий вызов открывает новый TCP; FIN или RST в простое — мёртвый сокет.
- Тесты A11, A12 идут по реальному времени (паузы 0,5–3 с); под нагрузкой машины не проверялись. Полный файл device_hub идёт дольше 2 минут: класс `medium`.
- Linux не проверялся: коды ошибок сокета там другие, ожидания от них не зависят.

## Память

`memory hits: python …/scripts/memory/search.py modbus transport disconnect blind acceptance test -> docs/claude/memory/feedback_blind_acceptance_can_pin_a_nonexistent_mechanism.md, feedback_blind_red_prove_bodies_with_scratch_reference.md`
