 # Multiprocess Framework — Architecture

> **Статус документа:** каркас (Фаза 0 рефакторинга v4.1).
> §1–§4 заполнены. §5 «Жизненный цикл», §6 «Модули», §7 «Внешние пакеты», §8 «ADR» — заголовки-заглушки, наполняются по одной секции после каждого модуля Фазы 1.
> **Принцип документа:** один входной документ на весь фреймворк. После Фазы 1 этот файл заменяет `README.md` (root), `STRUCTURE.md`, `DOCUMENTATION_INDEX.md`, `MODULES_STATUS.md`, `PROBLEMS.md`, `docs/FRAMEWORK_OVERVIEW.md`, `docs/ARCHITECTURE_REFERENCE.md`.

---

## 1. Идея фреймворка (конструктор)

**`multiprocess_framework` — это конструктор многопроцессных приложений на Python.**

Основа идеи — **конструктор процессов**: фреймворк прячет под капот всю многопроцессорную боль Python (spawn/fork, pickle-safe сериализацию под Windows, жизненный цикл, health-check, graceful shutdown, IPC, маршрутизацию, наблюдаемость, интеграцию с внешними системами) и даёт разработчику приложения набор готовых «деталей», которые собираются друг в друга через явные интерфейсы. Дополнительный бонус — **C++-уровень возможностей на скорости разработки Python**: Python перестаёт быть узким местом для системной интеграции и многопроцессорности, сохраняя при этом скорость итераций.

Ключевая **часть механизма построения** — **регистр-ориентированная модель**. Регистр — это `SchemaBase`-наследник, у которого каждое поле описано через `FieldMeta` с `FieldRouting(channel=..., process_targets=...)`. Одна декларация поля даёт: тип, валидацию, UI-метаданные, дефолт, маршрут между процессами. Регистры — это **единый источник истины** для бэкенда и фронтенда, а `RouterManager` по `FieldRouting` знает, в какой процесс и канал отправить изменение.

### Что фреймворк прячет под капот

- создание процессов (spawn/fork, pickle-safe, Windows/Linux);
- контроль жизненного цикла (старт, health-check, graceful shutdown, рестарт при падении);
- взаимодействие между процессами (очереди, shared memory, Router-каналы);
- передачу данных (Dict at Boundary, `model_dump()` на границе);
- маршрутизацию сообщений (имя процесса + канал Router);
- наблюдаемость (logger / error / statistics, упакованные в единый `Message` и отправленные в Router по каналам);
- взаимодействие с внешними объектами — БД, нейросети, контроллеры, камеры, устройства — через стандартизованные менеджеры и воркеры.

### Что остаётся разработчику приложения

1. **Построить регистры** — наследники `SchemaBase` с `FieldMeta` + `FieldRouting`, описывающие параметры приложения и их адресацию.
2. **Описать схемы конфигов** — для каждого процесса, менеджера, воркера.
3. **Наполнить процессы воркерами со своей логикой** — опрос камеры, обработка кадров, Modbus, инференс нейросети, PyQt-интерфейс и т. п.
4. **Подключить функциональные модули-детали** — sql, logger, statistics, console и прочие готовые «детали» конструктора.

### Миссия в одной фразе

> Расширить возможности Python до уровня C++ в части многопроцессорности и системной интеграции, при этом **ускорив** разработку приложений, а не замедлив её — за счёт конструктора «деталей» и регистр-ориентированной модели как единого источника истины.

Эта формулировка — ось всего рефакторинга. Каждое архитектурное решение проверяется вопросом: *«упрощает ли это жизнь разработчику приложения, или просто добавляет ещё одну абстракцию внутрь фреймворка?»*

---

## 2. Слои

Модули сгруппированы по слоям снизу вверх (от листьев к корням графа зависимостей). Внутри слоя модули независимы или зависят только от нижележащих слоёв.

