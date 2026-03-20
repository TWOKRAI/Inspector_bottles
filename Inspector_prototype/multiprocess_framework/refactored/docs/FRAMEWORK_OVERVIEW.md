# Multiprocess Framework — Comprehensive Overview

**Версия:** 2.0 (Refactored, Phase 8/8 Complete)
**Дата:** March 2026
**Статус:** Production Ready ✅

---

## Оглавление

1. [Что это такое и зачем](#что-это-такое-и-зачем)
2. [Архитектурные слои (15 модулей)](#архитектурные-слои-15-модулей)
3. [Принципы архитектуры](#принципы-архитектуры)
4. [Диаграмма зависимостей модулей](#диаграмма-зависимостей-модулей)
5. [Жизненный цикл приложения](#жизненный-цикл-приложения)
6. [Паттерны и принципы](#паттерны-и-принципы)
7. [Ключевые архитектурные решения](#ключевые-архитектурные-решения)
8. [Как всё работает вместе](#как-всё-работает-вместе)
9. [Быстрый старт для разработчиков](#быстрый-старт-для-разработчиков)
10. [FAQ и anti-patterns](#faq-и-anti-patterns)
11. [Глоссарий маршрутизации](ROUTING_GLOSSARY.md) — процесс vs канал Router, схемы регистров приложения и IPC

---

## Что это такое и зачем

### Суть фреймворка

**Multiprocess Framework** — это **архитектурный каркас для построения сложных многопроцессных приложений на Python**. Он предоставляет:

- **Единую модель управления процессами** — от запуска до graceful shutdown
- **Типизированную систему обмена сообщениями** между процессами (по аналогии с микросервисами)
- **Централизованное управление конфигурацией, логированием и ошибками** на уровне фреймворка
- **Потокобезопасность** внутри каждого процесса через `worker_module`
- **Структурированное хранение и синхронизацию данных** между процессами

### Зачем это нужно

В сложных приложениях (компьютерное зрение, обработка видео, IoT, автоматизация):

❌ **Без фреймворка:**
```
process1 → custom queue
process2 → custom logger
process3 → custom config loader
process4 → custom error handler
Итог: 4 параллельных реализации, баги в каждой
```

✅ **С фреймворком:**
```
process1 ──┐
process2 ──┼─→ RouterManager ─→ unified messaging
process3 ──┼─→ LoggerManager ─→ unified logging
process4 ──┴─→ ConfigManager ─→ unified configuration
        ↓
    ProcessManager (orchestration)
    ↓
    SystemLauncher (graceful start/stop)
```

### Преимущества архитектуры

| Преимущество | Почему это важно |
|---|---|
| **Модульность (15 независимых модулей)** | Каждый модуль можно развивать, тестировать и заменять отдельно. Нет сахаров, только явные зависимости. |
| **Dict at Boundary** | Данные между процессами передаются только словарями (pickle-safe). Внутри процесса используются Pydantic модели (типизированные). |
| **BaseManager + ObservableMixin** | Все менеджеры (логирования, конфигурации, роутинга) наследуют единый API для логирования, сбора метрик, отслеживания ошибок. |
| **ChannelRoutingManager** | Три менеджера (RouterManager, LoggerManager, ErrorManager) используют единый паттерн управления каналами, буферизации и диспетчеризации. DRY principle. |
| **Graceful Shutdown** | При получении сигнала (SIGTERM, SIGINT) фреймворк даёт каждому процессу время на завершение, синхронизирует состояние, потом силой убивает зависшие. |
| **Type Safety** | Все сообщения (Message), конфиги (SchemaBase), команды (Command) определяются через Pydantic или Protocol. Явное лучше неявного. |

---

## Архитектурные слои (15 модулей)

### Слой 1: Фундамент (Foundation)

Три модуля, на которых стоит всё:

#### 1. **base_manager** — Абстрактный менеджер
- **Роль:** Предоставить `BaseManager` (абстрактный класс жизненного цикла) и `ObservableMixin` (прокси-методы для логирования/метрик/ошибок)
- **Ключевые классы:**
  - `BaseManager` — ABC с методами `initialize()`, `shutdown()`, управлением адаптерами и событиями
  - `ObservableMixin` — Миксин для прозрачного логирования через `self._log_info()`, `self._record_metric()`, `self._track_error()`
  - `BaseAdapter` — Абстрактный адаптер для инкапсуляции взаимодействия менеджера с процессом

**Используется:** Все 12 остальных менеджеров наследуют `BaseManager + ObservableMixin`

---

#### 2. **data_schema_module** — Типизированные схемы данных
- **Роль:** Единая система описания структур данных через Pydantic v2. **Независимый, без зависимостей от других модулей фреймворка.**
- **Ключевые классы:**
  - `SchemaBase(SchemaMixin)` — Базовый класс для всех схем (регистров). Поля описываются через `Annotated[type, FieldMeta(...)]`
  - `FieldMeta` — Дескриптор с метаданными (описание, min/max, unit, routing, access_level)
  - `FieldRouting` — Маршрутизация поля через каналы (channel, priority, transform)
  - `SchemaRegistry` — Реестр схем для runtime-регистрации и получения по имени
  - `RegistersContainer` — Контейнер множества экземпляров схем с diff/snapshot для эффективной синхронизации
  - `DataConverter` — Конвертация между dict/JSON/YAML
  - `FileStorage` — Сохранение/загрузка в JSON

**Концепция:** Каждый процесс описывает свои данные через `ProcessData(SchemaBase)`. При запуске система автоматически собирает "каталог" всех процессов и их данных.

**Формула:** Schema = "чертёж", Instance = "живой объект по чертежу"

---

#### 3. **message_module** — Единый язык межпроцессного общения
- **Роль:** Типизированный протокол для всех сообщений между процессами. **Dict at Boundary: на границе процессов — dict, внутри — объекты.**
- **Ключевые классы:**
  - `Message` — Основной класс сообщения с 9 типами (GENERAL, COMMAND, LOG, SYSTEM, BROADCAST, DATA, REQUEST, RESPONSE, EVENT)
  - `MessageAdapter` — Рекомендуемый способ создания сообщений (фиксирует `sender` один раз)
  - `MessageType` — Enum с типами
  - `MessageSchema` — Pydantic-схемы для опциональной валидации

**Типы сообщений:**

| Тип | Пример | Кто слушает |
|---|---|---|
| `COMMAND` | `msg.command(targets=["worker"], command="set_fps", args={"fps": 30})` | CommandManager в целевом процессе |
| `LOG` | `msg.log("error", "connection failed")` | LoggerManager (глобальный) |
| `REQUEST` / `RESPONSE` | Синхронный запрос с correlation_id | Паттерн request/response |
| `EVENT` | Pub/sub событие | Зарегистрированные handlers |
| `BROADCAST` | Рассылка всем кроме... | Все процессы |

---

### Слой 2: Инфраструктура (Infrastructure)

Служебные менеджеры, которые поддерживают работу фреймворка:

#### 4. **logger_module** — Централизованное логирование
- **Роль:** Собирать логи от всех менеджеров (через `ObservableMixin`) и от дочерних процессов (через Router) и записывать в каналы (файлы, консоль, HTTP).
- **Ключевые классы:**
  - `LoggerManager(ChannelRoutingManager)` — Менеджер логирования с scope-based routing (SYSTEM, BUSINESS, PERFORMANCE, AUDIT, SECURITY, DEBUG)
  - `LogConfig` — Конфигурация каналов, батчинг, уровни
  - `ILogChannel` — Интерфейс для каналов (FileChannel, ConsoleChannel, HttpChannel, кастомные)
  - `BatchBuffer` — Батчинг логов для эффективности (группирует по 100 штук или по времени)

**Особенность:** Логи от всех менеджеров идут через `_log_info()` → LoggerManager.info(). Очень удобно для кросс-утечек отладки.

---

#### 5. **error_module** — Специализированное управление ошибками
- **Роль:** Наследник LoggerManager. Добавляет level-based routing (CRITICAL/ERROR/WARNING в разные файлы).
- **Ключевые классы:**
  - `ErrorManager(LoggerManager)` — Переопределяет `log()` для level-based routing вместо scope-based
  - `ErrorManagerConfig` — Конфиг с путями для critical.log, errors.log, warnings.log

**Использование:** `self._track_error(exc, context={"method": "process"})` → ErrorManager.log_exception()

---

#### 6. **config_module** — Runtime управление конфигурациями

- **Роль:** Runtime API для работы с конфигурациями. **Тонкая обёртка над data_schema_module** + управление жизненным циклом конфигов.
- **Ключевые классы:**
  - `ConfigManager(BaseManager, ObservableMixin, IConfigManager)` — Менеджер множества конфигов (создание, получение, удаление, синхронизация)
  - `Config` — Runtime контейнер одной конфигурации (~160 строк)
  - `ConfigSection` — View на часть конфигурации (вложенные ключи через точку)
  - `ConfigManagerConfig(SchemaBase)` — Конфиг самого менеджера через @register_schema

**Особенности:**
- **Dot-notation:** `config.get("database.host")`, `config.set("database.port", 5432)`
- **Подписки на изменения:** `@config.subscribe(key="debug")` или `config.subscribe(callback, key="*")`
- **Env-fallback:** если ключа нет, ищет в переменных окружения `{env_prefix}_{KEY}`
- **Синхронизация:** `cm.sync_config("app")` ← ConfigStore (Dict at Boundary), `cm.load_config_from_storage("app")`
- **Потокобезопасность:** RLock для всех операций
- **49 тестов:** Config, ConfigManager, ConfigSection полностью покрыты

**Интеграция:** С data_schema_module (merge_with_defaults, SchemaBase) и shared_resources_module (ConfigStore).

**ADR-023:** config_module — тонкая обёртка над data_schema_module (2026-03-15). Валидация и сериализация делегируются data_schema_module, config_module отвечает за runtime доступ и подписки.

---

#### 7. **console_module** — Управление терминальным I/O
- **Роль:** ConsoleManager управляет терминальным вводом-выводом процесса. Интеграция с LoggerManager (ConsoleLogChannel) и CommandManager для интерактивного управления.
- **Ключевые классы:**
  - `ConsoleManager(BaseManager, ObservableMixin)` — Менеджер консоли
  - `IPlatformConsole` — Интерфейс платформенной консоли (WindowsConsole, UnixConsole)
  - `ConsoleAdapter` — Адаптер для доступа из ProcessModule (`process.console_adapter`)
  - `ConsoleLogChannel` — Канал логирования в консоль
- **Три уровня:** пассивный (только вывод), активный (ввод+вывод), God Mode (интерактивное управление)
- **Кроссплатформенность:** WindowsConsole (Windows), UnixConsole (Linux/macOS)

---

#### 8. **shared_resources_module** — Межпроцессные ресурсы
- **Роль:** "Записная книжка" для создания и хранения Queue, Event, SharedMemory. **Pickle-safe** — передаётся в дочерние процессы напрямую.
- **Ключевые классы:**
  - `SharedResourcesManager` — Фасад (создание очередей, событий, MemoryManager)
  - `ProcessData` — Контейнер ресурсов одного процесса (queues, events, custom)
  - `QueueRegistry` — Создание и управление Queue
  - `EventManager` — Создание и управление Event
  - `MemoryManager` — Создание SharedMemory по именам (pickle-safe)
  - `ConfigStore` — Хранение конфигов всех процессов (отдельно от ProcessData)

**Особенность:** Всё pickle-safe. После unpickle в дочернем процессе вызывается `srm.reinitialize_in_child()`.

---

#### 9. **registers_module** — Runtime реестр экземпляров схем
- **Роль:** Контейнер живых экземпляров схем (`SchemaBase`) с маршрутизацией по каналам.
- **Ключевые классы:**
  - `RegistersContainer` — Контейнер экземпляров нескольких схем
  - Методы diff/snapshot для эффективной синхронизации

**Отличие от data_schema_module:** data_schema — статические чертежи; registers — живые объекты по чертежам.

---

### Слой 3: Коммуникация (Communication)

Менеджеры для обмена сообщениями и командами:

#### 10. **router_module** — Маршрутизация сообщений между процессами
- **Роль:** Единая точка входа-выхода для всех сообщений. Каждый процесс имеет один `RouterManager`.
- **Ключевые классы:**
  - `RouterManager(ChannelRoutingManager)` — Фасад (send, receive, register_channel, register_message_handler)
  - `AsyncSender` — PriorityQueue + фоновый поток для асинхронной отправки (с middleware pipeline)
  - `AsyncReceiver` — Фоновый поток приёма с fire-and-forget callback-ами
  - `IMessageChannel` — Интерфейс каналов (QueueChannel, SocketChannel, кастомные)

**Поток сообщения:**
```
Process A: msg.command(...) → msg.to_dict() ──→ RouterManager.send()
                                                    ↓
                              AsyncSender → middleware → resolve_channel → IMessageChannel.send()
                                                    ↓
                              Queue / Socket / HTTP
                                                    ↓
Process B: AsyncReceiver ← poll_all() ← middleware ← message_dispatcher (callbacks)
                ↓
          Message.from_dict() ← restored object
```

---

#### 11. **dispatch_module** — Диспетчеризация входящих сообщений внутри процесса
- **Роль:** Маршрутизация входящих сообщений к обработчикам на основе 4 стратегий.
- **Ключевые классы:**
  - `Dispatcher(BaseManager, ObservableMixin)` — Регистрирует обработчики, вызывает `dispatch(message)`
  - 4 стратегии маршрутизации:
    1. `EXACT_MATCH` — O(1) lookup по ключу (быстро)
    2. `FALLBACK_MATCH` — Несколько обработчиков, выбор по efficiency
    3. `PATTERN_MATCH` — Regex для гибкости
    4. `CHAIN_MATCH` — Сценарии (цепочки обработчиков)
  - `ScenarioBuilder` — Fluent API для построения сценариев

**Использование:**
```python
dispatcher.register_handler("process_frame", lambda data: process_frame(data))
result = dispatcher.dispatch({"command": "process_frame", "data": frame})
```

---

#### 12. **command_module** — Управление командами
- **Роль:** Тонкая обёртка над `dispatch_module` с терминологией команд.
- **Ключевые классы:**
  - `CommandManager(BaseManager, ObservableMixin)` — Фасад (register_command, handle_command)

**Суть:** CommandManager = Dispatcher, только `register_command` вместо `register_handler`.

---

### Слой 4: Процессы (Process)

Управление отдельными процессами:

#### 13. **worker_module** — Управление потоками внутри процесса
- **Роль:** Централизованное создание, запуск, остановка потоков (threads) внутри каждого процесса.
- **Ключевые классы:**
  - `WorkerManager(BaseManager, ObservableMixin)` — Менеджер потоков
  - `ThreadConfig` — Конфиг потока (приоритет, тип, режим)
  - `WorkerType` — Enum (APPLICATION, SYSTEM, BACKGROUND)
  - `ExecutionMode` — Enum (LOOP для циклических, TASK для одноразовых)

**Использование:**
```python
def my_worker(stop_event, pause_event):
    while not stop_event.is_set():
        if pause_event.is_set():
            time.sleep(0.05)
            continue
        # обработка

config = ThreadConfig(priority=ThreadPriority.NORMAL)
manager.create_worker("worker_1", my_worker, config, auto_start=True)
```

---

#### 14. **process_module** — Базовый класс процесса
- **Роль:** Предоставить `ProcessModule` — базовый класс для всех пользовательских процессов.
- **Ключевые классы:**
  - `ProcessModule(BaseManager, ObservableMixin)` — ABC с методами `initialize()`, `run()`, `shutdown()`
  - Встроенные менеджеры: RouterManager, CommandManager, WorkerManager, LoggerManager
  - Методы: `should_stop()`, `log_info()`, `send_message()`, `create_worker()`

**Использование:**
```python
class MyProcess(ProcessModule):
    def initialize(self) -> bool:
        self.log_info("Starting...")
        return True
    
    def run(self):
        while not self.should_stop():
            self.log_info("Working...")
            time.sleep(1)
    
    def shutdown(self) -> bool:
        self.log_info("Stopping...")
        return True
```

---

### Слой 5: Оркестрация (Orchestration)

#### 15. **process_manager_module** — Оркестратор системы
- **Роль:** Запуск, управление, мониторинг всех дочерних процессов. Единая точка входа.
- **Ключевые классы:**
  - `SystemLauncher` — Фасад (Dict at Boundary). Принимает `List[(name, process_dict)]`, нормализует, запускает
  - `ProcessSpawner` — Запуск процессов ОС с обработкой сигналов (SIGTERM, SIGINT)
  - `ProcessManagerProcess` — Оркестратор-процесс (composite из ProcessRegistry + ProcessMonitor + EventManager)
  - `ProcessRegistry` — Реестр всех процессов с lifecycle (START → RUNNING → STOPPING → STOPPED)
  - `ProcessMonitor` — Мониторинг состояний процессов (broadcast при изменениях)
  - `ProcessPriority` — Приоритеты запуска (с Windows-specific реализацией)
  - `ProcessStatus` — Enum состояний процесса

**Поток запуска:**
```
SystemLauncher.run()
    ↓
ProcessSpawner.launch_orchestrator() ← создаёт ProcessManagerProcess
    ↓
ProcessManagerProcess.initialize()
    ├─ ProcessRegistry.register_all(processes)
    ├─ SharedResourcesManager.register_process() для каждого
    └─ Запуск всех дочерних процессов через ProcessRegistry.start_all()
    ↓
AsyncReceiver: мониторит состояния, обрабатывает команды
    ↓
При SIGTERM/SIGINT: graceful_shutdown()
    ├─ Остановка всех процессов (stop_event → join → terminate → kill)
    └─ Синхронизация состояния
```

---

## Принципы архитектуры

### 1. **Модульность (Modularity)**

15 независимых модулей, каждый может быть заменён или расширен без изменения других.

```
Плохо: base_manager → logger_module → config_module → ...
       (цепочка зависимостей, если один сломается — сломаются все)

Хорошо: base_manager → {logger_module, config_module, router_module}
        (звезда: все зависят от base, но не от друг друга)
```

### 2. **Dict at Boundary**

На границе процессов передаются только простые типы (`dict`, `list`, `str`, `int`). Pydantic модели используются только внутри процесса.

```python
# Отправка между процессами
msg = msg.to_dict()  # Message → dict
# Получение
msg = Message.from_dict(raw_dict)  # dict → Message (восстановлен)
```

**Почему:** Pydantic модели содержат методы (не сериализуемые в pickle), что ломает multiprocessing на Windows (spawn mode).

### 3. **BaseManager + ObservableMixin**

Все менеджеры наследуют этот паттерн:

```python
class MyManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={'logger': logger} if logger else {},
        )
    
    def initialize(self) -> bool:
        self._log_info("Starting")  # автоматически пойдёт в LoggerManager
        return True
```

**Результат:** Все менеджеры логируют одинаково. Легко подменить логгер на сокет или БД.

### 4. **ChannelRoutingManager**

RouterManager, LoggerManager, ErrorManager используют один паттерн:

```
ChannelRoutingManager (базовый)
├─ _channel_registry (thread-safe)
├─ _dispatcher (маршрутизация по ключу)
├─ buffer_strategy (батчинг, async sender)
└─ normalize_config() (Dict at Boundary)
    ↓
RouterManager → message channels (QueueChannel, SocketChannel)
LoggerManager → log channels (FileChannel, ConsoleChannel)
ErrorManager  → severity channels (errors.log, critical.log)
```

**Преимущество:** DRY. Исправление ошибки в registry применяется ко всем трём сразу.

### 5. **Graceful Shutdown**

При SIGTERM/SIGINT:

```
Signal handler (no sys.exit, just set stop_event)
    ↓
ProcessRegistry.stop_all(timeout=5)
    ├─ Каждому процессу: stop_event.set()
    ├─ Ждём join(timeout) — процесс сам завершается
    ├─ Если не завершился: terminate() — SIGTERM
    ├─ Снова join(timeout)
    └─ Если зависший: kill() — SIGKILL
    ↓
Log all stats
    ↓
Return gracefully (без sys.exit)
```

**Результат:** Даже при зависшем процессе система закроется за 5-10 сек, не потеряв данные.

### 6. **Explicit is Better Than Implicit**

- Все зависимости явно передаются в конструктор (не через globals)
- Нет автоматических pickle magic — `reinitialize_in_child()` вызывается явно
- Нет скрытого логирования — `self._log_info()` явно видит, что логирует
- Никаких sys.path.insert — импорты абсолютные

---

## Диаграмма зависимостей модулей

```
                    ┌─── base_manager
                    │
                    ├─── data_schema_module  (независимая, no deps)
                    │
                    ├─── message_module
                    │
                    ▼
        ┌────────────────────────────────────┐
        │  logger_module (BaseManager + CRM)  │
        └────────────────────────────────────┘
                    │
                    ▼
        ┌────────────────────────────────────┐
        │  error_module (extends logger)     │
        └────────────────────────────────────┘
        
        ┌────────────────────────────────────┐
        │  config_module (BaseManager)       │
        └────────────────────────────────────┘
        
        ┌────────────────────────────────────┐
        │  console_module (BaseManager)      │
        │  IPlatformConsole, ConsoleAdapter  │
        └────────────────────────────────────┘
        
        ┌────────────────────────────────────┐
        │  shared_resources_module (pickup-safe) │
        └────────────────────────────────────┘
        
        ┌────────────────────────────────────┐
        │  registers_module (data schema instances) │
        └────────────────────────────────────┘
        
        ┌────────────────────────────────────┐
        │  router_module (CRM + AsyncSender) │
        │  + message_module                  │
        └────────────────────────────────────┘
        
        ┌────────────────────────────────────┐
        │  dispatch_module (4 strategies)    │
        └────────────────────────────────────┘
        
        ┌────────────────────────────────────┐
        │  command_module (wraps dispatch)   │
        └────────────────────────────────────┘
        
        ┌────────────────────────────────────┐
        │  worker_module (thread mgmt)       │
        └────────────────────────────────────┘
        
        ┌────────────────────────────────────┐
        │  process_module (ProcessModule)    │
        │  + router + command + worker + ... │
        └────────────────────────────────────┘
        
                    ▼
        ┌────────────────────────────────────┐
        │  process_manager_module            │
        │  (ProcessManagerProcess orchestrator) │
        │  + ProcessRegistry + Monitor        │
        └────────────────────────────────────┘
                    │
                    ▼
        ┌────────────────────────────────────┐
        │  SystemLauncher (entry point)      │
        │  Dict at Boundary                  │
        └────────────────────────────────────┘

Легенда:
  CRM = ChannelRoutingManager (базовый класс для менеджеров с каналами)
  Dict at Boundary = данные передаются только dict между процессами
```

---

## Жизненный цикл приложения

### Фаза 1: Конфигурация (Before Startup)

```python
# Пользователь определяет процессы
processes_config = [
    ("camera_process", {
        "class_path": "my_app.CameraProcess",
        "config": {"camera_id": 0, "fps": 30},
    }),
    ("detector_process", {
        "class_path": "my_app.DetectorProcess",
        "config": {"model_path": "model.pt"},
    }),
]

launcher = SystemLauncher(
    processes=processes_config,
    console_enabled=True,
    error_manager_config={...},
)
```

**Что происходит:**
- SystemLauncher нормализует конфиги через `merge_with_defaults(DEFAULT_PROCESS_SCHEMA)`
- Все конфиги становятся `dict` (Dict at Boundary)

### Фаза 2: Запуск (Startup)

```
launcher.run()
    ↓
ProcessSpawner.launch_orchestrator()
    ├─ Создаёт ProcessManagerProcess
    ├─ Передаёт SharedResourcesManager
    ├─ Устанавливает signal handler
    └─ Ждёт `wait()` на MainProcess
    ↓
ProcessManagerProcess.initialize()
    ├─ ProcessRegistry.register_all(processes)
    ├─ Для каждого процесса:
    │   ├─ SRM.register_process(name, config_dict)
    │   │   ├─ Создаёт очереди (system, data, commands)
    │   │   ├─ Создаёт события (stop_event, pause_event)
    │   │   └─ Сохраняет конфиг в ConfigStore
    │   └─ ProcessRegistry.start_process(name)
    │       ├─ fork() / spawn() новый Process
    │       └─ Вызывает run_process_function(name, srm, config)
    │
    └─ ProcessRegistry.start_all() — все процессы начинают работать
    ↓
run_process_function (в дочернем процессе)
    ├─ srm.reinitialize_in_child()  # восстановить ресурсы после pickle
    ├─ Загрузить класс процесса
    ├─ Создать экземпляр ProcessModule
    ├─ Вызвать process.initialize()
    ├─ Вызвать process.run() — основной цикл
    ├─ На stop_event: процесс выходит из run()
    └─ Вызвать process.shutdown()
```

### Фаза 3: Работа (Runtime)

Каждый процесс имеет:

```
┌────────────────────────────────────────┐
│  Process A                             │
│                                        │
│  ┌──────────────────────────────────┐ │
│  │ WorkerManager                    │ │
│  │ ├─ worker_1 (LOOP) — обработка  │ │
│  │ └─ worker_2 (LOOP) — отправка   │ │
│  └──────────────────────────────────┘ │
│          │                             │
│  ┌───────▼──────────────────────────┐ │
│  │ RouterManager                    │ │
│  │ ├─ send(msg) ← from workers     │ │
│  │ ├─ receive() ← AsyncReceiver    │ │
│  │ └─ register_message_handler()   │ │
│  └──────────────────────────────────┘ │
│          │                             │
│  ┌───────▼──────────────────────────┐ │
│  │ CommandManager                   │ │
│  │ ├─ handle_command(msg)          │ │
│  │ └─ register_command("ping", ...) │ │
│  └──────────────────────────────────┘ │
│                                        │
│  process.run() loop:                   │
│  1. worker_1 обрабатывает данные      │
│  2. worker_2 отправляет сообщения    │
│  3. RouterManager получает команды   │
│  4. CommandManager вызывает handler   │
│  5. back to step 1                    │
│                                        │
└────────────────────────────────────────┘
        │
        │ msg.to_dict()
        ▼
┌────────────────────────────────────────┐
│ Process B                              │
│  (аналогично)                          │
└────────────────────────────────────────┘
```

**Обмен сообщениями между процессами:**

```
Process A (worker_1):
    msg = adapter.command(
        targets=["detector_process"],
        command="detect_objects",
        args={"frame": frame},
    )
    router.send(msg)
        ↓
    msg.to_dict() → Queue (shared_resources)
        ↓
Process B (RouterManager):
    receive() → Message.from_dict(raw_dict)
        ↓
    message_dispatcher([callback1, callback2, ...])
        ↓
    CommandManager.handle_command(msg)
        ↓
    handler = registry.get("detect_objects")
        ↓
    result = handler(msg["args"])
        ↓
    Response: msg.response(targets=["camera_process"], result=result)
```

### Фаза 4: Остановка (Shutdown)

```
Signal: SIGTERM / SIGINT / Ctrl+C
    ↓
ProcessSpawner._signal_handler()
    ├─ set stop_event (НЕ sys.exit!)
    └─ return (естественное завершение)
    ↓
ProcessSpawner.wait() возвращает управление
    ↓
ProcessRegistry.stop_all(timeout=5)
    ├─ Для каждого процесса:
    │   ├─ process_data.stop_event.set()
    │   ├─ join(timeout=5)  — ждём завершения
    │   ├─ if alive: terminate() — SIGTERM
    │   ├─ join(timeout=5)
    │   └─ if alive: kill() — SIGKILL
    └─ Все процессы завершены
    ↓
ProcessManagerProcess.shutdown()
    ├─ RouterManager.shutdown()
    ├─ LoggerManager.flush()
    └─ SRM.shutdown()
    ↓
Log: "Application stopped gracefully"
    ↓
Exit code 0
```

---

## Паттерны и принципы

### Паттерн 1: Manager Initialization

Все менеджеры инициализируются одинаково:

```python
manager = MyManager(
    manager_name="name",
    logger=logger_manager,     # опционально
    error_manager=error_manager,  # опционально
    config={...},              # или None/RegisterBase
)

manager.initialize()   # → вернуть bool
# ... работа ...
manager.shutdown()     # → вернуть bool
```

### Паттерн 2: Observable Logging

Вместо прямого использования LoggerManager:

```python
# Плохо:
if self.logger_manager:
    self.logger_manager.info("message")

# Хорошо (автоматическая интеграция):
self._log_info("message")  # → внутри ObservableMixin
```

### Паттерн 3: Request-Response

Для синхронных запросов между процессами:

```python
# Отправитель
req = adapter.request(
    targets=["service"],
    request_type="get_data",
    query={"key": "value"},
    timeout=5.0,
)
correlation_id = req.id
router.send(req)
# ... ждём ответ в callback ...

# Получатель
def handle_request(msg):
    if msg.type == MessageType.REQUEST:
        result = process_query(msg.get("query"))
        reply = adapter.response(
            targets=[msg.sender],
            request_id=msg.id,  # correlation_id!
            result=result,
        )
        router.send(reply)

# Отправитель получает результат
def handle_response(msg):
    if msg.get("request_id") == correlation_id:
        print(msg.get("result"))
```

### Паттерн 4: Graceful Worker Stop

Каждый worker проверяет `stop_event`:

```python
def my_worker(stop_event, pause_event):
    while not stop_event.is_set():  # ← check stop
        if pause_event.is_set():    # ← check pause
            time.sleep(0.05)
            continue
        
        # work
        process_data()
        time.sleep(1)
    
    # cleanup (optional)
    cleanup()
```

### Паттерн 5: Adapter Pattern

Каждый модуль может предоставить адаптер для интеграции:

```
message_module → MessageAdapter (helper для создания сообщений)
router_module   → RouterAdapter (helper для процесса)
command_module  → CommandAdapter (helper для процесса)
data_schema_module → ISchemaAdapter (для конвертации схем)
```

**Адаптер** — это не класс, а просто помощник для удобства работы с модулем.

---

## Ключевые архитектурные решения

Все решения задокументированы в `DECISIONS.md`. Основные:

### ADR-001: ObservableMixin остаётся
Связывает logger, stats, error через прокси-методы. Удаление потребует ручного прокидывания везде.

### ADR-008: Dict at Boundary
На границе процессов — `dict`. Внутри — Pydantic. Гарантирует pickle-совместимость на Windows spawn.

### ADR-013: ChannelRoutingManager
Базовый класс для RouterManager, LoggerManager, ErrorManager. DRY — исправление ошибки применяется ко всем сразу.

### ADR-021: Прямой pickle SRM
SharedResourcesManager pickle-ируется напрямую вместе с Queue/Event. Исключает дублирование кода создания ресурсов.

**Все остальные решения в `DECISIONS.md`**

---

## Как всё работает вместе

### Сценарий: Обработка видео с детекцией

```python
# 1. Определяем процессы
processes = [
    ("camera", {
        "class_path": "app.CameraProcess",
        "config": {"fps": 30},
    }),
    ("detector", {
        "class_path": "app.DetectorProcess",
        "config": {"model": "yolo.pt"},
    }),
    ("display", {
        "class_path": "app.DisplayProcess",
        "config": {},
    }),
]

# 2. Запускаем
launcher = SystemLauncher(processes=processes)
launcher.run()  # ← blocking until Ctrl+C
```

### Процесс CameraProcess

```python
class CameraProcess(ProcessModule):
    def initialize(self):
        self.log_info("Camera initializing")
        
        # Создать worker для захвата кадров
        self.create_worker(
            "capture",
            self._capture_worker,
            ThreadConfig(execution_mode=ExecutionMode.LOOP),
            auto_start=True
        )
        return True
    
    def _capture_worker(self, stop_event, pause_event):
        cap = cv2.VideoCapture(0)
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue
            
            ret, frame = cap.read()
            if ret:
                # Отправить кадр детектору
                msg = self.msg.command(
                    targets=["detector"],
                    command="detect",
                    args={"frame": frame.tobytes()},
                )
                self.router.send(msg)
    
    def shutdown(self):
        self.log_info("Camera shutting down")
        return True
```

### Процесс DetectorProcess

```python
class DetectorProcess(ProcessModule):
    def initialize(self):
        self.log_info("Detector initializing")
        self.model = load_model("yolo.pt")
        
        # Зарегистрировать обработчик команды
        self.command_manager.register_command(
            "detect",
            self._detect_handler
        )
        return True
    
    def _detect_handler(self, msg_data):
        frame_bytes = msg_data.get("frame")
        frame = np.frombuffer(frame_bytes, dtype=np.uint8)
        
        # Детекция
        results = self.model(frame)
        
        # Отправить результат в display
        msg = self.msg.command(
            targets=["display"],
            command="show_detections",
            args={"detections": results.json()},
        )
        self.router.send(msg)
        
        return {"status": "ok"}
    
    def shutdown(self):
        self.log_info("Detector shutting down")
        return True
```

### Процесс DisplayProcess

```python
class DisplayProcess(ProcessModule):
    def initialize(self):
        self.log_info("Display initializing")
        
        self.command_manager.register_command(
            "show_detections",
            self._show_handler
        )
        return True
    
    def _show_handler(self, msg_data):
        detections = msg_data.get("detections")
        # Отобразить на экране
        print(f"Detected: {detections}")
        return {"displayed": True}
    
    def shutdown(self):
        self.log_info("Display shutting down")
        return True
```

### Поток выполнения

```
1. ProcessManagerProcess запущен
   ├─ создаёт CameraProcess, DetectorProcess, DisplayProcess
   └─ SRM регистрирует очереди для каждого

2. CameraProcess.initialize()
   ├─ создаёт worker "capture"
   └─ worker начинает читать видео

3. CameraProcess._capture_worker
   ├─ захватывает frame
   ├─ создаёт сообщение COMMAND: detect
   └─ отправляет через RouterManager в очередь DetectorProcess

4. DetectorProcess.AsyncReceiver (фоновый поток)
   ├─ получает сообщение из очереди
   ├─ вызывает CommandManager.dispatch()
   ├─ находит обработчик "detect"
   └─ вызывает DetectorProcess._detect_handler()

5. DetectorProcess._detect_handler()
   ├─ запускает YOLO
   ├─ создаёт сообщение COMMAND: show_detections
   └─ отправляет в очередь DisplayProcess

6. DisplayProcess (аналогично шагу 4-5)
   ├─ получает сообщение
   ├─ показывает результаты

7. Ctrl+C
   ├─ ProcessSpawner получает SIGINT
   ├─ устанавливает stop_event для всех процессов
   ├─ каждый process.run() выходит из цикла
   ├─ процессы вызывают shutdown()
   └─ приложение завершает работу gracefully
```

---

## Быстрый старт для разработчиков

### 1. Создать простой процесс

```python
# my_app.py
from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.worker_module import (
    ThreadConfig, ExecutionMode
)

class HelloProcess(ProcessModule):
    def initialize(self) -> bool:
        self.log_info("Hello Process started")
        
        # Создать worker для работы
        def work(stop_event, pause_event):
            counter = 0
            while not stop_event.is_set():
                counter += 1
                self.log_info(f"Iteration {counter}")
                time.sleep(1)
        
        self.create_worker(
            "work_1",
            work,
            ThreadConfig(execution_mode=ExecutionMode.LOOP),
            auto_start=True,
        )
        return True
    
    def shutdown(self) -> bool:
        self.log_info("Hello Process stopped")
        return True
```

### 2. Запустить

```python
from multiprocess_framework.refactored.modules.process_manager_module import SystemLauncher

launcher = SystemLauncher(
    processes=[
        ("hello", {
            "class_path": "my_app.HelloProcess",
            "config": {},
        }),
    ]
)

launcher.run()  # блокирует до Ctrl+C
```

### 3. Обмен сообщениями

```python
# process_a.py
class ProcessA(ProcessModule):
    def initialize(self):
        self.command_manager.register_command("ping", self._ping_handler)
        return True
    
    def _ping_handler(self, data):
        self.log_info("Got ping!")
        return {"pong": True}

# process_b.py
class ProcessB(ProcessModule):
    def initialize(self):
        def send_ping(stop_event, pause_event):
            msg = self.msg.command(
                targets=["process_a"],
                command="ping",
            )
            self.router.send(msg)
            time.sleep(1)
        
        self.create_worker("pinger", send_ping, ThreadConfig(), auto_start=True)
        return True
```

---

## FAQ и anti-patterns

### Q: Как добавить новый менеджер?

A: Наследуй `BaseManager + ObservableMixin`:

```python
class MyManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={'logger': logger} if logger else {},
        )
    
    def initialize(self) -> bool:
        self._log_info("Initializing")
        return True
    
    def shutdown(self) -> bool:
        return True
```

---

### Q: Зачем нужны `msg.to_dict()` и `Message.from_dict()`?

A: Pydantic модели не всегда сериализуются в `multiprocessing.Queue` на Windows. `dict` гарантированно сериализуется. Это **Dict at Boundary** — на границе процессов только примитивы.

---

### Q: Как правильно остановить процесс?

A: **Плохо:**
```python
# ❌ sys.exit() — процесс убивается неожиданно
sys.exit(0)
```

**Хорошо:**
```python
# ✅ check stop_event в цикле
def worker(stop_event, pause_event):
    while not stop_event.is_set():  # ← graceful
        work()
```

---

### Q: Почему нельзя использовать глобальные переменные?

A: При `fork()` они копируются в дочерний процесс. Изменение в дочернем не видно родителю. Вместо этого используй `shared_resources_module` (Queue, Event, SharedMemory).

---

### Q: Как debug-ить сообщения между процессами?

A: Включи логирование RouterManager:

```python
logger = LoggerManager(...)
logger.initialize()

router = RouterManager(
    manager_name="router",
    logger=logger,
)
router.initialize()

# Все send/receive будут залогированы
```

---

### Q: Anti-pattern: Использовать ObservableMixin без менеджеров

❌ **Плохо:**
```python
class MyManager(BaseManager, ObservableMixin):
    def __init__(self):
        ObservableMixin.__init__(self, managers={})  # пусто!
    
    def work(self):
        self._log_info("info")  # не будет залогировано (нет логгера)
```

✅ **Хорошо:**
```python
class MyManager(BaseManager, ObservableMixin):
    def __init__(self, logger):
        ObservableMixin.__init__(self, managers={'logger': logger})
    
    def work(self):
        self._log_info("info")  # ✓ залогировано
```

---

### Q: Anti-pattern: Игнорировать `initialize()` / `shutdown()`

❌ **Плохо:**
```python
process = MyProcess("name")
process.run()  # не инициализирован! ресурсы утекают
```

✅ **Хорошо:**
```python
process = MyProcess("name")
try:
    if process.initialize():
        process.run()
finally:
    process.shutdown()
```

---

### Q: Anti-pattern: Передавать Pydantic модели между процессами

❌ **Плохо:**
```python
msg = MyModel(field1=value1)
queue.put(msg)  # ломается на Windows!
```

✅ **Хорошо:**
```python
msg_dict = msg.model_dump()  # → dict
queue.put(msg_dict)  # ✓ pickle-safe

# На другой стороне
msg = MyModel(**queue.get())
```

---

## Резюме

**Multiprocess Framework** — это архитектура для построения надёжных многопроцессных приложений. Ключевые черты:

✅ **Модульность:** 15 независимых модулей  
✅ **Type-safe:** Pydantic + Protocol для описания данных  
✅ **Graceful shutdown:** На сигнал даёт время на корректное завершение  
✅ **Observable:** Все менеджеры логируют через единый интерфейс  
✅ **Scalable:** Добавить новый процесс/менеджер — просто наследовать классы  
✅ **Production-ready:** Покрыто тестами, документировано, проверено на ошибки

**Где использовать:**
- Обработка видео / компьютерное зрение
- IoT приложения
- Системы мониторинга
- Микросервисные приложения на одной машине

**Где НЕ использовать:**
- Простые скрипты (для них достаточно `multiprocessing` + `logging`)
- Распределённые системы (для них используй Docker + Kubernetes)

---

## Полезные ссылки

- `DECISIONS.md` — архитектурные решения (ADR)
- `modules/*/README.md` — документация каждого модуля
- `modules/*/STATUS.md` — статус рефакторинга
- `modules/*/tests/` — примеры использования (в тестах)
- `multiprocess_prototype/main.py` — полный пример приложения

---

**Разработано в 2026 году | Статус: Production Ready**
