# Services/device_hub — Статус

## Текущее состояние

**Фазы 0-5 DONE** — полный цикл: YAML-протоколы, реестр, DeviceManager,
4 драйвера, always-on процесс `devices`, тонкий robot_io, GUI-вкладки
(Робот/ПЧ/Камеры), миграция с runtime.py, чистка vfd_control/robot_draw.

## Компоненты

| Компонент | Статус | Тесты |
|-----------|--------|-------|
| DeviceEntry | done | test_entry.py |
| RegistryStore | done | test_store.py |
| build_transport | done | test_transports.py |
| DeviceManager | done | test_manager.py |
| RobotDriver | done | test_robot_driver.py |
| VfdDriver | done | test_vfd_driver.py |
| HikvisionDriver | done (lazy SDK) | test_device_hub_plugin (enum/release) |
| GenericModbusDriver | done | test_generic_modbus.py |
| DeviceHubPlugin | done | test_device_hub_plugin.py |
| DeviceHubClient | done | test_client.py |

## ADR

- ADR-DH-001: Один мастер — процесс devices
- ADR-DH-002: Bridge-транспорт шарит Lock носителя
- ADR-DH-003: YAML-протокол → RegisterMap + meta
- ADR-DH-004: Удаление носителя — блокировка, НЕ каскад
- ADR-DH-005: YAML-протокол закреплено (parity-инвариант)
