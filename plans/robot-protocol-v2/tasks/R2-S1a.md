# R2-S1a — обрыв Modbus посреди запроса виден вызывающему

Полоса Р2. Ветка `fix/modbus-link-drop` от `main` `53efe24b9`. Сливается ПЕРЕД R2-S1 (вердикт CTO 2026-11-26, разрешение владельца 2026-11-26 на правку `Services/modbus`).

## Дефект

`ModbusSdkClient._call` (`Services/modbus/sdk/client.py:268-297`) переводит в `ModbusIOError` только ответ с `isError()`. Исключение самого вызова (`ModbusException` pymodbus или `OSError` сокета) проходит сырым. `ModbusDevice._read/_write` (`core/device.py:195-228`) ловят только `ModbusDriverError`, поэтому `_fail` не вызывается и устройство остаётся `CONNECTED`. pymodbus на следующем запросе сам открывает новый TCP. Прогон ревьюера и CTO: после обрыва посреди `get_telemetry` роботу ушли `PARAM_APPLY, CVT_JOB, CVT_JOB`, `drv.is_connected` оставался `True`.

## DESIGN

- Д1. В `_call` любое `ModbusException` или `OSError`, брошенное вызовом метода pymodbus в ЛЮБОЙ из двух веток (`device_id=` и запасной `slave=`), переводится в `ModbusIOError` с именем метода и текстом причины, `from exc`. Одна строка WARNING с unit и адресом, как у ветки `isError()`.
- Д2. `ModbusDevice` не меняется: его `_read/_write` уже на `ModbusDriverError` считают ошибку, переводят устройство в `ERROR`, зовут `on_error` и пробрасывают исключение.
- Д3. Клиент pymodbus здесь НЕ закрывается: потребители, которые продолжают слать запросы без `connect()`, не должны замолчать навсегда. Состояние устройства после ошибки возвращает только `connect()`; удачный запрос сам его не возвращает.
- Д4. Прочие исключения (`TypeError` запасной ветки, ошибки программиста) проходят как раньше.

## FILES

1. `Services/modbus/sdk/client.py` — `_call`.
2. `Services/modbus/tests/test_transport_errors.py` — новый.
3. `Services/modbus/README.md`, `STATUS.md`, `DECISIONS.md` (если файл есть) — одна запись о контракте ошибок.

## ACCEPTANCE

Проверки A1–A7 идут на настоящих `ModbusSdkClient` и pymodbus поверх своего TCP-сервера на `127.0.0.1` (порт от ОС), без подмены клиента, кроме A5. Каждый вызов, способный повиснуть, — в потоке-демоне со сроком.

- A1. Сервер принимает запрос чтения и закрывает соединение без ответа → вызывающий получает `ModbusIOError`; для всех четырёх чтений.
- A2. То же через `ModbusDevice`: после исключения `is_connected` равно `False`, `on_error` вызван один раз, `reads_err` равен 1.
- A3. То же для записи (`write_register`, `write_registers`, `write_coil`) через `ModbusDevice`: `ModbusIOError`, `is_connected` `False`, `writes_err` равен 1.
- A4. Простаивающее соединение разорвано сервером ДО следующего запроса → `ModbusIOError` либо удачный ответ на новом соединении; сырое исключение другого типа не выходит. Если запрос удался на новом соединении, это записывается в отчёт как измеренный остаток (его закрывает `TLM_BOOT_ID`, отдельная задача).
- A5. Метод клиента, не принимающий `device_id` и бросающий `OSError` (и отдельно `ModbusException`) в ветке `slave=` → `ModbusIOError`.
- A6. После ошибки `connect()` возвращает `True`, `is_connected` `True`, чтение отдаёт значения.
- A7. После ошибки удачный запрос без `connect()` не делает `is_connected` равным `True`.
- A8. Ответ с `isError()` и обычное чтение ведут себя как раньше (существующие тесты не меняются).
- A9. Наборы потребителей зелёные: `Services/modbus`, `Services/vfd_comm`, `Plugins/sinks/modbus_sink`, `Services/robot_comm`, `Services/device_hub` (heavy, своё окно). Красный набор называется поимённо.

