# Framework Architecture — Visual Reference

**Этот документ содержит диаграммы и таблицы для быстрого понимания архитектуры.**

---

## 1. Иерархия классов: Наследование

```
Pydantic BaseModel
    │
    ├─ SchemaBase (data_schema_module)
    │   │
    │   └─ RegisterBase (registers_module, для config)
    │       ├─ ChannelRoutingConfig (channel_routing_module)
    │       │   ├─ LogConfig (logger_module)
    │       │   └─ ErrorManagerConfig (error_module)
    │       │
    │       └─ ThreadConfig (worker_module)
    │
    └─ Message (message_module)
        ├─ CommandMessage
        ├─ LogMessage
        └─ ...

────────────────────────────────────────────

BaseManager (base_manager)
    │
    ├─ ObservableMixin ────────┐
    │                          │
    ├─ BaseAdapter            │
    │                          │
    ├─ ChannelRoutingManager ◄─┤ (channel_routing_module)
    │   │                      │
    │   ├─ RouterManager       │ (router_module)
    │   ├─ LoggerManager       │ (logger_module)
    │   │   └─ ErrorManager    │ (error_module)
    │   │                      │
    │   ├─ Dispatcher          │ (dispatch_module)
    │   │   └─ CommandManager  │ (command_module)
    │   │                      │
    │   ├─ ConfigManager       │ (config_module)
    │   ├─ ConsoleManager      │ (console_module)
    │   └─ WorkerManager       │ (worker_module)
    │                          │
    └─ ProcessModule ◄─────────┘ (process_module)
        │
        ├─ logger_manager ─────────┐
        ├─ router_manager          │
        ├─ command_manager         ├─ встроено
        ├─ worker_manager          │
        └─ config_manager ─────────┘
        
ProcessManagerProcess ◄────────────┐
    │                              │
    ├─ ProcessRegistry             │
    ├─ ProcessMonitor              ├─ process_manager_module
    └─ CommandManager ──────────────┘
```

---

## 2. Слои архитектуры (Layer Cake)

```
┌──────────────────────────────────────────────────────────┐
│ Application Layer (user code)                            │
│ ──────────────────────────────────────────────────────   │
│ class MyProcess(ProcessModule):                          │
│   def run(self): ...                                     │
└──────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────┐
│ Orchestration Layer                                      │
│ ──────────────────────────────────────────────────────   │
│ SystemLauncher → ProcessSpawner → ProcessManagerProcess  │
│                                   ├─ ProcessRegistry     │
│                                   ├─ ProcessMonitor      │
│                                   └─ SharedResourcesMgr   │
└──────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────┐
│ Process Layer                                            │
│ ──────────────────────────────────────────────────────   │
│ ProcessModule (runs in each process)                     │
│ ├─ RouterManager (communication)                         │
│ ├─ CommandManager (message dispatching)                  │
│ ├─ WorkerManager (thread management)                     │
│ ├─ LoggerManager (logging)                              │
│ └─ ConfigManager (configuration)                         │
└──────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────┐
│ Communication Layer                                      │
│ ──────────────────────────────────────────────────────   │
│ RouterManager (send/receive)                            │
│   ├─ AsyncSender (buffered async send)                  │
│   ├─ AsyncReceiver (background receive)                 │
│   └─ IMessageChannel (QueueChannel, SocketChannel, ...) │
│                                                          │
│ CommandManager (dispatch commands)                      │
│   └─ Dispatcher (4 strategies: EXACT, FALLBACK, etc)    │
└──────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────┐
│ Infrastructure Layer                                     │
│ ──────────────────────────────────────────────────────   │
│ LoggerManager / ErrorManager (logging & error tracking)  │
│ ConfigManager (configuration management)                │
│ ConsoleManager (terminal I/O, 3 levels, cross-platform)  │
│ SharedResourcesManager (inter-process resources)        │
│   ├─ ProcessData (queues, events, memory)               │
│   ├─ QueueRegistry (queue creation)                     │
│   ├─ EventManager (event creation)                      │
│   └─ MemoryManager (shared memory)                      │
└──────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────┐
│ Foundation Layer                                         │
│ ──────────────────────────────────────────────────────   │
│ BaseManager (lifecycle: init/shutdown)                  │
│ ObservableMixin (logging integration)                   │
│ message_module (message types & protocols)              │
│ data_schema_module (typed data structures)              │
│                                                          │
│ Channel Routing Module (base for all routers)           │
│   ├─ ChannelRegistry (thread-safe)                      │
│   ├─ Dispatcher (key-based routing)                     │
│   └─ BufferStrategy (batching/async)                    │
└──────────────────────────────────────────────────────────┘
```

