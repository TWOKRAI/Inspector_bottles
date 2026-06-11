# Services/device_hub — Статус

## Текущее состояние

**Фаза 1 DONE** — реестр, DeviceManager, 4 драйвера, ~30+ тестов.

## Компоненты

| Компонент | Статус | Тесты |
|-----------|--------|-------|
| DeviceEntry | done | test_entry.py |
| RegistryStore | done | test_store.py |
| build_transport | done | test_transports.py |
| DeviceManager | done | test_manager.py |
| RobotDriver | done | test_robot_driver.py |
| VfdDriver | done | test_vfd_driver.py |
| HikvisionDriver | done (lazy SDK) | — |
| GenericModbusDriver | done | test_generic_modbus.py |

## Следующие шаги

- Фаза 2: процесс `devices` (плагин, base.yaml, клиент)
- Фаза 3: тонкие плагины + рецепт v4
- Фаза 4: GUI-вкладки
