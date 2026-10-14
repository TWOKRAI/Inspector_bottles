---
name: feedback-modbus-device-raw-oserror-keeps-connected
description: "ModbusDevice не помечает обрыв на сыром OSError сокета (WinError 10053 после рестарта контроллера) — is_connected остаётся True, драйвер, переподключающийся по is_connected, пишет в мёртвый сокет вечно / ModbusDevice stays connected on raw socket OSError, driver never reconnects"
module: [services/device_hub, services/modbus]
mechanism: [error-handling, lifecycle]
metadata:
  node_type: memory
  type: feedback
  modified: 2026-10-14
---
**Ловушка.** `ModbusDevice` (`Services/modbus/core/device.py`: `_read`, `_write`, `transaction`) переводит связь в ERROR (`_fail`, `is_connected=False`) только на `ModbusDriverError`. После рестарта контроллера (sim `E2eRig.restart`) сокет отдаёт сырой `ConnectionAbortedError` (WinError 10053) — он проходит мимо `_fail`, `is_connected` остаётся True навсегда.

**Замер.** T5.1 (RobotDriverV2), приёмка 6 «рестарт sim с другой меткой → параметры повторно»: красная 2 из 2, в логе каждый тик «пульс HB_PC не записан: [WinError 10053]»; после правки драйвера — зелёная, приёмка 10/10 три прогона подряд (fd5c003e8).

**Как применять.** Ошибка ввода-вывода в тике драйвера = связь потеряна: сбросить свою готовность и закрыть сокет (`transport.disconnect()`); перед повторным `connect()` переоткрывать сокет, даже если транспорт говорит «подключён». Тот же застревающий сокет возможен у v1-драйвера робота и у других потребителей `ModbusDevice` — исправление в самом `Services/modbus` (fix forward) открыто, см. `docs/claude/OPEN_QUESTIONS.md` → «Task T5.1».

**Триггер.** Драйвер или клиент Modbus TCP, который решает о переподключении по `is_connected`; тест с рестартом сервера.
