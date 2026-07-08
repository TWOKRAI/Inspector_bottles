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

## Потокобезопасность (snapshot-API)

Реестр (`_entries`) и драйверы (`_drivers`) мутируются командным потоком и
читаются supervisor-/tick-воркерами. Читать их ИЗВНЕ менеджера — ТОЛЬКО через
публичный snapshot-API под `_registry_lock`:

| Метод | Отдаёт |
|-------|--------|
| `snapshot_registry()` | shallow-копия `list[DeviceEntry]` под локом |
| `get_driver(id)` | живой драйвер или `None` под локом |
| `connected_ids()` | id подключённых (по `is_connected`) |
| `device_count()` / `connected_count()` | счётчики под локом |

IO (connect/disconnect/tick) — ВНЕ лока (короткие критические секции).
Прямой обход приваток из плагина запрещён (гейт `test_no_private_access.py`).
Детали — ADR-DH-008.

## Зависимости

- `multiprocess_framework.modules.base_manager` (BaseManager + ObservableMixin)
- `Services.modbus` (RegisterTransport, ModbusDevice, protocol_file)
- `Services.robot_comm` (RobotClient, FakeRobotTransport — для RobotDriver)
- `Services.vfd_comm` (VfdClient, VfdConfig — для VfdDriver)
- `Services.hikvision_camera` (lazy import — для HikvisionDriver)

НЕ зависит от: `Plugins/*`, `multiprocess_prototype/*`.
