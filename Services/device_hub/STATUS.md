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
| RobotDriverV2 (пакет `drivers/robot_driver_v2/`) | done (T5.3f; на стенде не проверен) | test_robot_driver_v2.py, test_robot_v2_state_acceptance.py, test_no_private_driver_state.py |
| DeviceHubPlugin | done | test_device_hub_plugin.py |
| DeviceHubClient | done | test_client.py |

## ADR

- ADR-DH-001: Один мастер — процесс devices
- ADR-DH-002: Bridge-транспорт шарит Lock носителя
- ADR-DH-003: YAML-протокол → RegisterMap + meta
- ADR-DH-004: Удаление носителя — блокировка, НЕ каскад
- ADR-DH-005: YAML-протокол закреплено (parity-инвариант)
- ADR-DH-006: supervisor connect последовательно (known limitation)
- ADR-DH-008: чтение реестра и драйверов только через snapshot-API
- ADR-DH-009: потоки робота — у области плагина; стоп процесса один раз, параллельно, под одним сроком
- ADR-DH-010: одно состояние RobotDriverV2 под одним замком; драйвер — пакет

## T5.3f — итог

Драйвер робота v2: файл 2037 строк -> пакет из 12 файлов; 30 полей и 53 секции `_flags_lock` -> `RobotState`
(27 полей, 49 секций одного замка); тестовые обращения к полям состояния 31 -> 0, швы — белый список 104 (сторож
`test_no_private_driver_state.py`). Поведение не менялось. Детали и коммиты — `plans/robot-protocol-v2/tasks/T5.3f.result.md`.

**Открыто:** окна W1 и W4 (`request_stop` посреди `connect`) — задача T5.3g; живой стенд T5.3f ещё не пройден;
SPI хаба (снятие швов) — следующая задача.
