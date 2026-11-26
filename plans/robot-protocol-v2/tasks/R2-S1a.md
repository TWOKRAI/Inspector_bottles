# R2-S1a — обрыв Modbus виден вызывающему и ничего не пишется до нового подключения

Полоса Р2. Ветка `fix/modbus-link-drop` от `main` `53efe24b9`. Сливается ПЕРЕД R2-S1; если до дня с роботом успевает только одна из двух — R2-S1a (вердикты CTO 2026-11-26). Разрешение владельца 2026-11-26 на правку `Services/modbus`.

**Assignee:** developer (Sonnet). **Level:** Senior (дизайн задан ниже). **Gate:** приёмка слепого тестера, инъекции, живой прогон на loopback, ревью стадии 5. **Handoff:** отчёт `docs/reports/2026-11-26_robot-protocol-v2_R2-S1a.md`. Редакция 2: после проверки стадии 0 (CHANGES REQUESTED) и вердикта CTO.

## Дефект

`ModbusSdkClient._call` (`Services/modbus/sdk/client.py:268-297`) переводит в `ModbusIOError` только ответ с `isError()`. Исключение самого вызова (`ModbusException` pymodbus или `OSError` сокета) проходит сырым, `ModbusDevice` не вызывает `_fail` и остаётся `CONNECTED`. Прогоны ревьюера и CTO (pymodbus 3.13.0, loopback):

- после FIN pymodbus сам открывает новый TCP, и записи уходят по нему (после обрыва роботу ушли `PARAM_APPLY, CVT_JOB, CVT_JOB`);
- после RST или разрыва простоя pymodbus держит мёртвый сокет, а `connect()` отвечает True без нового TCP (3 чтения подряд `ConnectionResetError`, accepts=1);
- поток, ждавший замок устройства в момент обрыва, отправляет `servo on` по новому соединению при `is_connected=False`.

## DESIGN

- Д1. В `_call` любое `ModbusException` или `OSError`, брошенное вызовом метода pymodbus в ЛЮБОЙ из двух веток (`device_id=` и запасной `slave=`), переводится в `ModbusIOError` с именем метода и причиной, `from exc`, одна строка WARNING с unit и адресом.
- Д2. В той же новой ветке закрывается сокет pymodbus (`self._client.close()` внутри обёртки; обёртка не обнуляется, `ModbusSdkClient.close()` не вызывается). Сбой самого закрытия не подменяет исходную причину. Ветка `isError()` сокет не закрывает.
- Д3. Прочие исключения (`TypeError` запасной ветки, `ValueError`, `struct.error`) проходят как раньше: это ошибки вызывающего, а не связи.
- Д4. Защёлка записи в `ModbusDevice`: ставится в `_fail`, снимается только удачным `connect()`. `disconnect()` её не снимает (робот v2 после ошибки сам зовёт `disconnect()`, и проверка по состоянию `ERROR` пропустила бы ждавшую запись). Пока защёлка стоит, `write_register`, `write_registers`, `write_coil`, `transaction` под замком устройства бросают `ModbusConnectionError` без единого кадра на провод; счётчики, `_fail` и `on_error` не трогаются. Чтения не закрываются. Устройство без ошибки (в том числе никогда не звавшее `connect()`) ведёт себя как раньше. Правило одно для всех потребителей, флага включения нет.
- Д5. Исключение из защёлки задаётся данными при создании: `ModbusDevice(..., error_writable: frozenset[int] = frozenset())`. Проходит только запись, состоящая ровно из одной записи одного регистра с адресом из набора (`write_register` или `transaction` из одной такой операции). Параметра на самом вызове нет. `build_transport` принимает этот набор и передаёт в `ModbusDevice`. Робот v2 задаёт `{STOP_REQ}` (`0x1021`), `RobotClient` v1 при создании своего устройства — `{REG_STOP}` (`0x1106`). Удачная запись по исключению защёлку не снимает.
- Д6. `GenericModbusDriver.tick`: при `desired_connected and not is_connected` (проверка стоит ДО проверки `protocol`) переподключается тем же порядком, что `VfdDriver` (`_reconnect_due`, `_record_reconnect`, `reset_reconnect`, `_note_reconnect_failed`), порог 2 с. Цена: после 3 неудач нужна кнопка «Подключить».
- Д7. `Services/modbus/plugin`: переподключение из потока опроса только из состояния `ERROR`, с порогом 2 с и одной строкой в лог на серию неудач. Проверка и `connect()` под `self._lock`; после «Отключить» и после `shutdown` подключения нет.

