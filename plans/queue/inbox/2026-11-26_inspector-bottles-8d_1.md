# Находка: обрыв Modbus посреди запроса остаётся незамеченным (общий слой)

Сессия inspector-bottles-8d (бывшая d1, полоса Р2), 2026-11-26. Не чинено, ждёт слова владельца.

- `Services/modbus/sdk/client.py` `_call` не переводит `ModbusException` / `OSError` в `ModbusIOError`; `ModbusDevice` (`core/device.py:203,216`) ловит только свой тип и остаётся «подключён», pymodbus сам открывает новый TCP.
- Прогон ревьюера и CTO на настоящем pymodbus поверх sim v2: после обрыва посреди запроса перезагруженному роботу уходят `PARAM_APPLY, CVT_JOB, CVT_JOB`, защёлки нет, `last_error` пуст.
- Решение CTO: отдельная задача R2-S1a (`Services/modbus/sdk/client.py` и тесты на настоящем клиенте по TCP), слить ПЕРЕД R2-S1; R2-S1 до этого не сливать.
- Затрагивает ПЧ (тема полосы Ф), робота v1, `generic_modbus_driver`, плагины `modbus` и `modbus_sink`: они начнут видеть обрыв и переподключаться.
