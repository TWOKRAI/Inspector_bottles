# Services/device_hub

Центральный реестр устройств и менеджер соединений.

## Назначение

Единое место владения всеми соединениями с устройствами (роботы, ПЧ, камеры,
произвольные Modbus). CRUD реестра, lifecycle (connect/disconnect), dispatch
команд через драйверы.

## Структура

```
__init__.py            — публичный API
errors.py              — иерархия ошибок
registry/
  entry.py             — DeviceEntry (dataclass, to_dict/from_dict)
  store.py             — RegistryStore (atomic YAML)
transports.py          — build_transport (tcp/rtu/bridge)
manager.py             — DeviceManager (BaseManager + ObservableMixin)
drivers/
  base.py              — BaseDeviceDriver (quality codes, stats)
  robot_driver.py      — RobotDriver (feeder CVT + draw)
  vfd_driver.py        — VfdDriver (poll + DRAW-gating)
  hikvision_driver.py  — HikvisionDriver (control-only)
  generic_modbus_driver.py — GenericModbusDriver (универсальный)
tests/
```

## Зависимости

- `multiprocess_framework.modules.base_manager` (BaseManager + ObservableMixin)
- `Services.modbus` (RegisterTransport, ModbusDevice, protocol_file)
- `Services.robot_comm` (RobotClient, FakeRobotTransport — для RobotDriver)
- `Services.vfd_comm` (VfdClient, VfdConfig — для VfdDriver)
- `Services.hikvision_camera` (lazy import — для HikvisionDriver)

НЕ зависит от: `Plugins/*`, `multiprocess_prototype/*`.