Остаток, не закрывается здесь: чужой `connect()` между проверкой защёлки и записью (нужен номер сеанса связи, семья `TLM_BOOT_ID`). Замерить и записать в отчёт.

## FILES

1. `Services/modbus/sdk/client.py` — `_call` (Д1–Д3).
2. `Services/modbus/core/device.py` — защёлка и `error_writable` (Д4, Д5).
3. `Services/device_hub/transports.py` — параметр набора (Д5).
4. `Services/device_hub/drivers/robot_driver_v2/driver.py` — передать `{STOP_REQ}` (Д5), больше ничего.
5. `Services/robot_comm/core/client.py` — набор `{REG_STOP}` при создании своего `ModbusDevice` (Д5).
6. `Services/device_hub/drivers/generic_modbus_driver.py` — Д6.
7. `Services/modbus/plugin/plugin.py` — Д7.
8. Новые тесты: `Services/modbus/tests/test_transport_errors.py`, `Services/modbus/tests/test_write_latch.py`, `Services/modbus/tests/test_plugin_reconnect.py`, `Services/device_hub/tests/test_r2s1a_link_drop.py`.
9. `Services/modbus/README.md`, `STATUS.md`, `DECISIONS.md` (если есть) — контракт ошибок и защёлки.

## ACCEPTANCE

Настоящие `ModbusSdkClient`, `ModbusDevice` и pymodbus поверх своего TCP-сервера на `127.0.0.1` (порт от ОС), без подмены клиента, кроме A5. Режимы обрыва: FIN (штатное закрытие), RST, разрыв простоя. Каждый вызов, способный повиснуть, — в потоке-демоне со сроком. Ожидаемые значения — литералы.

- A1. Сервер принял запрос чтения и оборвал связь без ответа (FIN и RST) → `ModbusIOError`; для всех четырёх чтений.
- A2. То же через `ModbusDevice`: `is_connected` `False`, `on_error` вызван один раз, `reads_err` 1.
- A3. Записи (`write_register`, `write_registers`, `write_coil`, `transaction`) → `ModbusIOError`, `is_connected` `False`, `writes_err` 1, остаток серии `transaction` на сервер не пришёл.
- A4. Простаивающее соединение разорвано ДО следующего запроса → `ModbusIOError`; после `connect()` успех на новом TCP.
- A5. Метод клиента без `device_id`, бросающий `OSError` (и отдельно `ModbusException`) в ветке `slave=` → `ModbusIOError` (поддельный клиент имеет `close()`).
- A6. После ошибки `connect()` возвращает `True`, чтение отдаёт значения, сервер насчитал 2 соединения — для FIN, RST и разрыва простоя.
- A7. После ошибки запись без `connect()` → `ModbusConnectionError`, на сервер 0 кадров записи; то же после `disconnect()`; удачное чтение не делает `is_connected` `True` и не снимает защёлку; после `connect()` запись проходит.
- A8. Ответ с `isError()` → `ModbusIOError`, как раньше; обычные чтение и запись без ошибок — как раньше. Существующие тесты не меняются.
- A9. Сервер молчит (таймаут) → `ModbusIOError`, `is_connected` `False`.
- A10. С набором `{X}` при защёлке: одна запись регистра `X` доходит (ровно 1 кадр). Отказ и 0 кадров: другой адрес; `transaction` из записи `X` и ещё одной операции; `write_registers` с `X` длиной 2; `write_coil` по `X`. Без набора запись `X` отклонена.
- A11. Два потока: A висит в чтении, B ждёт замок с записью; связь рвётся (FIN и RST) → B получает `ModbusConnectionError`, на новом соединении 0 кадров записи.
- A12. Настоящий `RobotDriverV2` поверх sim v2 по loopback TCP: после обрыва `servo on`, задание, `DO_SET`, `PARAM_APPLY` — отказ и 0 кадров в регистры команд; STOP — ровно одна запись `STOP_REQ`; STOP без эха показан как неподтверждённый. Программа шла в момент обрыва → её следующая запись отклонена, поток кончается, переподключение проходит.
- A13. Робот v1: при защёлке `stop(mode)` доходит одним кадром в `0x1106`.
- A14. `GenericModbusDriver`: FIN, RST, разрыв простоя → `bad`, после порога `good`, 2 соединения. `desired_connected=False` → `connect()` не зовётся. Сервера нет → 3 попытки и стоп.
- A15. Плагин `Services/modbus` после обрыва снова читает; после «Отключить» и после `shutdown` подключения нет; «Отключить» во время попытки кончается `DISCONNECTED`.
- A16. Наборы потребителей зелёные: `Services/modbus` (с плагином), `Services/vfd_comm`, `Plugins/sinks/modbus_sink`, `Services/robot_comm`, `Services/device_hub` (heavy, своё окно). Красный набор называется поимённо.

