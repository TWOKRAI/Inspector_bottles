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
| RobotDriverV2 (пакет `drivers/robot_driver_v2/`) | done (T5.3f; стенд `harness_smoke` 3 passed ×3, 2026-10-20) | test_robot_driver_v2.py, test_robot_v2_state_acceptance.py, test_no_private_driver_state.py |
| SPI драйвера (`spi.py`, `OpSpec`, команды из описаний) | done (SPI a–g, 2026-10-26; стенд не гонялся) | test_spi_contract.py, test_spi_acceptance.py, test_op_commands.py, test_spi_commands_acceptance.py |
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
- ADR-DH-011: `connect` и `request_stop` драйвера робота v2 линеаризуются переходами `RobotState`
- ADR-DH-012: явный SPI драйвера и команды хаба из описаний операций

## T5.3f — итог

Драйвер робота v2: файл 2037 строк -> пакет из 12 файлов; 30 полей и 53 секции `_flags_lock` -> `RobotState`
(27 полей, 49 секций одного замка; после T5.3g — 31 поле: 27 + 4 `_JogRun`, 55 секций); тестовые обращения к полям состояния 31 -> 0, швы — белый список 112 (сторож
`test_no_private_driver_state.py`). Поведение не менялось — по наборам, матрице инъекций и стенду `harness_smoke` 3×3. Детали и коммиты — `plans/robot-protocol-v2/tasks/T5.3f.result.md`.

**T5.3g:** окна W1, W1′, W2, W4 и WW (`request_stop` посреди `connect`) закрыты переходами `RobotState` (ADR-DH-011).

## SPI хаба — итог (ADR-DH-012)

Контракт драйвера — `Protocol` и умолчания базы вместо `getattr` / `hasattr`; 55 операций в каталогах `OpSpec`, из них
генерируются команды `robot_*` / `vfd_*` (72 имени не менялись); исполнитель `device_io` (4/64) объявлен в топологии
(`base.yaml`, C-47 исправлен в framework); `drv._client` в тестах хаба вне v1/ПЧ/сторожа 43 -> 0; затвор переподключения
в базе. Команды и фабрики — из таблицы видов `kinds.py` по `OP_SPECS` драйверов (SPI.h); подкласс плагина со своим
`device_kinds` получает команды сам, опции драйверов — по виду и по `(вид, протокол)` (SPI.h2). Подзадачи и коммиты — `plans/robot-protocol-v2/tasks/SPI.md`, отступления — `SPI.deviations.md`.

**Открыто:**
- Регенерация `docs/contracts/CAPABILITIES.yaml` / `.md` (`python -m backend_ctl.dump_capabilities`, headless-бэкенд, окно
  `heavy`): до неё `backend_ctl/tests/test_capabilities.py::test_dump_matches_committed` красный.
- Значения `device_io` 4/64 — умолчания `ExecutorSpec`, не замер; стенд для SPI не гонялся.
- Длинные синхронные операции (`toolchange` v1, `stop` v2 до 0,8 с) задерживают поток роутера (вне SPI).
