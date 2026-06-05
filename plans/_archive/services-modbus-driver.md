# План: универсальный драйвер Modbus-TCP / RS485

**Slug:** `services-modbus-driver`
**Ветка:** `feat/services-modbus-driver`
**Дата:** 2026-06-01

## Context (зачем)

В проекте нет ни одного промышленного протокола связи с PLC/контроллерами
(grep `modbus|plc|rs485|pymodbus` — пусто). Для системы инспекции бутылок нужен
канал к железу: читать триггеры/статусы линии и **писать команды выбраковки**
бракованной бутылки в PLC. Нужен универсальный, переиспользуемый драйвер,
который даёт и программный API, и встраивается в GUI/pipeline.

**Решения, согласованные с владельцем:**
- Форма: **Service-пакет с plugin-слоем** (как `Services/hikvision_camera/`) — даёт
  standalone-API *и* плагин для pipeline. «Сервис или плагин» — ложная дилемма:
  для драйвера железа правильно оба в одном пакете.
- Направления: **чтение (вход) + запись (выход) + ручные команды из GUI** — все три.
- Транспорт: **TCP + RS485 (RTU) опцией** — core транспорт-агностичный, выбор в конфиге.
- Библиотека: **pymodbus 3.x** (High reputation, sync+async, TCP+RTU одной либой,
  актуальна на 2026). Используем **sync**-клиент — он ложится на потоковую
  worker-модель фреймворка (как sqlite в `Plugins/io/database`), без asyncio в процессе.

## Архитектура и слои

Слой импортов (`.sentrux/rules.toml`): `app → Plugins → Services → framework`.
Пакет живёт в `Services/modbus/`, импортирует **только** framework + pymodbus +
свой core. **Запрещено** импортировать `multiprocess_prototype.*` и `Plugins.*`.

Три слоя по образцу hikvision:
- `sdk/` — тонкая обёртка над pymodbus (graceful import, как `SDK_AVAILABLE`).
- `core/` — бизнес-логика: state machine соединения, конфиг, thread-safe API.
- `plugin/` — `ProcessModulePlugin` для pipeline + `@register_schema` для GUI-конфига.

**Discovery — «дал путь к папке, он сам находит по ключевым файлам».**
Механизм уже такой, новый писать не нужно — оба сканера обходят директорию
рекурсивно и ищут маркер-файл:
- `ServiceRegistry.discover` → ищет **`service.py`** (glob `**/service.py`),
  импортирует → `@register_service` срабатывает.
- `PluginRegistry.discover` → ищет **`plugin.py`** (rglob `plugin.py`),
  импортирует → `@register_plugin` срабатывает.

Правка `system.yaml`: добавить `"Services"` в `plugin_paths` — тогда `plugin.py`
внутри `Services/modbus/` найдётся автоматически:

```yaml
discovery:
  plugin_paths:
    - "Plugins"
    - "Services"   # ← добавить: плагины внутри Service-пакетов
  service_paths:
    - "Services"
  auto_discover: true
```

Итог: чтобы подключить драйвер — просто кладём папку `Services/modbus/` с файлами
`service.py` и `plugin/plugin.py`; сканеры подхватывают и сервис, и плагин по
ключевым файлам, без ручной регистрации.

## Структура файлов (новые)

```
Services/modbus/
├── __init__.py          # public API: ModbusDevice, ModbusConfig, TransportType; lazy plugin
├── interfaces.py        # @runtime_checkable ModbusClientProtocol
├── service.py           # @register_service("modbus") ModbusService(IService shell)
├── README.md, STATUS.md
├── sdk/
│   ├── client.py        # фабрика pymodbus: ModbusTcpClient | ModbusSerialClient; MODBUS_AVAILABLE
│   ├── errors.py        # ModbusDriverError + graceful ImportError
│   └── datatypes.py     # decode/encode регистров (int16/int32/float)
├── core/
│   ├── config.py        # ModbusConfig: transport(tcp|rtu), host, port, serial_port, baudrate, unit_id, timeout, retries
│   ├── device.py        # ModbusDevice — state machine DISCONNECTED→CONNECTED→ERROR, Lock, read/write
│   └── poller.py        # маппинг блоков регистров для опроса (addr,count,kind)
├── plugin/
│   ├── plugin.py        # @register_plugin("modbus", category="io") ModbusPlugin
│   ├── config.py        # @register_schema ModbusPluginConfig(PluginConfig)
│   └── registers.py     # @register_schema ModbusRegisters(SchemaBase)
├── tests/
└── __main__.py          # CLI smoke
```

## Встраивание в GUI (всё переиспользуется)

1. **Вкладка «Сервисы»** — lifecycle через `ServiceRegistry` (авто).
2. **Инспектор ноды** — конфиг авто-генерится из `register_schema`, live-правка через
   `register_update` IPC (Этап 2 уже готов).
3. **Ручные команды** connect/read/write — через `command_sender` → `RouterManager` → `cmd_*`.

## Зависимости

- `pyproject.toml`: optional-extra `[modbus]` → `pymodbus>=3.6` (тянет `pyserial`).
- `sdk/client.py` — graceful import (`MODBUS_AVAILABLE`), тесты без либы/железа.

## Этапы реализации

1. [x] **P1 — core + sdk** + тесты. Standalone работает.
2. [x] **P2 — plugin-слой** + правка `system.yaml` (`plugin_paths += "Services"`) + тесты. Discovery OK.
3. [x] **P3 — service shell** + README/STATUS + pyproject extra `[modbus]`. (GUI-smoke/ADR — manual, требует `pip install '.[modbus]'`)
4. [x] **P4 — RouterManager как канал:** `channels/modbus_channel.py` —
   `ModbusChannel(MessageChannel)` по образцу `SocketChannel` (`send`=команды→Modbus,
   `poll`=опрос PLC→Message + события status/error); опц. регистрация в `plugin.start()`
   через `ctx.router_manager.register_channel(...)`. Связано с
   `plans/2026-05-31_transport-router-hub/`.
5. Коммиты с trailers `Why:`/`Layer: services` + `Refs: plans/services-modbus-driver.md`.

**Итог:** 74 unit-теста, ruff чисто, слои чисты, discovery service+plugin OK.

## Out of scope

- Async-клиент (sync достаточно; async — будущее).
- Физическая RS485-проверка (нет железа) — mock + ручной smoke владельцем.
- Modbus-server роль (только клиент/master).
- Register-map редактор в GUI — отдельный план.
