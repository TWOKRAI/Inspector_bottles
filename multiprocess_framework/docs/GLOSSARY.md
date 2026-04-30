# Glossary — Термины фреймворка

Снимает путаницу между близкими, но различными понятиями. Дополняет [`ROUTING_GLOSSARY.md`](ROUTING_GLOSSARY.md) (там — детали маршрутизации).

---

## Базовые сущности

### Process (процесс)
**Определение:** ОС-процесс, запущенный через `multiprocessing.Process`. В фреймворке — экземпляр класса-наследника `ProcessModule`.

**Ассоциировано:** `name` (строка-идентификатор), `class_path` (для динамической загрузки), `config` (dict).

**Не путать с:** thread / worker / module.

---

### Worker (воркер)
**Определение:** **поток** (`threading.Thread`) внутри процесса. Создаётся через `WorkerManager.create_worker(...)`.

**Два режима:**
- **LOOP** — бесконечный цикл, проверяет `stop_event`. Финальный статус: `STOPPED`.
- **TASK** — одноразовое выполнение. Финальный статус: `COMPLETED`.

**Не путать с:** process (то — ОС, это — поток внутри ОС).

---

### Module (модуль)
**Определение:** **папка** в `multiprocess_framework/modules/<name>/`. Это **код фреймворка**, не runtime-сущность.

**Не путать с:** process / Python module (`.py` файл).

---

### Manager (менеджер)
**Определение:** runtime-объект, наследник `BaseManager + ObservableMixin`. Управляет одной подсистемой (логи, маршрутизация, потоки, конфиг).

**Примеры:** `LoggerManager`, `RouterManager`, `WorkerManager`, `ConfigManager`, `CommandManager`.

---

## Регистры и схемы

### `SchemaBase`
**Определение:** базовый класс для **описания структуры данных**. Наследник `pydantic.BaseModel` с расширениями (`FieldMeta`, `FieldRouting`).

**Применение:** конфиги, регистры, value objects (`Message`).

---

### Register / Регистр
**Определение:** **наследник `SchemaBase`**, описывающий состояние какой-то сущности приложения (камера, рецепт, профиль). Поля имеют `FieldMeta` и опционально `FieldRouting`.

**Метафора:** «чертёж». Сам регистр — это класс. Конкретные значения — инстансы.

**Не путать с:** `SchemaBase` (общий базовый класс) / `RegistersContainer` (контейнер инстансов).

---

### `FieldMeta`
**Определение:** дескриптор поля регистра. Содержит:
- `description: str`
- `min_value` / `max_value` / `unit`
- `routing: FieldRouting | None`
- `access_level: int`
- `ui_*` — UI-метаданные (placeholder, помощь и т.д.)

---

### `FieldRouting`
**Определение:** маршрут поля между процессами. Содержит:
- `channel: str` — имя канала Router'а (логический поток).
- `process_targets: list[str]` — имена процессов-получателей.
- `transform: callable | None` — опциональная трансформация значения.

**Используется:** `RegistersManager.set_field_value()` → `RouterManager.send()`.

---

### `RegistersContainer`
**Определение:** runtime-контейнер **инстансов** регистров (хранилище значений). Реализован в `data_schema_module`. `RegistersManager` его композирует.

---

### `SchemaRegistry`
**Определение:** реестр **классов**-схем (зарегистрированных через `@register_schema`). Глобальный, без Singleton.

**Не путать с:** `RegistersContainer` (хранит инстансы), `RegistersManager` (runtime-фасад).

---

## Сообщения и маршрутизация

### `Message`
**Определение:** value object (наследник `SchemaBase`) для IPC. Поля: `id, type, sender, targets, channel, priority, ts, data`.

**Передача:** между процессами — через `model_dump()` (Dict at Boundary).

---

### `MessageType`
**Определение:** enum типов сообщений: `COMMAND, LOG, SYSTEM, BROADCAST, DATA, REQUEST, RESPONSE, EVENT, GENERAL`.

---

### Target / `targets`
**Определение:** **имена процессов-получателей** в `Message.targets`. Список строк-идентификаторов процессов.

**Не путать с:** канал.

---

### Channel (канал)
**Определение:** **логический поток** сообщений. Используется:
1. В `Message.channel` — для маршрутизации Router'ом.
2. В `FieldRouting.channel` — для привязки поля к каналу.
3. В `LoggerManager` / `StatsManager` / `ErrorManager` — как «выходное русло» (FileChannel, ConsoleChannel и т.п.).

**Не путать с:** target (имя процесса) и Queue (физическая очередь).

**Подробно:** [`ROUTING_GLOSSARY.md`](ROUTING_GLOSSARY.md).

---

### Queue (очередь)
**Определение:** `multiprocessing.Queue` — **физический транспорт** сообщений между процессами. Создаётся `SharedResourcesManager.register_process()`.

**Не путать с:** канал (логический) — канал может использовать очередь, сокет, HTTP.

---

## Подсистемы

### `BaseManager`
**Определение:** ABC с lifecycle (`initialize()`, `shutdown()`) и адаптерами (`attach_adapter`, `get_adapter`).

---

### `ObservableMixin`
**Определение:** miksин с приватными прокси: `_log_*`, `_record_metric`, `_record_timing`, `_track_error`. Делегирует в реестр менеджеров (`logger`, `stats`, `error`).

---

### `BaseAdapter`
**Определение:** ABC адаптера, инкапсулирующего интеграцию менеджера с процессом или внешним ресурсом. Подключается через `manager.attach_adapter(name, adapter)`.

---

