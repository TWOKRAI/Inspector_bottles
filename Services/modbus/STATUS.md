# STATUS — modbus

## Текущий статус: ✅ Готов к использованию (P1–P3)

Дата: 2026-06-01 · Ветка: `feat/services-modbus-driver` · План: `plans/services-modbus-driver.md`

| Аспект | Оценка | Комментарий |
|--------|--------|-------------|
| Архитектура | 9/10 | Три слоя (sdk → core → plugin) + service shell |
| Транспорт | — | TCP + RS485 (RTU) одной либой (pymodbus 3.x) |
| Телеметрия | 9/10 | state/ошибки/счётчики через API, callbacks, register-поля |
| Error handling | 8/10 | ModbusDriverError-иерархия, graceful import |
| Тесты | 8/10 | 82 unit-теста без pymodbus/железа (fake-клиент) + real round-trip |
| Документация | 8/10 | README + STATUS |

## Структура файлов

| Путь | Назначение |
|------|-----------|
| `__init__.py` | Публичный API + ленивая загрузка plugin/service |
| `interfaces.py` | `ModbusClientProtocol` |
| `service.py` | `@register_service("modbus")` `ModbusService` (IService) |
| `sdk/client.py` | Обёртка pymodbus (TCP/RTU), `MODBUS_AVAILABLE` |
| `sdk/datatypes.py` | encode/decode int16/32/float (stdlib) |
| `sdk/errors.py` | Иерархия `ModbusDriverError` |
| `core/config.py` | `ModbusConfig` (transport-агностичный) |
| `core/status.py` | `ConnectionState` + `ModbusStatus` (телеметрия) |
| `core/device.py` | `ModbusDevice` — state machine + Lock + callbacks |
| `core/poller.py` | `ModbusPoller` — опрос блоков регистров |
| `plugin/plugin.py` | `@register_plugin("modbus", category="io")` |
| `plugin/config.py` | `ModbusPluginConfig` (identity + bindings) |
| `plugin/registers.py` | `ModbusRegisters` (config + readonly-телеметрия) |
| `channels/modbus_channel.py` | `ModbusChannel(MessageChannel)` — драйвер как канал RouterManager |
| `server/sim_server.py` | Тестовый Modbus-slave (приёмник) — `run_test_server` + `trace_write` |
| `server/__main__.py` | CLI приёмника: `python -m Services.modbus.server` |
| `__main__.py` | CLI-smoke |
| `tests/` | 82 unit-теста |

## Этапы

- [x] P1 — core + sdk + тесты (38)
- [x] P2 — plugin-слой + `system.yaml` (`plugin_paths += Services`) + тесты (15), discovery OK
- [x] P3 — service shell + README/STATUS + pyproject extra `[modbus]` + тесты (5)
- [x] P4 — RouterManager как канал: `ModbusChannel(MessageChannel)` (send/poll + status/error события) + опц. регистрация в плагине + тесты (16)
- [x] P5 — тестовый Modbus-slave (`server/`) для приёма + demo `modbus_sink` (Plugins) + рецепт `modbus_demo.yaml` + тесты (8)

## Зависимости

| Модуль | Обязательный | Зачем |
|--------|-------------|-------|
| Python 3.12+ | да | type hints |
| pymodbus ≥ 3.7 | опционально | live TCP/RTU (extra `[modbus]`) |
| multiprocess_framework | опционально | плагин/сервис |