## REDS (прогноз до реализации)

A1, A2, A3, A5 красные. A4, A6, A7 — зелёные или красные, прогон покажет; A8 зелёный.

Инъекция: убрать новый `except` → A1, A2, A3, A5 красные, A6, A8 зелёные.

## Последствия для потребителей (проверить, не чинить без нужды)

ПЧ (`Services/vfd_comm`, тема полосы Ф), робот v1 (`Services/robot_comm/core/client.py`), `generic_modbus_driver`, плагины `Services/modbus/plugin` и `Plugins/sinks/modbus_sink`, `Services/modbus/channels`, `service.py`: увидят обрыв там, где раньше pymodbus молча чинил связь. Драйверы `device_hub` пойдут в цикл переподключения и могут «сдаться» после 3 попыток (`drivers/base.py:275-302`).

## Кто восстанавливается сам после обрыва (по чтению 2026-11-26, не прогонялось)

| Потребитель | После правки |
|---|---|
| робот v1 и v2 | сам: попытка раз в 2 с, объект транспорта тот же; после 3 неудач ждёт «Подключить», кроме `max_reconnect_attempts: 0` (рецепты букв) |
| ПЧ через мост робота (все рецепты с ПЧ) | сам, вслед за носителем: `is_connected` идёт от транспорта робота |
| `modbus_sink` | сам, на следующих данных |
| `GenericModbusDriver` | **не восстанавливается**: `tick` без связи только отдаёт `bad`, `connect()` не зовёт. Сегодня связь молча чинит pymodbus |
| `Services/modbus/plugin` и `ModbusChannel` | **не восстанавливаются**: `connect()` только по команде |

Предложение (на разбор ревьюеру): Д5 — `GenericModbusDriver.tick` переподключается как `VfdDriver` (`_reconnect_due`, `reset_reconnect`, `_note_reconnect_failed`, только при `desired_connected`). Д6 — `Services/modbus/plugin` переподключается с порогом только из состояния `ERROR` (после «Отключить» состояние `DISCONNECTED`, подключения нет).

Находки вне задачи, по чтению: прямой ПЧ (`tcp`/`rtu`) не подключается и сегодня — `VfdDriver.connect()` не открывает транспорт (рецептов с прямым ПЧ нет); у мостового ПЧ счётчик попыток не обнуляется, если связь вернулась вместе с носителем.

`DeviceHubPlugin.readiness` считает любое «нет связи» отказом без задержки (ADR-PH-004), поэтому ставший видимым короткий обрыв увёл бы линию в отказ.

- Д7 (решение владельца 2026-11-26: «Прощать на несколько секунд»). Плагину `device_hub` в `hikvision_letter_robot.yaml` и `letter_robot_sim.yaml` задаётся `readiness: {hold_s: 5.0}` (ADR-PM-061; потолок 10 с; на boot не действует). Значение 5 с выбрал лид, владелец может поменять. Код плагина и фреймворка не меняется. Рецепты и golden `hikvision_letter_robot.build.json` общие с полосой Ф: написать ей до первой правки.
- Порядок с полосой Ф (договорено 2026-11-26): у них неслиты `presence_watch` (`feat/run-state-2-2d` `5999d5eb9`) и `inbox_stall_s` (`feat/run-state-2-2e` `e4ed7376c`) в тех же рецептах и golden. Д7 делается после их слияния в `main` (пришлют sha). Если R2-S1a готова раньше — правим только строки `device_hub` (не пересекаются), golden пересобирается после rebase, не руками.
- A10. Пин на оба рецепта: у `device_hub` разобранная политика равна `hold_s=5.0` без переназначения степеней (`parse_policy`), прогноз до правки — красный.

## Не входит

`Services/device_hub` (кроме прогона тестов). Тест на настоящих объектах драйвера робота (три точки обрыва: `get_telemetry`, `poll_errors` в тике, `wait_done` задания; ветка `except Exception → _link_lost()` в `robot_driver_v2/jobs.py`) и переписывание проверки A4 задачи R2-S1 делаются в ветке R2-S1 после переноса на эту. `TLM_BOOT_ID`. RTU на железе.