## REDS (прогноз на `main`)

Красные: A1–A5, A7, A9, A10, A11, A12, A14 (RST, простой, «сервера нет»), A15 (RST). A6: FIN зелёная, RST и простой красные. Зелёные сторожа: A8, A13, часть A14 с `desired_connected=False`.

Инъекции (каждая отдельно): убрать новый `except` → A1–A4, A9 красные; убрать закрытие сокета → A6 (RST) красная; убрать защёлку → A7, A11, A12; снимать защёлку в `disconnect()` → A7 (после `disconnect`); не пропускать набор → A10 (проход), A12 (STOP), A13; пропускать серию с адресом из набора целиком → A10 (смешанная серия); убрать Д6 → A14; убрать Д7 → A15.

## Последствия для потребителей

- Ответ контроллера кодом исключения (`isError()`) и один таймаут после повторов теперь тоже ставят защёлку: запись отклоняется до `connect()`.
- Робот v1 и v2, ПЧ, `modbus_sink`, `generic_modbus_driver`, плагин `Services/modbus` увидят обрыв там, где раньше pymodbus чинил связь молча.
- ПЧ через мост: идёт за носителем; после 3 неудач с лимитом по умолчанию остаётся «сдался» (старый дефект, станет заметнее; в рецептах букв `max_reconnect_attempts: 0`). Таймаут ПЧ через мост роняет связь робота (по чтению, `transports.py`).
- Прямой ПЧ (`tcp`/`rtu`) не подключается и сегодня (`VfdDriver.connect()` не открывает транспорт); рецептов с ним нет. `cmd_connect` плагина `Services/modbus` создаёт новое устройство, канал держит старое. Оба — строкой в отчёт.

## Не входит

Прощение короткого обрыва (отдельная задача R2-S1b ниже). `Services/device_hub` кроме пунктов FILES. Тест на настоящих объектах для защёлки движения R2-S1 и переписывание её проверки A4 — в ветке R2-S1 после переноса на эту. `TLM_BOOT_ID`, номер сеанса связи. RTU на железе.

## R2-S1b (отдельная задача, после слияния правок полосы Ф)

Решение владельца 2026-11-26: короткий обрыв линия прощает несколько секунд. `readiness: {hold_s: 5.0}` (ADR-PM-061, потолок 10 с; число выбрал лид) у плагина `device_hub` в `hikvision_letter_robot.yaml` и `letter_robot_sim.yaml`; пин `parse_policy` на оба рецепта.

- До пина измерить на loopback время от обрыва до `is_connected=True`: если больше 5 с, прощение ничего не даёт.
- Порядок с полосой Ф: у них неслиты `feat/run-state-2-2d` `5999d5eb9` и `feat/run-state-2-2e` `e4ed7376c` в тех же рецептах и golden; golden пересобирается после rebase, не руками.
- Пределы (прогон ревьюера): повторный обрыв через 3 с после возврата даёт отказ сразу; узел с уже блокирующей причиной не прощается; мигание 4,5 с без связи и 5,5 с связи отказа не даёт никогда. `hold_s` берётся из рецепта, с которым стартовал защищённый процесс `devices`; переключение рецепта в приложении его не меняет (по чтению).
