# vfd_comm — сервис ПЧ INVT GD20 (транспорт-агностик)

Тонкий сервис устройства поверх [`Services/modbus`](../modbus/README.md):
клиент зависит только от `RegisterTransport` и не знает, как доставляются
регистры.

## Топология (текущий путь — мост через робота)

```
VfdClient ──(RegisterTransport)──> RobotClient ──TCP──> Робот (Lua) ──RS-485──> GD20
              mailbox 0x1200/0x1210            ретрансляция + зеркало статуса
```

vfd_comm **не импортирует** robot_comm — связку делает плагин `vfd_control`:

```python
from Services.robot_comm import runtime
from Services.vfd_comm import VfdClient

vfd = VfdClient(transport=runtime.get_client())   # мост = клиент робота
vfd.run(50.0)            # частота+направление+RUN+FLAG одной транзакцией
st = vfd.poll()          # пульс VFD_FLAG + чтение зеркала
vfd.ensure_alive()       # heartbeat моста не растёт -> VfdBridgeStaleError
vfd.stop()
```

## КРИТИЧНО: зеркало обновляется только по команде

В текущем Lua (`cvt_universal_full.lua`) статус ПЧ зеркалится **только при
обработке VFD_FLAG**. Прямое `read_status()` без команд читает замороженный
снимок, heartbeat не растёт даже при живом мосте. Поэтому:

- периодический опрос — **`poll()`** (пульс флага; Lua кэширует last_cmd/
  last_freq — лишних записей на RS-485 не будет, только чтение статуса);
- живость моста — **`ensure_alive()`** по динамике heartbeat между poll'ами;
- Lua-улучшение «публикация статуса в idle» — кандидат №1 в плане
  `plans/robot-vfd-services.md`.

Ограничение безопасности: Lua обслуживает VFD_FLAG только в CVT-ветке между
заданиями — в DRAW-режиме и во время job команды ПЧ (включая Stop) не
исполняются. GUI обязан дизейблить VFD-кнопки в DRAW (до Lua-фикса №2).

## Будущее прямое RTU-подключение

Закладка готова: `DIRECT_MAP` в `core/registers.py` — регистры самого GD20
(0x2000 cmd / 0x2100 status / 0x3000 monitor, из мануала goodrive20). Смена
пути = `VfdClient(ModbusDevice(ModbusConfig(transport="rtu", ...)),
register_map=DIRECT_MAP)` + клиентский код команд GD20 (1=FWD/2=REV/5=STOP).
Полей heartbeat/comm_errors там нет — они существуют только в мосте
(`VFDStatus` допускает None).

## Масштабирование

Новый регистр ПЧ = строка в `core/registers.py` (+ точечная ретрансляция в
Lua, если через мост). Новое устройство = копия паттерна (см. README modbus).

## Тесты

```bash
pytest Services/vfd_comm    # 15: юнит (стаб) + интеграция моста (фейк-робот)
```
