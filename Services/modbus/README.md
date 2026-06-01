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

## Архитектура (3 слоя)

```
sdk/    — тонкая обёртка над pymodbus + datatypes (int16/32/float) + errors
core/   — ModbusConfig, ModbusDevice (state machine + телеметрия), ModbusPoller
plugin/ — ModbusPlugin (io) + ModbusRegisters (config/телеметрия для GUI)
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

## CLI-smoke

```bash
python -m Services.modbus --tcp 127.0.0.1:5020 read 0 10
python -m Services.modbus --tcp 127.0.0.1:5020 write 0 42
python -m Services.modbus --rtu COM3:9600 read 0 5
```

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
