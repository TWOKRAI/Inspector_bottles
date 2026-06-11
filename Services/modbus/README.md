# modbus — драйвер Modbus-TCP / RS485

Универсальный, переиспользуемый драйвер промышленного протокола Modbus для связи
с PLC и контроллерами. Даёт **программный API** (standalone) и **встраивается в
GUI/pipeline** как плагин и сервис.

## Возможности

- **TCP и RS485 (RTU)** одной библиотекой (pymodbus 3.x), выбор через `transport`.
- **Чтение** (вход): опрос holding/input/coils/discrete-регистров.
- **Запись** (выход): команды в PLC — например выбраковка бракованной бутылки.
- **Команды из GUI**: connect / disconnect / read / write / get_status.
- **Полноценная телеметрия**: состояние соединения, ошибки, счётчики
  reads/writes/errors, uptime — через API (`get_status`), callbacks и register-поля.
- **Graceful degradation**: пакет импортируется без pymodbus (`MODBUS_AVAILABLE`),
  тесты идут без библиотеки и без железа.
- **Атомарные транзакции** (`ModbusDevice.transaction`) — серия записей под одним
  Lock для mailbox-протоколов (данные → маркер-флаг последним).
- **`RegisterTransport`** (Protocol) — минимальный контракт «устройство как
  пространство регистров» для сервисов устройств.
- **`RegisterMap`** — декларативная карта регистров устройства (scale/signed/DW),
  фундамент для тонких сервисов устройств (`robot_comm`, `vfd_comm`, ...).

## Архитектура (3 слоя)

```
sdk/    — тонкая обёртка над pymodbus + datatypes (int16/32/float) + errors
core/   — ModbusConfig, ModbusDevice (state machine + телеметрия), ModbusPoller
plugin/ — ModbusPlugin (io) + ModbusRegisters (config/телеметрия для GUI)
server/ — тестовый Modbus-slave (приёмник) для симуляции PLC
service.py — ModbusService (IService) для вкладки «Сервисы»
```

Слой импортов: `Services → multiprocess_framework`. Пакет НЕ импортирует
`multiprocess_prototype.*` / `Plugins.*`.

## Быстрый старт (standalone API)

```python
from Services.modbus import ModbusConfig, ModbusDevice, TransportType

dev = ModbusDevice(ModbusConfig(host="192.168.1.10", port=502, unit_id=1))
dev.connect()
print(dev.read_holding(0, 10))     # [int, ...]
dev.write_register(0, 42)
print(dev.get_status())            # {'state': 'connected', 'reads_ok': 1, ...}
dev.disconnect()

# RS485 (RTU)
dev = ModbusDevice(ModbusConfig(transport=TransportType.RTU, serial_port="COM3", baudrate=9600))
```

## Как добавить сервис нового устройства (паттерн)

`Services/modbus` — универсальный транспорт; конкретное устройство (робот, ПЧ,
сканер, датчик) оформляется **тонким сервисом устройства**, который выбирает тип
соединения и задаёт свою карту регистров. Эталоны: `Services/robot_comm`
(прямое TCP-соединение), `Services/vfd_comm` (мост через другое устройство).

Шаблон (`Services/<device>_comm/`):

1. **`core/config.py`** — dataclass конфига устройства. Транспортные параметры —
   это `ModbusConfig` (или внешний транспорт для моста), доменные — лимиты/шкалы.
2. **`core/registers.py`** — карта регистров через `RegisterMap` (один источник
   истины протокола устройства):

   ```python
   from Services.modbus import Field, Reg, RegBlock, RegDW, RegisterMap

   MAP = RegisterMap(
       {
           "job_flag": Reg(0x1100),                       # маркер mailbox
           "x_mm":     Reg(0x1101, scale=10, signed=True),
           "encoder":  RegDW(0x1112, signed=True),        # 32 бита
           "telemetry": RegBlock(0x1130, fields=(
               Field("x_mm", scale=10, signed=True),
               Field("moving"),
           )),
       },
       word_order="little",
   )
   ```

3. **`core/client.py`** — клиент устройства поверх `RegisterTransport`
   (`ModbusDevice` для прямого соединения или клиент-мост). Команды mailbox —
   через `device.transaction(MAP.write_ops({...данные..., "флаг": 1}))`:
   маркер-флаг всегда последним ключом, abort на первой ошибке гарантирует,
   что флаг не ляжет поверх частичных данных.
4. **`service.py`** — `@register_service("<device>_comm")` для каталога сервисов.
   Если соединением владеет плагин — сервис только карточка/статус, БЕЗ
   собственного подключения (иначе два master'а к одному устройству).
5. **`testing/fake_transport.py`** — in-process стаб `RegisterTransport` с
   mailbox-семантикой устройства (FLAG-цикл, echo) — тесты без сети.
6. **`tests/`** — карта/кодеки (без сети) + клиент против фейк-транспорта.

Реконнект — ответственность владельца соединения (плагина), НЕ sdk: тихий
reconnect+retry внутри `transaction` разорвал бы атомарность серии.

## CLI-smoke

```bash
python -m Services.modbus --tcp 127.0.0.1:5020 read 0 10
python -m Services.modbus --tcp 127.0.0.1:5020 write 0 42
python -m Services.modbus --rtu COM3:9600 read 0 5
```

## Тестовый Modbus-slave (приёмник)

Сам драйвер — **master** (пишет/читает). Чтобы увидеть, что реально приходит по
шине (например от `modbus_sink` в demo-пайплайне), есть встречный **slave**-сервер.
Поднимается в отдельном терминале и печатает каждую входящую запись регистров:

```bash
python -m Services.modbus.server --tcp 127.0.0.1:5020
# [16:21:07] recv holding[100..102] = [640, 480, 1234]
```

Логирование — через `trace_pdu` сервера; хранилище на нативном SimData/SimDevice
(pymodbus 3.13). Только для теста/симуляции, не для прода.

## Использование в pipeline (плагин)

```yaml
processes:
  - process_name: plc
    plugins:
      - plugin_class: Services.modbus.plugin.plugin.ModbusPlugin
        plugin_name: modbus
        transport: tcp
        host: 192.168.1.10
        port: 502
        unit_id: 1
        poll_interval_ms: 200
        poll_kind: holding
        poll_address: 0
        poll_count: 10
        write_enabled: true     # писать поле результата в PLC
        write_address: 100
        write_field: verdict
```

Плагин авто-дискаверится: `plugin_paths` в `system.yaml` включает `Services`.
Поля конфигурации авто-генерируются в инспекторе ноды из `ModbusRegisters`.

## Установка

```bash
pip install '.[modbus]'   # тянет pymodbus + pyserial (RTU)
```

## Тесты

```bash
python -m pytest Services/modbus/tests -q   # без pymodbus/железа (fake-клиент)
```

## Зависимости

| Пакет | Обязательный | Зачем |
|-------|--------------|-------|
| Python 3.12+ | да | type hints |
| pymodbus ≥ 3.7 | опционально | реальное подключение TCP/RTU |
| pyserial | опционально | RS485 (тянет pymodbus) |
| multiprocess_framework | опционально | для плагина/сервиса |

См. также [STATUS.md](STATUS.md).