---

## 3. Поток сообщения (Message Flow)

### A. Отправка сообщения (Send Path)

```
sender = process_a.msg          (MessageAdapter, sender="process_a")
    │
    ├─ msg = sender.command(    (создание сообщения)
    │     targets=["process_b"],
    │     command="process",
    │     args={...}
    │   )
    │
    └─ process_a.router.send(msg)
        │
        ├─ msg.to_dict()        (Dict at Boundary)
        │
        ├─ AsyncSender._queue.put(msg_dict, priority)  (в PriorityQueue)
        │
        └─ AsyncSender._worker_thread (фоновый поток)
            │
            ├─ msg_dict = _queue.get()
            │
            ├─ MiddlewarePipeline._apply_send_middleware()  (трансформация)
            │
            ├─ _resolve_channels(msg_dict)  (куда отправить)
            │
            └─ for channel in channels:
                │
                └─ channel.write(msg_dict)  (в очередь / сокет / HTTP)
                    │
                    └─ shared_resources.get_process_data("process_b").queues["system"].put(msg_dict)
```

### B. Получение сообщения (Receive Path)

```
AsyncReceiver._worker_thread (фоновый поток)
    │
    ├─ while not stop_event:
    │
    ├─ msgs = shared_resources.get_process_data(self_name).queues["system"].get_all()
    │     (poll all channels, non-blocking)
    │
    └─ for msg_dict in msgs:
        │
        ├─ MiddlewarePipeline._apply_recv_middleware()  (трансформация)
        │
        ├─ message_dispatcher.dispatch(msg_dict)
        │     (fire-and-forget callbacks, FIFO)
        │
        ├─ Message.from_dict(msg_dict)  (восстановление объекта)
        │
        └─ if type == COMMAND:
            │
            └─ CommandManager.handle_command(msg)
                │
                ├─ dispatcher.dispatch(msg, key_field="command", data_field="data")
                │
                └─ handler = registry.get(msg["command"])
                    │
                    └─ result = handler(msg["data"])
                        │
                        └─ (async, не блокирует receive)
```

---

## 4. Жизненный цикл процесса (Process Lifecycle)

```
START
  │
  ▼
┌─────────────────────────────────────────┐
│ 1. fork() / spawn()                    │
│    (создание дочернего процесса)       │
│    args: process_name, srm, config     │
└─────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────┐
│ 2. run_process_function()               │
│    (entry point дочернего процесса)     │
│                                        │
│    srm.reinitialize_in_child()         │
│    (восстановить Queue/Event/Memory)   │
└─────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────┐
│ 3. Загрузить класс процесса             │
│    _load_process_class(class_path)      │
│    (динамическая загрузка)              │
└─────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────┐
│ 4. process.initialize()                 │
│    (инициализация менеджеров)           │
│    ├─ RouterManager.initialize()        │
│    ├─ CommandManager.initialize()       │
│    ├─ WorkerManager.initialize()        │
│    ├─ LoggerManager.initialize()        │
│    └─ (пользовательская логика)        │
└─────────────────────────────────────────┘
  │
  ├─ if FAILED: → shutdown → exit(1)
  │
  ▼
┌─────────────────────────────────────────┐
│ 5. process.run()                        │
│    (основной цикл работы)               │
│    while not stop_event.is_set():       │
│        worker1.process()                │
│        worker2.process()                │
│        receive_messages()               │
│        handle_commands()                │
└─────────────────────────────────────────┘
  │
  ├─ stop_event.set() ← получили сигнал
  │
  ▼
┌─────────────────────────────────────────┐
│ 6. process.shutdown()                   │
│    (завершение менеджеров)              │
│    ├─ RouterManager.shutdown()          │
│    ├─ LoggerManager.flush()             │
│    ├─ WorkerManager.stop_all()          │
│    └─ (пользовательская логика)        │
└─────────────────────────────────────────┘
  │
  ▼
STOPPED (exit code 0 или 1)
```

---

## 5. Таблица модулей и их роли