| Слой | Модули | Роль |
|------|--------|------|
| **Foundation** | `base_manager`, `data_schema_module` | Базовые примитивы: `ObservableMixin`, `SchemaBase`, `FieldMeta`, `FieldRouting`, `SchemaRegistry`. Сердце фреймворка. |
| **Routing primitives** | `dispatch_module`, `channel_routing_module` | Примитивы маршрутизации: регистрация ключ→handler, стратегии (exact/pattern/fallback/chain), CRM как базовый класс менеджеров с каналами. |
| **Messaging** | `message_module`, `router_module` | Единый `Message` (dict at boundary) и `RouterManager` поверх CRM: отделяет имя процесса (`targets`) от канала Router (`FieldRouting.channel`). |
| **Observability** | `logger_module`, `error_module`, `statistics_module` | Наследники CRM с каналами (файл, терминал, prometheus, UI). Разные входы (log record / error+traceback / metric point), одинаковая выходная дорожка через `Message` → Router. |
| **Resources & Config** | `shared_resources_module`, `config_module` | Pickle-safe SRM и `ConfigStore` (dict на границе, Pydantic внутри). |
| **Command & Work** | `command_module`, `worker_module` | `CommandManager` (семантика «команда» поверх dispatch) и `WorkerManager` (жизненный цикл воркеров внутри процесса). |
| **Process** | `process_module`, `process_manager_module`, `console_module` | `ProcessModule` — база дочернего процесса; `ProcessManagerProcess` — оркестрация; `console_module` — кросс-платформенный интерактив для регистров. |
| **Storage** | `sql_module` | SQL-воркер с dict-at-boundary для запросов. |
| **Application kit** | `registers_module` | Инфраструктура для регистров (process_registry, discovery, RegistersMeta). Сами регистры создаются в прикладном коде. |
| **External (Фаза 2)** | `frontend_framework` (вынесен из фреймворка) | PyQt-приложение как отдельный процесс, связь через `ProcessModule` + `RouterManager` + `FieldRouting`. |

---

## 3. Граф зависимостей

Направление стрелок — «зависит от». От листьев (низ) к корням (верх).

```mermaid
graph BT
    base[base_manager]
    schema[data_schema_module]
    dispatch[dispatch_module]
    crm[channel_routing_module]
    message[message_module]
    router[router_module]
    logger[logger_module]
    error[error_module]
    stats[statistics_module]
    srm[shared_resources_module]
    config[config_module]
    command[command_module]
    worker[worker_module]
    process[process_module]
    pmgr[process_manager_module]
    console[console_module]
    sql[sql_module]
    registers[registers_module]
    frontend[frontend_framework]

    dispatch --> base
    crm --> base
    crm --> schema
    crm --> dispatch

    message --> schema
    router --> crm
    router --> message
    router --> dispatch

    logger --> crm
    error --> logger
    stats --> crm

    srm --> base
    config --> base
    config --> schema

    command --> dispatch
    worker --> base

    process --> worker
    process --> router
    process --> logger
    process --> srm
    process --> schema

    pmgr --> process
    pmgr --> command

    console --> base
    console --> schema
    console --> logger

    sql --> base
    sql --> schema

    registers --> schema

    frontend --> process
    frontend --> router
    frontend --> schema
```

Порядок рефакторинга идёт от листьев к корням — сначала `base_manager` / `data_schema_module`, в конце `process_manager_module` / `console_module` / `frontend_framework`. Полный порядок и обоснование — в `plans/refactoring/00_overview.md`.

---

## 4. Сквозные принципы

Эти принципы действуют во всех модулях. Отклонения фиксируются как ADR в `DECISIONS.md`.