### CRM — `ChannelRoutingManager`
**Определение:** базовый класс для менеджеров с **каналами**. Наследники: `LoggerManager`, `RouterManager`, `StatsManager`, `ErrorManager`. Включает `ChannelRegistry`, `Dispatcher`, `IBufferStrategy`, `normalize_config()`.

---

### CRM-канал (`IChannel`)
**Определение:** ABC канала: `send(record) -> bool`, `flush()`, `close()`. Реализации: `FileChannel`, `ConsoleChannel`, `HttpChannel`, `QueueChannel`, `SocketChannel`, `ConsoleLogChannel` и т.д.

---

### Dispatcher
**Определение:** сопоставление **ключ → handler** по одной из 4 стратегий (`EXACT_MATCH`, `PATTERN_MATCH`, `FALLBACK_MATCH`, `CHAIN_MATCH`). Используется внутри CRM, `CommandManager`, `RouterManager`.

---

### Сценарий (`Scenario`)
**Определение:** последовательность handler'ов (`CHAIN_MATCH`). Создаётся через `ScenarioBuilder` (fluent API).

---

## SharedResources

### `SharedResourcesManager` (SRM)
**Определение:** фасад над всеми межпроцессными ресурсами: `Queue`, `Event`, `SharedMemory`, `ConfigStore`, `ProcessStateRegistry`. Pickle-safe для Windows spawn.

---

### `ProcessHandle`
**Определение:** chainable-объект для доступа к ресурсам конкретного процесса:

```python
srm.for_process("camera").queue("system").send(msg)
srm.for_process("camera").event("stop").set()
srm.for_process("camera").memory("frames").write(data)
```

---

### `ProcessStateRegistry` (PSR)
**Определение:** **единственный источник истины** для динамического состояния процессов: status, queues, events, metadata. Реализован в `shared_resources_module`.

---

### `ConfigStore`
**Определение:** pickle-safe **dict** в SRM для статической конфигурации всех процессов. Cross-process синхронизация через `ConfigManager.sync_config()` / `load_config_from_storage()`.

---

### `ProcessData`
**Определение:** dataclass с ресурсами одного процесса: `status`, `queues`, `events`, `metadata`, `custom`. Хранится в PSR.

---

## Жизненный цикл

### `SystemLauncher`
**Определение:** фасад точки входа. Принимает `processes: list[(name, dict)]`, запускает оркестратор.

---

### `ProcessSpawner`
**Определение:** стартер OS-процесса оркестратора. Создаёт SRM, ставит signal handlers, запускает `ProcessManagerProcess`.

---

### `ProcessManagerProcess` (PMP)
**Определение:** оркестратор-процесс (наследник `ProcessModule`). Composite из `ProcessRegistry`, `ProcessMonitor`, `ProcessPriority`, `ProcessStatus`, `EventManager`.

**Метафора:** «генеральный директор» приложения.

---

### `ProcessRegistry`
**Определение:** реестр всех дочерних процессов с **per-process** `stop_events`. Управляет lifecycle: create/start/stop/restart/remove.

---

### `ProcessMonitor`
**Определение:** heartbeat thread в PMP. Опрашивает `is_alive()`, broadcast-ит изменения статуса.

---

### `stop_event`
**Определение:** `multiprocessing.Event`. Каждый процесс получает свой (per-process). Установка в `True` — сигнал на graceful shutdown.

---

## Прикладной слой

### `ProcessModule`
**Определение:** **базовый класс** для пользовательских процессов. Содержит готовые подсистемы: `worker_manager`, `router`, `command_manager`, `logger_manager`, `error_manager`, `stats_manager`, `console_adapter`.

**Что наследник реализует:** `initialize()`, `run()`, `shutdown()`.

---

### `MessageAdapter`
**Определение:** **рекомендованный** способ создания сообщений. Фиксирует `sender` один раз. Методы: `command/log/system/broadcast/data/request/response/event`.

---

### `RegistersManager`
**Определение:** runtime-фасад для **именованных экземпляров** регистров. Pub/sub, `set_field_value` с fan-out, `build_routing_map`.

**Не путать с:** `SchemaRegistry` (реестр классов) / `RegistersContainer` (хранилище инстансов в data_schema).

---

### `FrontendRegistersBridge`
**Определение:** мост между виджетом и регистром. Подписывается на регистр → обновляет UI; обратно — `set_field_value()`.

---

## Сокращения

| Сокращение | Расшифровка |
|-----------|-------------|
| **CRM** | `ChannelRoutingManager` (паттерн канальной маршрутизации) |
| **PMP** | `ProcessManagerProcess` |
| **SRM** | `SharedResourcesManager` |
| **PSR** | `ProcessStateRegistry` |
| **SoT** | Source of Truth (источник истины) |
| **DI** | Dependency Injection |
| **IPC** | Inter-Process Communication |
| **DDL** | Data Definition Language (SQL) |
| **DML** | Data Manipulation Language (SQL) |
| **UoW** | Unit of Work (транзакция) |
| **ADR** | Architecture Decision Record |
| **API** | Application Programming Interface |
| **ABC** | Abstract Base Class |

---

## Кросс-ссылки

- [`SPEC.md`](../SPEC.md) — главная спецификация фреймворка.
- [`MODULES_OVERVIEW.md`](MODULES_OVERVIEW.md) — навигатор по модулям.
- [`MODULE_CONTRACTS.md`](MODULE_CONTRACTS.md) — контракт каждого модуля.
- [`INTERACTION_FLOWS.md`](INTERACTION_FLOWS.md) — цепочки взаимодействия.
- [`DESIGN_RULES.md`](DESIGN_RULES.md) — императивные правила.
- [`ROUTING_GLOSSARY.md`](ROUTING_GLOSSARY.md) — детали маршрутизации (channel vs target).