| Модуль | Уровень | Наследует | Роль | Публичный API |
|--------|---------|----------|------|---------------|
| **base_manager** | Foundation | - | BaseManager, ObservableMixin | `BaseManager`, `ObservableMixin` |
| **data_schema_module** | Foundation | Pydantic | Типизированные схемы | `SchemaBase`, `FieldMeta`, `SchemaRegistry` |
| **message_module** | Foundation | Pydantic | Протокол сообщений | `Message`, `MessageAdapter`, `MessageType` |
| **logger_module** | Infra | BaseManager + ObservableMixin | Централизованное логирование | `LoggerManager`, `LogConfig`, `ILogChannel` |
| **error_module** | Infra | LoggerManager | Управление ошибками | `ErrorManager`, `ErrorManagerConfig` |
| **config_module** | Infra | BaseManager + ObservableMixin | Управление конфигурациями | `ConfigManager`, `Config`, `ConfigSection` |
| **console_module** | Infra | BaseManager + ObservableMixin | Терминальный I/O, 3 уровня, IPlatformConsole | `ConsoleManager`, `ConsoleAdapter`, `IPlatformConsole` |
| **shared_resources_module** | Infra | - | Межпроцессные ресурсы | `SharedResourcesManager`, `ProcessData` |
| **registers_module** | Infra | - | Runtime реестр схем | `RegistersContainer` |
| **router_module** | Comm | ChannelRoutingManager | Маршрутизация сообщений | `RouterManager`, `IMessageChannel` |
| **dispatch_module** | Comm | BaseManager + ObservableMixin | Диспетчеризация команд | `Dispatcher`, `DispatchStrategy` |
| **command_module** | Comm | BaseManager + ObservableMixin | Управление командами | `CommandManager` |
| **worker_module** | Process | BaseManager + ObservableMixin | Управление потоками | `WorkerManager`, `ThreadConfig` |
| **process_module** | Process | BaseManager + ObservableMixin | Базовый класс процесса | `ProcessModule`, `ProcessStatus` |
| **process_manager_module** | Orch | - | Оркестрация всех процессов | `SystemLauncher`, `ProcessRegistry`, `ProcessManagerProcess` |

---

## 6. Таблица типов сообщений

| Тип | MessageType | Обязательные поля | Обработчик | Пример |
|-----|-------------|------------------|-----------|--------|
| **GENERAL** | `general` | `content` | Любой callback | Произвольные данные |
| **COMMAND** | `command` | `command` | CommandManager | `msg.command(targets=[...], command="ping")` |
| **LOG** | `log` | `level`, `message` | LoggerManager | `msg.log("error", "Failed to connect")` |
| **SYSTEM** | `system` | `action` | ProcessManagerProcess | `msg.system(targets=[...], action="pause")` |
| **BROADCAST** | `broadcast` | `content` | Все процессы | `msg.broadcast(content=data, exclude=[...])` |
| **DATA** | `data` | `data_type` | Кастомный | Для больших данных |
| **REQUEST** | `request` | `request_type` | Кастомный handler | Синхронный запрос |
| **RESPONSE** | `response` | `request_id` | Callback по correlation_id | Ответ на REQUEST |
| **EVENT** | `event` | `event_type` | Event subscribers | Pub/Sub событие |

---

## 7. Таблица приоритетов AsyncSender

| Приоритет | Значение | Обработка | Пример |
|-----------|----------|-----------|--------|
| **URGENT** | `"urgent"` | Максимальный, обработка немедленно | Критическая ошибка |
| **HIGH** | `"high"` | Высокий приоритет | Важная команда |
| **NORMAL** | `"normal"` | Стандартный (по умолчанию) | Обычное сообщение |
| **LOW** | `"low"` | Низкий, фоновые задачи | Статистика, метрики |

---

## 8. Таблица Worker Modes

| Mode | ExecutionMode | Поведение | Финальный статус |
|------|---------------|-----------|-----------------|
| **LOOP** | `LOOP` | Циклический, пока `stop_event` | STOPPED |
| **TASK** | `TASK` | Одноразовый, выполняется один раз | COMPLETED |

---

## 9. Таблица Process States

```
┌──────────────┐
│   CREATED    │  (процесс создан, но не запущен)
└──────┬───────┘
       │ start()
       ▼
┌──────────────┐
│   STARTING   │  (процесс запускается)
└──────┬───────┘
       │ initialize() успешно
       ▼
┌──────────────┐
│   RUNNING    │  (процесс работает)
└──────┬───────┘
       │ stop() / shutdown signal
       ▼
┌──────────────┐
│  STOPPING    │  (процесс завершается)
└──────┬───────┘
       │ shutdown() завершился
       ▼
┌──────────────┐
│   STOPPED    │  (процесс остановлен)
└──────────────┘

Ошибки:
  ├─ CREATION_ERROR (при fork/spawn)
  ├─ INITIALIZATION_ERROR (при initialize())
  ├─ RUNTIME_ERROR (во время run())
  └─ SHUTDOWN_ERROR (при shutdown())
```

---

## 10. Таблица Scope-based Logging Levels