1. **Dict at Boundary (ADR-008).** Между процессами передаются только `dict`. На границе — `schema.model_dump()`, внутри процесса — Pydantic v2. Никаких кастомных сериализаторов, `model_dump()` один на всех.
2. **`SchemaBase` + `FieldMeta` + `FieldRouting` — единая модель конфигов и регистров.** Одна декларация поля даёт тип, валидацию, UI-метаданные, дефолт и маршрут между процессами. У каждого модуля есть свой дефолтный конфиг-наследник `SchemaBase` (`LoggerManagerConfig`, `RouterManagerConfig`, ...). Регистры создаются в прикладном коде как те же `SchemaBase`-наследники, но с `FieldRouting` на каждом поле.
3. **`ObservableMixin` — единый способ подключить logger / stats / error.** Два уровня сложности (после рефакторинга): приватные методы (`_log_*`, `_record_*`, `_track_*`) + опциональный `auto_proxy`. Никаких `PluginRegistry`, `ObservableDecorators`, `simple_mode`.
4. **`interfaces.py` — единственный публичный контракт модуля.** Потребитель зависит от Protocol/ABC, а не от конкретных реализаций. Это держит DI и моки.
5. **Pickle-safe для Windows spawn.** Любой объект, уходящий в `RouterManager`/`Queue`/`shared_resources_module`, проверен на сериализуемость под `spawn`. Проверка — тестом.
6. **Channel vs target.** Имя процесса (`targets` в `send_message`) и канал Router (`FieldRouting.channel`, `msg["channel"]`) — это разные вещи. Смешение запрещено, проверяется `ipc-routing-checker`. См. `docs/ROUTING_GLOSSARY.md`.
7. **Один публичный API на модуль — `interfaces.py` + `__init__.py`.** Из `__init__.py` экспортируется только то, что нужно внешнему потребителю.
8. **Логирование через `ObservableMixin`**, не через `print`, не через `logging` напрямую. Пути логов — из env (`MULTIPROCESS_LOG_DIR` / `INSPECTOR_LOG_DIR`), не хардкод от cwd.
9. **Никакого `sys.path.insert`** — только корректные пакеты и `PYTHONPATH`, как описано в `README.md` модуля.
10. **Backward compatibility удаляется без жалости.** Решение автора для текущего рефакторинга: алиасы и методы-преобразования не держим, потребители мигрируются синхронно.
11. **Регистры — в прикладном коде, не во фреймворке.** Фреймворк предоставляет примитивы (`SchemaBase` + `FieldMeta` + `FieldRouting` + `RouterManager`), приложение собирает регистры как наследники. Это отражает философию конструктора.
12. **Документация по мере рефакторинга (Tier 1).** Во время Фазы 1, по мере готовности модулей, пополняются файлы высокого приоритета:
    - **Шаг Фазы 0.5** (модуль #1): создать `QUICK_REFERENCE.md`, добавить оглавление в `DECISIONS.md`, создать `ARCHITECTURE_MAP.md` (текстовая диаграмма).
    - **Каждый модуль** (Фаза 1, Шаг 5 per-module плана): после заполнения §6.X в этом файле обновить Tier 1 файлы, если архитектура изменилась.

Полный перечень ADR — `DECISIONS.md`.

---

## 4.1. Документация высокого приоритета (Tier 1) — создание и поддержка

**Фаза 0.5** — один раз в начале Фазы 1, при рефакторинге модуля:

| Файл | Назначение | Объём | Когда создаётся |
|------|-----------|-------|-----------------|
| [`QUICK_REFERENCE.md`](QUICK_REFERENCE.md) | Таблица с якорями на ключевые файлы, интерфейсы, скрипты | ~50 строк | Фаза 0.5 (модуль #1) |
| [`ARCHITECTURE_MAP.md`](ARCHITECTURE_MAP.md) | ASCII диаграмма модулей, потоков данных, IPC-точек | ~100 строк | Фаза 0.5 (модуль #1) |
| [`DECISIONS.md`](DECISIONS.md) оглавление | Раздел «Содержание» с якорями на все ADR (глобальные + модульные) | ~50 строк | Фаза 0.5 (модуль #1) |
| [`CONTEXT_HINTS.md`](CONTEXT_HINTS.md) (`.claude/`) | Типичные ошибки, паттерны, gotchas для агентов | ~100 строк | Фаза 0.5 (модуль #1, опционально) |
| Каждый модуль: `modules/X/DECISIONS.md` | Локальные архитектурные решения (ADR-140+) | ~200 строк | Фаза 1, Шаг 5 per-module плана |

**Фаза 1 и далее** — по мере готовности модулей, Шаг 5 (Документация) per-module плана:
- Заполняется подсекция §6.X (роль модуля, диаграмма, ссылки).
- Обновляются Tier 1 файлы, если архитектура модуля привнесла новые интерфейсы или паттерны.

**Цель:** Эти файлы экономят 10–15K токенов на проект, снижают ошибки на 50%, ускоряют ориентацию в коде в 2x раза.

---

## 5. Жизненный цикл приложения

> **TODO (Фаза 1).** Здесь появится sequence-диаграмма `SystemLauncher → ProcessManagerProcess → дочерние процессы → runtime-сообщения → graceful shutdown`. Заполняется после рефакторинга `process_manager_module` (модуль #13, milestone M1).

---

## 6. Модули

> **Процесс заполнения (Фаза 1, Шаг 5 per-module плана):**
> 1. Заполняется подсекция 6.X (роль, диаграмма, ссылка на README).
> 2. **Одновременно обновляются Tier 1 документы:**
>    - `QUICK_REFERENCE.md` — если появился новый ключевой файл или интерфейс.
>    - `ARCHITECTURE_MAP.md` — если изменилась связь модуля с другими.
>    - `DECISIONS.md` оглавление — если добавились новые ADR.
> 3. Объём подсекции — ≤ 100 строк: роль, mermaid-диаграмма локальных связей, ссылка на `README.md` модуля.

### 6.1 `base_manager` — фундамент менеджеров

**Роль:** Предоставляет две независимые строительные блоки, из которых собираются все менеджеры фреймворка.

**`BaseManager`** — абстрактный класс с жизненным циклом (`initialize()`, `shutdown()`), управлением адаптерами (`attach_adapter()`, `get_adapter()`) и диагностикой (`get_debug_info()`).

**`ObservableMixin`** — примесь для наблюдаемости: менеджер говорит `self._log_info("msg")`, и mixin сам найдёт `logger_manager` и вызовет его метод. Два режима: приватные методы (по умолчанию, pickle-safe) и опциональные публичные прокси-методы (`auto_proxy=True`). После unpickle в multiprocessing гарантирует, что `_log_*` возвращают `None` без исключений, пока менеджеры не перерегистрированы.

**`BaseAdapter`** — базовый класс адаптеров, инкапсулирующих интеграцию с процессом или внешним ресурсом.

```
BaseManager (жизненный цикл, адаптеры)
    ├── attach_adapter / get_adapter / detach_adapter
    └── initialize / shutdown (abstract)

ObservableMixin (наблюдаемость)
    ├── _log_* / _record_* / _track_*  (приватные методы, всегда pickle-safe)
    ├── [auto_proxy] log_*/record_*/track_*  (опциональные публичные)
    └── ManagerRegistry (реестр сервисов — logger, stats, error, ...)

Все менеджеры: class M(BaseManager, ObservableMixin)
```

Ключевые решения (ADR-040…043):
- Удалена плагинная система (дублировала приватные методы).
- Удалены декораторы `@logged`/`@timed`/`@monitored` (4-й способ делать одно и то же).
- Удалена magic `BaseManager.__getattr__` для адаптеров (используйте `get_adapter(name)`).
- Удалены события `on_event`/`emit_event` (дублируют dispatch_module/router_module).

📖 Подробнее: [`modules/base_manager/README.md`](modules/base_manager/README.md) · [`modules/base_manager/docs/OBSERVABLE_ARCHITECTURE.md`](modules/base_manager/docs/OBSERVABLE_ARCHITECTURE.md)
### 6.2 `data_schema_module` — ядро данных

**Роль:** Независимое ядро для описания структур данных на базе Pydantic v2. Нулевые зависимости от других модулей фреймворка.

**`SchemaBase`** (`RegisterBase`) — базовый класс для регистров. Наследник Pydantic `BaseModel` с дополнительными возможностями: `FieldMeta` (UI-метаданные, валидация, ограничения), `FieldRouting` (канал Router, process_targets), `RegisterDispatchMeta` (цели доставки для всего регистра).

**`SchemaMixin`** (`RegisterMixin`) — ключевые методы для работы с полями: `build()` → `(manager_name, model_dump())` для Dict at Boundary.

```
SchemaBase (Pydantic v2 BaseModel)
    ├── FieldMeta            — дескриптор поля (min/max, UI-подсказки)
    ├── FieldRouting         — канал Router + process_targets
    └── RegisterDispatchMeta — цели доставки для регистра

SchemaRegistry              — реестр схем (без Singleton)
DataConverter / FileStorage — сериализация: dict/JSON/YAML
RegistersContainer          — контейнер состояния регистров
```

Ключевые решения (ADR-120…123):

- Удалён `_compat.py` (0 внешних потребителей).
- Удалены shim-директории (`fields/`, `utils/` re-exports).
- `extensions/` — только явный импорт, не входит в top-level API.

📖 Подробнее: [`modules/data_schema_module/README.md`](modules/data_schema_module/README.md)

### 6.3 `dispatch_module` — маршрутизация внутри процесса

**Роль:** Сопоставление входящего сообщения (`dict`) с обработчиком по ключу и стратегии: exact / pattern / fallback / chain (сценарии). Зависит только от `base_manager` (`BaseManager` + `ObservableMixin`).

**`Dispatcher`** — фасад: регистрация обработчиков, `dispatch()`, сценарии через композицию **`ScenarioManager`** (`core/scenarios.py`). Стратегии — отдельные классы в `strategies/`. **`BaseDispatcher`** — облегчённый вариант только с `EXACT_MATCH`, без наблюдаемости.

```
Dispatcher
    ├── strategies/*     — Exact / Pattern / Fallback / Chain
    ├── ScenarioManager  — CRUD сценариев + dispatch_scenario
    ├── types/types      — DispatchStrategy, HandlerInfo, Scenario
    └── builders/        — ScenarioBuilder (fluent API)
```

Ключевые решения (ADR-130…132):

- Сценарии вынесены в `ScenarioManager`; публичные методы на `Dispatcher` остаются тонкими делегатами.
- Удалён legacy-конструктор (`logger_manager=` и т.д.); подключение сервисов — через `managers` / `config`.
- Удалён alias `AdvancedDispatcher`.

📖 Подробнее: [`modules/dispatch_module/README.md`](modules/dispatch_module/README.md) · [`modules/dispatch_module/DECISIONS.md`](modules/dispatch_module/DECISIONS.md)
### 6.4 `channel_routing_module` — паттерн CRM

**Роль:** Базовый класс для всех менеджеров с канальной маршрутизацией. Устраняет дублирование между Logger, Error, Router, Stats — все наследуют `ChannelRoutingManager`.

**`ChannelRoutingManager`** (`BaseManager` + `ObservableMixin`) — фасад, объединяющий:

- `ChannelRegistry` — потокобезопасный реестр каналов (`IChannel`)
- `Dispatcher` — маршрутизация ключ → канал (из `dispatch_module`)
- `IBufferStrategy` — опциональная буферизация (Direct / Batch / AsyncSender)
- `normalize_config()` — Dict at Boundary для конфигов

```
ChannelRoutingManager (BaseManager + ObservableMixin)
    ├── ChannelRegistry    — register/get/unregister каналов
    ├── Dispatcher         — key → handler (dispatch_module)
    ├── IBufferStrategy    — Direct / Batch / AsyncSender
    └── normalize_config() — dict ← None | dict | SchemaBase

Наследники:
    ├── LoggerManager   (BatchBuffer, scope/level → ILogChannel)
    │       └── ErrorManager   (severity → channel)
    └── RouterManager   (AsyncSender, IMessageChannel)
```

Ключевые решения (ADR-013…016, ADR-108):

- CRM-паттерн как единая основа канальных менеджеров.
- Три буфера для разных сценариев (sync/batch/async).
- Две роли конфигов: runtime (для наследования) и flat (для реестра/UI).

📖 Подробнее: [`modules/channel_routing_module/README.md`](modules/channel_routing_module/README.md) · [`modules/channel_routing_module/DECISIONS.md`](modules/channel_routing_module/DECISIONS.md)
### 6.5 `logger_module` — первый CRM-наследник

**Роль:** Логирование со scope-based маршрутизацией (SYSTEM / BUSINESS / PERFORMANCE / AUDIT / SECURITY). Первый реальный наследник CRM-паттерна.

**`LoggerManager`** (`ChannelRoutingManager`) — scope + level → каналы (FileChannel / ConsoleChannel / HttpChannel). Использует `BatchBuffer` из CRM для пакетной записи. Поддержка per-module файлов, thread-local контекста, динамического should_log().

```
LoggerManager (ChannelRoutingManager)
    ├── _channel_registry  — FileChannel / ConsoleChannel / HttpChannel
    ├── _buffer (BatchBuffer) — batch flush по size/interval
    ├── _dispatcher (Dispatcher) — scope/level → handler
    ├── LogRecord (core/log_types.py) — dataclass записи
    └── LoggerAdapter — обёртка для multiprocess

Наследник: ErrorManager (severity routing: WARNING/ERROR/CRITICAL → отдельные файлы)
```

Ключевые решения (ADR-140…142):

- Удалён LogDispatcher (дублировал CRM's Dispatcher).
- Удалён BatchManager (дублировал CRM's BatchBuffer).
- LogRecord — отдельный тип в `core/log_types.py`.

📖 Подробнее: [`modules/logger_module/README.md`](modules/logger_module/README.md) · [`modules/logger_module/DECISIONS.md`](modules/logger_module/DECISIONS.md)
### 6.6 `config_module` — конфигурационное хранилище

**Роль:** Runtime-доступ к конфигурациям со scope-based подписками.

**Config** (~160 LOC) — простой контейнер (dict + dot-notation + RLock), без валидации и файлового I/O.  
**ConfigManager** (~215 LOC) — коллекция объектов `Config` с синхронизацией через ConfigStore (Dict at Boundary).

```
Config (dict + RLock + подписки)
    ├── dot-notation: get("database.host")
    ├── подписки: subscribe(callback, key="*")
    ├── ConfigSection — view на подсекцию
    └── env-fallback (опционально, через env_prefix)

ConfigManager
    ├── _configs: Dict[str, Config]
    ├── ConfigStore (SRM): dict на границе для cross-process синхронизации
    ├── create_config(), get_config(), remove_config()
    ├── sync_config() → ConfigStore (config.data как dict)
    └── load_config_from_storage() ← ConfigStore (dict → Config)
```

Ключевые решения: **ADR-023** (global) — тонкая обёртка над `data_schema_module`; **ADR-143…146** (локально в модуле) — Dict at Boundary для ConfigStore, отсутствие I/O в модуле, пять компонентов, опциональный env-fallback. **Pydantic / SchemaBase** — только у **`ConfigManagerConfig`** и в адаптере схем; payload в ConfigStore остаётся plain dict.

📖 Подробнее: [`modules/config_module/README.md`](modules/config_module/README.md) · [`modules/config_module/DECISIONS.md`](modules/config_module/DECISIONS.md) · [`modules/config_module/docs/ARCHITECTURE.md`](modules/config_module/docs/ARCHITECTURE.md)

### 6.7 `message_module` — IPC-примитив

**Роль:** Value object для межпроцессного взаимодействия. Leaf-зависимость (только `data_schema_module`).

**Message** (`SchemaBase`, ~485 LOC) — typed IPC container: поля Pydantic + `FieldMeta`, fluent API, Dict at Boundary.  
**MessageAdapter** (~327 LOC) — контекстная фабрика (один на процесс, фиксированный sender).

```
Message (SchemaBase / value object)
    ├── create(type, sender, targets, ...) — основной метод
    ├── model_dump() / to_dict() / from_dict() — Dict at Boundary
    ├── fluent API: set_priority(), set_targets(), set_channel()
    └── optional строгая схема: CommandMessageSchema, LogMessageSchema (extra='forbid')
        (BaseMessageSchema — алиас на Message для обратной совместимости импорта)

MessageAdapter(sender=name)
    ├── .command(targets, command, args)
    ├── .log(level, message, module)
    ├── .system(targets, action)
    ├── .broadcast(content)
    ├── .data(targets, data_type, data)
    ├── .request(targets, request_type)
    ├── .response(targets, request_id, result)
    └── .event(event_type, targets, data)
```

Ключевые решения (ADR-147…152):
- **Dict at Boundary:** только `msg.to_dict()` пересекает границу.
- **`schema=None` — нормальный путь,** отдельная Pydantic-схема (`CommandMessageSchema` / …) — опциональное усиление.
- **Message = SchemaBase** — единый источник полей; **IMessage** — `Protocol` (**ADR-152**).
- **MessageAdapter** — рекомендованный способ в процессах.
- **Поле `routers`:** RouterManager'ы внутри процесса.

📖 [`modules/message_module/README.md`](modules/message_module/README.md) · [`modules/message_module/DECISIONS.md`](modules/message_module/DECISIONS.md)

### 6.8 `shared_resources_module` — межпроцессные ресурсы

**Роль:** Централизованный pickle-safe реестр всех разделяемых ресурсов (очереди, события, SharedMemory). Разделяет статическую конфигурацию (ConfigStore) от динамического состояния (ProcessStateRegistry). Зависит только от #1 `base_manager`.

**SharedResourcesManager** (~408 LOC) — фасад-делегатор: оркестрирует 5 внутренних менеджеров.
**ProcessStateRegistry** (~230 LOC) — единственный источник истины для Queue/Event/status.
**ProcessHandle** (~226 LOC) — chainable Handle API для доступа к ресурсам процесса.
**MemoryManager** (~414 LOC) — жизненный цикл SharedMemory (owner create/unlink, consumer open/close).

```
SharedResourcesManager (facade)
    ├── register_process(name, config) — единая точка регистрации (ADR-018)
    ├── for_process(name) → ProcessHandle — Handle API (ADR-SRM-002)
    │   ├── .queue("system").send(msg)     — QueueHandle
    │   ├── .event("stop").set()           — EventHandle
    │   └── .memory("frames").write(data)  — MemoryHandle
    ├── ConfigStore — dict-хранилище (pickle-safe, статика)
    ├── ProcessStateRegistry — Dict[str, ProcessData] (динамика)
    │   └── ProcessData: status, queues (Proxy), events (Proxy), metadata
    ├── QueueRegistry — делегирует хранение в PSR (ADR-SRM-003)
    ├── EventManager — системные события + подписки + router-интеграция
    └── MemoryManager — SharedMemory + MemoryAccessStatus enum (ADR-SRM-004)
```

Ключевые решения (ADR-SRM-001…008):
- **Handle API:** `for_process()` → QueueHandle/EventHandle/MemoryHandle — единый chainable доступ (**ADR-SRM-002**).
- **PSR — single source of truth:** QueueRegistry не кеширует очереди, делегирует в PSR (**ADR-SRM-003**).
- **Pickle-safe:** ConfigStore = dict, Queue/Event — нативно. `reinitialize_in_child()` восстанавливает EventManager._event_queue и MemoryManager.handles (**ADR-020**, **ADR-021**).
- **MemoryAccessStatus enum** вместо bool — диагностические причины отказа (**ADR-SRM-004**).

📖 [`modules/shared_resources_module/README.md`](modules/shared_resources_module/README.md) · [`modules/shared_resources_module/DECISIONS.md`](modules/shared_resources_module/DECISIONS.md)

### 6.9 `router_module` — маршрутизация сообщений

**Роль:** Масштабируемая маршрутизация IPC-сообщений между процессами. CRM-наследник (#4), использует Message (#7), Dispatcher (#3).

**RouterManager** (CRM-наследник) — фасад: AsyncSender (outgoing pipeline), AsyncReceiver (incoming poll), два dispatcher'а.  
**RouterAdapter** — тонкая обёртка для ProcessModule (контекст отправителя, `send_to_channel`).  
**RouterSchemaAdapter** — FieldRouting → карта каналов для регистрации.

```
RouterManager(ChannelRoutingManager)
    ├── send() / send_async() → _send_mw → _resolve_channels → channel.send()
    ├── receive() → _poll_all_channels → _recv_mw → message_dispatcher
    ├── channel_dispatcher (= CRM._dispatcher) — исходящие (handlers возвращают имя канала)
    ├── message_dispatcher — входящие обработчики
    ├── AsyncSender — PriorityQueue + фоновый поток
    └── AsyncReceiver — poll thread + callbacks
```

Ключевые решения (ADR-153…158):
- **CRM inheritance:** `_channel_registry`, `_dispatcher` из CRM; AsyncSender — отдельный pipeline (**ADR-153**, **ADR-015**).
- **Name-returning handlers:** dispatch возвращает имя канала, не результат записи (**ADR-154**).
- **Thread-safe _stats:** счётчики под `threading.Lock` (**ADR-156**).

📖 [`modules/router_module/README.md`](modules/router_module/README.md) · [`modules/router_module/DECISIONS.md`](modules/router_module/DECISIONS.md)

### 6.10 `worker_module` — управление потоками-воркерами

**Роль:** Централизованное управление жизненным циклом потоков внутри ProcessModule: создание, запуск, остановка, пауза, мониторинг, перезапуск. Зависит только от base_manager (#1).

**WorkerManager** (BaseManager + ObservableMixin, ~231 LOC) — фасад: делегирует WorkerRegistry (хранение) и WorkerLifecycle (создание/запуск/остановка потоков).
**WorkerAdapter** (~138 LOC) — тонкая обёртка для ProcessModule.
**WorkerSchemaAdapter** (~94 LOC) — извлечение настроек потока из SchemaBase-конфигов.

```
WorkerManager(BaseManager, ObservableMixin, IWorkerManager)
    ├── create_worker() / start / stop / restart / pause / resume
    ├── _worker_registry: WorkerRegistry (threading.Lock, Dict[str, WorkerInfo])
    ├── _lifecycle: WorkerLifecycle (create thread, start, stop, auto-restart)
    ├── ThreadConfig (runtime) — to_dict/from_dict (Dict at Boundary)
    └── ThreadWorkerConfig(SchemaBase) — декларативный конфиг (Pydantic)
```

Два режима выполнения:
- **LOOP** — бесконечный цикл, stop_event для остановки. Финальный статус: STOPPED.
- **TASK** — одноразовое выполнение. Финальный статус: COMPLETED.

Два типа воркеров: **SYSTEM** (фреймворк, e.g. message_processor), **APPLICATION** (пользовательский).

Ключевые решения (ADR-159…162):
- **Нет зависимости от dispatch_module:** WorkerManager — lifecycle manager, не message router (ADR-159).
- **Dual config:** ThreadConfig (runtime) + ThreadWorkerConfig (SchemaBase) — осознанное разделение (ADR-160).

📖 [`modules/worker_module/README.md`](modules/worker_module/README.md) · [`modules/worker_module/DECISIONS.md`](modules/worker_module/DECISIONS.md)

### 6.11 `process_module` — базовый класс процесса

**Роль:** Сборка worker, router, logger, command, config, statistics, console, shared resources в единый `ProcessModule` — базовый класс для прикладных процессов. Зависит от #2 `data_schema_module`, #5 `logger_module`, #8 `shared_resources_module`, #9 `router_module`, #10 `worker_module`.

**ProcessModule** (BaseManager + ObservableMixin + IProcessModule) — фасад: делегирует подсистемам без изменения публичного контракта для 19+ наследников.

```
ProcessModule
    ├── ProcessLifecycle — initialize/shutdown; конфиг/очереди: тело в ProcessLifecycle, вызов через `process._init_configuration` / `_init_queues` (делегаты → lifecycle, см. ADR-166a)
    ├── ProcessManagers — pipeline: _create_*_manager → register → attach adapters → event_manager.set_router_manager
    ├── ProcessCommunication — send_message / broadcast / receive_message; send / receive (расширенный API)
    ├── ProcessState — регистрация и обновление состояния в PSR (через shared_resources)
    └── SystemThreads — системные потоки (например message_processor)
```

Два API коммуникации (ADR-163):
- **`send_message(target, message)`** → `bool`
- **`send(message)`** → `Dict` со статусом

**ISharedResources** (Protocol) — DI без жёсткой связи на конкретный SRM (ADR-164).

Ключевые решения (ADR-163…167, ADR-166a):
- **Dual comm API** и **ISharedResources** — см. выше.
- **Удалён shim** `process_module/state/process_state_registry.py`; `ProcessStateRegistry` только из `shared_resources_module` (ADR-165).
- **ProcessManagers** — декомпозиция `initialize()` на подметоды (ADR-166).
- **Конфиг/очереди** — реализация в `ProcessLifecycle`, вызов через `ProcessModule._init_*` (делегаты, ADR-166a).
- **Воркеры из конфига** — `importlib.import_module` (ADR-167).

📖 [`modules/process_module/README.md`](modules/process_module/README.md) · [`modules/process_module/DECISIONS.md`](modules/process_module/DECISIONS.md)

### 6.12 `command_module` — фасад для обработки команд

**Роль:** Тонкий фасад над `dispatch_module` с семантикой «команда». Предоставляет `register_command(name, handler)` / `handle_command(msg)` вместо низкоуровневых `register_handler` / `dispatch`. Зависит от `dispatch_module` (#3) и `base_manager` (#1).

**CommandManager** (BaseManager + ObservableMixin + ICommandManager, ~360 LOC) — фасад: внутренний `Dispatcher` для маршрутизации `msg["command"]` → handler.  
**BaseCommandManager** (~55 LOC) — lightweight конкретный класс для тестов и простых случаев. Только EXACT_MATCH, без ObservableMixin.  
**CommandAdapter** (~109 LOC) — тонкая обёртка для ProcessModule, добавляет `execute_via_message()`.  
**CommandManagerConfig** (SchemaBase) — плоская схема для реестра и UI.

```
CommandManager(BaseManager, ObservableMixin, ICommandManager)
    ├── register_command(name, handler) → dispatcher.register_handler()
    ├── handle_command(msg) → dispatcher.dispatch(msg, key="command")
    ├── get_commands() / get_command_info() / get_commands_by_tag()
    ├── overwrite_command() / update_command_metadata() / update_command_tags()
    └── dispatcher: Dispatcher (composition, all 4 strategies available)
```

**Не путать с CRM:** CommandManager маршрутизирует команды **к функциям**. CRM маршрутизирует данные **в каналы** (файлы, очереди). Общее — оба используют Dispatcher через композицию (ADR-172).

**Синхронный by design (ADR-172).** Async-буферизация обеспечена выше — RouterManager (AsyncSender + message_processor thread). CommandManager работает внутри потока message_processor. Команды — быстрые управляющие сигналы (set_fps, start_capture). Тройной dispatch path: `message_dispatcher → CommandManager → Dispatcher` — O(1) × 3, не bottleneck. Тяжёлые handlers → worker thread, не async command.

Интеграция: `ProcessLifecycle._register_commands_with_router()` мостит команды в `router.message_dispatcher`, чтобы IPC-сообщения (из GUI) доходили до command handlers. `message_dispatcher` — встроенный generic аналог, CommandManager добавляет семантику (tags, metadata, timing stats).

Ключевые решения (ADR-168…172):
- **ICommandManager подключён** к CommandManager (ADR-168)
- **Нет наследования от CRM, синхронный by design** — разные паттерны (ADR-172)
- **Legacy kwargs удалены** — единственный caller использует новый API (ADR-169)

📖 [`modules/command_module/README.md`](modules/command_module/README.md) · [`modules/command_module/DECISIONS.md`](modules/command_module/DECISIONS.md)

### 6.13 `process_manager_module` — *TODO (после модуля #13, milestone M1)*
### 6.14 `error_module` — *TODO (после модуля #14)*
### 6.15 `statistics_module` — *TODO (после модуля #15)*
### 6.16 `sql_module` — *TODO (после модуля #16)*
### 6.17 `registers_module` — *TODO (после модуля #17)*
### 6.18 `console_module` — *TODO (после модуля #18, milestone M2)*

---

## 7. Внешние пакеты

### 7.1 `frontend_framework` — *TODO (Фаза 2, после модуля #19, milestone M3)*

PyQt-приложение, вынесенное из `multiprocess_framework/` в отдельный пакет. Связь с фреймворком — только через стандартные механизмы: `ProcessModule`, `RouterManager`, `Message`, `FieldRouting`. Внутри фреймворка PyQt-кода и импортов не остаётся.

---

## 8. ADR

Полный список — в [`DECISIONS.md`](DECISIONS.md). Ключевые:

- **ADR-008** — Dict at Boundary.
- *ADR-040…ADR-0NN — добавляются в Фазе 1 по мере принятия решений в рамках рефакторинга.*