| Scope | Уровень | Файл | Описание | ObservableMixin метод |
|-------|---------|------|---------|---------------------|
| **DEBUG** | DEBUG | debug.log | Отладочная информация | `_log_debug()` |
| **BUSINESS** | INFO | app.log | Бизнес-логика (кадры, детекции) | `_log_info()` |
| **SYSTEM** | WARNING | system.log | Системные предупреждения | `_log_warning()` |
| **SYSTEM** | ERROR | system.log | Системные ошибки | `_log_error()` |
| **SYSTEM** | CRITICAL | critical.log | Критические ошибки | `_log_critical()` |
| **PERFORMANCE** | DEBUG | perf.log | Производительность (fps, timing) | (кастомный scope) |
| **AUDIT** | INFO | audit.log | Аудит (изменения конфига) | (кастомный scope) |
| **SECURITY** | WARNING | security.log | Безопасность (попытки доступа) | (кастомный scope) |

---

## 11. Dict at Boundary: Преобразования

```
┌─────────────────────────────────────┐
│ Внутри процесса (ProcessModule)      │
│ ├─ Message (объект)                 │
│ ├─ LogRecord (объект)               │
│ ├─ Config (Pydantic)                │
│ ├─ SchemaBase (Pydantic)            │
│ └─ Команды (типизированные)         │
└─────────────────────────────────────┘
         │ .to_dict()
         ▼ .model_dump()
┌─────────────────────────────────────┐
│ На границе процессов                 │
│ (в очередях, сокетах, файлах)      │
│ ├─ dict                             │
│ ├─ list                             │
│ ├─ str                              │
│ ├─ int, float, bool                 │
│ └─ bytes                            │
└─────────────────────────────────────┘
         │ Message.from_dict()
         ▼ ClassName(**dict)
┌─────────────────────────────────────┐
│ В другом процессе (процесс B)        │
│ ├─ Message (восстановлен)           │
│ ├─ LogRecord (восстановлен)         │
│ ├─ Config (восстановлен)            │
│ └─ (работаем с объектами)           │
└─────────────────────────────────────┘
```

---

## 12. Channel Resolution Flow

```
RouterManager.send(msg_dict)
    │
    ├─ Step 1: Проверить msg_dict["channel"] (явно указан?)
    │   └─ Да → O(1) lookup в _channel_registry
    │
    └─ Step 2: channel_dispatcher (маршрутизация)
        │
        ├─ Exact match: msg_dict["type"] == "command"
        │   └─ channels = ["command_channel"]
        │
        ├─ Pattern match: type matches regex
        │   └─ channels = ["pattern_channel_1", "pattern_channel_2"]
        │
        └─ Broadcast: type == "broadcast"
            └─ channels = [all except exclude]
    │
    └─ Результат: List[IMessageChannel]
        │
        └─ for channel in channels:
            └─ channel.write(msg_dict)
```

---

## 13. Initialization Order (Правильный порядок)

```
1. ProcessManagerProcess.__init__()
   └─ ProcessRegistry()
   └─ ProcessMonitor()
   └─ SharedResourcesManager()

2. ProcessManagerProcess.initialize()
   └─ RouterManager.initialize()
   └─ LoggerManager.initialize()
   └─ ErrorManager.initialize()
   └─ CommandManager.initialize()
   └─ ProcessRegistry.initialize()

3. ProcessRegistry.start_all()
   └─ Для каждого процесса:
      ├─ SRM.register_process(name, config)
      ├─ Process.spawn()
      └─ run_process_function()
         ├─ srm.reinitialize_in_child()
         ├─ load_process_class()
         ├─ process.initialize()
         ├─ process.run()
         └─ process.shutdown()

4. ProcessManagerProcess.shutdown()
   └─ ProcessRegistry.stop_all()
   └─ RouterManager.shutdown()
   └─ LoggerManager.shutdown()
   └─ SRM.shutdown()
```

---

## 14. Error Handling Strategy

```
┌──────────────────┐
│ Возникла ошибка  │
└─────────┬────────┘
          │
          ▼
┌──────────────────────────────────────────┐
│ ObservableMixin._track_error(exc)        │
│ (автоматически если регистрирован)      │
│ ErrorManager._handle_error()             │
└─────────┬────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────┐
│ ErrorManager.log_exception()             │
│ ├─ Форматировать traceback               │
│ ├─ Записать в level-based канал          │
│ │  (CRITICAL → critical.log)             │
│ │  (ERROR → errors.log)                  │
│ │  (WARNING → warnings.log)              │
│ └─ Отправить сигнал другим процессам     │
└─────────┬────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────┐
│ Обработка в зависимости от типа:         │
│ ├─ INITIALIZATION_ERROR                  │
│ │  └─ Не запускать процесс                │
│ ├─ RUNTIME_ERROR                         │
│ │  ├─ Логировать                         │
│ │  ├─ Отправить алерт                    │
│ │  └─ Попробовать восстановление         │
│ └─ SHUTDOWN_ERROR                        │
│    └─ Логировать, но не блокировать      │
└──────────────────────────────────────────┘
```

---

## 15. Graceful Shutdown Cascade

```
Ctrl+C (SIGINT) / SIGTERM
    │
    ▼
ProcessSpawner._signal_handler()
    ├─ set orchestrator_stop_event
    └─ return (НЕ sys.exit!)
    │
    ▼
wait() возвращает управление
    │
    ▼
ProcessSpawner.cleanup()
    ├─ ProcessRegistry.stop_all(timeout=5)
    │   │
    │   └─ Для каждого процесса:
    │       ├─ process_data.stop_event.set()
    │       ├─ join(timeout=5)  ← ждём graceful exit
    │       ├─ if alive: terminate()  ← SIGTERM
    │       ├─ join(timeout=5)
    │       └─ if alive: kill()  ← SIGKILL
    │
    ├─ RouterManager.shutdown()
    ├─ LoggerManager.flush()
    └─ SRM.shutdown()
    │
    ▼
exit(0) или exit(1)
```

---

## 16. Module Dependencies Matrix

```
                    base config data dispatch error logger router command worker process manager console shared
                    mngr_mod_  sch   _mod    _mod  _mod   _mod   _mod    _mod  _mod   _mod    _mod   _resource
                    
base_manager        -    -     -     -       -     -      -      -       -      -      -       -      -
config_module       ✓    -     -     -       -     -      -      -       -      -      -       -      -
data_schema_module  -    -     -     -       -     -      -      -       -      -      -       -      -
dispatch_module     ✓    -     -     -       -     -      -      -       -      -      -       -      -
error_module        ✓    -     -     -       -     ✓      -      -       -      -      -       -      -
logger_module       ✓    -     -     -       -     -      -      -       -      -      -       -      -
router_module       ✓    -     ✓     -       -     -      -      -       -      -      -       -      ✓
command_module      ✓    -     -     ✓       -     -      -      -       -      -      -       -      -
worker_module       ✓    -     -     -       -     -      -      -       -      -      -       -      -
process_module      ✓    ✓     ✓     ✓       ✓     ✓      ✓      ✓       ✓      -      -       -      ✓
console_module      ✓    -     -     -       -     -      -      -       -      -      -       -      -
shared_resources    -    -     -     -       -     -      -      -       -      -      -       -      -
process_manager     ✓    -     -     -       ✓     ✓      ✓      ✓       ✓      ✓      -       ✓      ✓

Легенда:
  ✓ = имеет прямую зависимость
  - = нет зависимости
```

---

## 17. Performance Characteristics

| Операция | Сложность | Примечание |
|----------|-----------|-----------|
| Найти канал по имени | O(1) | ChannelRegistry использует dict |
| Отправить сообщение | O(1) | AsyncSender buffering |
| Получить сообщение | O(n) | poll_all() — проверяет все каналы |
| Диспетчеризировать команду | O(1) | EXACT_MATCH — dict lookup |
| Найти обработчик команды | O(1) | CommandManager registry — dict |
| Логирование в батче | O(batch_size) | Батчинг — амортизированный O(1) |
| Создать процесс | O(n) | fork/spawn — зависит от памяти |
| Остановить процесс | O(timeout) | Graceful shutdown с timeout |

---

## 18. Памяти и ресурсы

| Ресурс | По умолчанию | Конфигурируемо | Примечание |
|--------|-----------|---|---|
| Размер PriorityQueue (AsyncSender) | ∞ | Нет | Не ограничена, может расти |
| Размер пачки логирования | 100 | LogConfig.batch_size | После пачки — сброс на диск |
| Интервал батчинга | 1.0 сек | LogConfig.batch_interval | Периодический sброс |
| Размер ProcessData.custom | ∞ | Нет | Пользовательские данные |
| Размер SharedMemory | конфиг | Да | Per-process, явно зарегистрирована |

---

## Заключение

Эта документация описывает визуально и табличным форматом всю архитектуру фреймворка.
Используй `FRAMEWORK_OVERVIEW.md` для понимания общей концепции и этот файл для деталей.

**Ключ к успеху:** Помни о **Dict at Boundary** и **Graceful Shutdown** — это основы надёжности.

