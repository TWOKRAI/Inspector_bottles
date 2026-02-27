# Multiprocess Framework - Полное описание

Многопроцессный фреймворк для создания распределенных приложений с PyQt/PySide GUI.

## 📋 Содержание

1. [Архитектура](#архитектура)
2. [Основные компоненты](#основные-компоненты)
3. [Классы и методы](#классы-и-методы)
4. [Связи между компонентами](#связи-между-компонентами)
5. [Использование](#использование)

---

## 🏗️ Архитектура

Фреймворк построен на многопроцессной архитектуре, где каждый компонент работает в отдельном процессе:

```
SystemLauncher
    └── ProcessManager (главный процесс)
        ├── SharedResourcesManager (общие ресурсы)
        └── Процессы приложения (ProcessModule)
            ├── WorkerManager (потоки)
            ├── RouterManager (маршрутизация)
            ├── LoggerManager (логирование)
            └── CommandManager (команды)
```

### Основные принципы

- **Многопроцессность**: Каждый компонент - отдельный процесс
- **Централизованное управление**: ProcessManager управляет всеми процессами
- **Общие ресурсы**: SharedResourcesManager для межпроцессного взаимодействия
- **Декларативность**: Декораторы `@process` и `@worker` для определения процессов

---

## 🧩 Основные компоненты

### 1. ProcessManagerModule - Управление процессами

**Классы:**
- `SystemLauncher` - главный запускатель системы
- `ProcessManager` - менеджер процессов (наследуется от ProcessModule)
- `ProcessManagerCore` - ядро управления процессами
- `ProcessManagerBootstrap` - запуск ProcessManager

**Модули:**
- `launcher/` - SystemLauncher
- `process/` - ProcessManager
- `core/` - ProcessManagerCore, ProcessLifecycle, ProcessPriority, ProcessStatus
- `bootstrap/` - ProcessManagerBootstrap
- `builders/` - декораторы и конфигурации (@process, @worker, ProcessConfig)
- `monitor/` - мониторинг процессов
- `platforms/` - платформо-зависимые адаптеры (Windows, Linux)
- `runner/` - запуск процессов

### 2. ProcessModule - Базовый класс процессов

**Класс:** `ProcessModule(ProcessCore)`

**Компоненты:**
- `ProcessCore` - жизненный цикл процесса
- `ProcessConfigHandler` - работа с конфигурацией
- `ManagersComponents` - управление менеджерами
- `ProcessCommunication` - межпроцессная коммуникация

**Модули:**
- `process_module.py` - главный класс ProcessModule
- `core.py` - ProcessCore (жизненный цикл)
- `config_handler.py` - ProcessConfigHandler
- `managers.py` - ManagersComponents
- `communication.py` - ProcessCommunication

### 3. SharedResourcesModule - Общие ресурсы

**Классы:**
- `SharedResourcesManager` - главный менеджер общих ресурсов
- `ProcessStateRegistry` - реестр состояний процессов
- `QueueRegistry` - реестр очередей
- `QueueManager` - менеджер очередей
- `ImageMemoryManager` - управление разделяемой памятью
- `EventManager` - управление событиями
- `ProcessData` - данные процесса (dataclass)
- `ProcessConfiguration` - конфигурация процесса (dataclass)

**Модули:**
- `SharedResourcesManager.py` - главный менеджер
- `process_state_registry.py` - реестр состояний
- `queue_registry.py` - реестр очередей
- `queue_manager.py` - менеджер очередей
- `Memory_Manager.py` - управление памятью
- `event_manager.py` - события
- `process_data.py` - данные процесса
- `process_config.py` - конфигурация процесса

### 4. MessageModule - Система сообщений

**Классы:**
- `Message` - универсальный класс сообщений
- `MessageType` - типы сообщений (Enum)
- `Priority` - приоритеты сообщений (Enum)
- `MessageAdapter` - адаптер для ProcessModule

**Модули:**
- `message.py` - класс Message
- `message_types.py` - типы и приоритеты
- `message_adapter.py` - адаптер

### 5. RouterModule - Маршрутизация

**Классы:**
- `RouterManager` - менеджер маршрутизации
- `MessageChannel` - канал сообщений (базовый)
- `QueueChannel` - канал на основе очередей
- `RouterAdapter` - адаптер для ProcessModule

**Модули:**
- `router_manager.py` - RouterManager
- `channel.py` - каналы сообщений
- `router_adapter.py` - адаптер

### 6. LoggerModule - Логирование

**Классы:**
- `LoggerManager` - главный менеджер логирования
- `LoggerAdapter` - адаптер для ProcessModule
- `LogConfig` - конфигурация логирования
- `LogLevel` - уровни логирования (Enum)
- `LogScope` - области логирования (Enum)
- `BatchManager` - батчинг логов
- `LogDispatcher` - диспетчер логов

**Модули:**
- `manager.py` - LoggerManager
- `logger_adapter.py` - адаптер
- `config.py` - конфигурация и типы
- `batcher.py` - батчинг
- `dispatcher.py` - диспетчер
- `channels.py` - каналы записи

### 7. ConfigModule - Конфигурация

**Классы:**
- `ConfigManager` - менеджер конфигураций
- `Config` - базовый класс конфигурации
- `ConfigSection` - секция конфигурации

**Модули:**
- `config_manager.py` - ConfigManager
- `base_config.py` - Config, ConfigSection

### 8. ConsoleModule - Консоль

**Классы:**
- `ConsoleManager` - менеджер консолей
- `ConsoleChannel` - канал консоли
- `ConsoleRedirector` - редиректор вывода

**Модули:**
- `console_manager.py` - ConsoleManager
- `console_channel.py` - ConsoleChannel
- `redirector.py` - редиректор

### 9. CommandModule - Команды

**Классы:**
- `CommandManager` - менеджер команд
- `CommandAdapter` - адаптер для ProcessModule
- `BaseCommandManager` - базовый класс

**Модули:**
- `command_manager.py` - CommandManager
- `command_adapter.py` - адаптер
- `base_command_manager.py` - базовый класс

### 10. WorkerModule - Потоки

**Классы:**
- `WorkerManager` - менеджер потоков
- `ThreadConfig` - конфигурация потока (dataclass)
- `ThreadPriority` - приоритеты потоков (Enum)
- `WorkerStatus` - статусы воркеров (Enum)

**Модули:**
- `worker_manager.py` - WorkerManager

### 11. DispatchModule - Диспетчеризация

**Классы:**
- `Dispatcher` - универсальный диспетчер
- `BaseDispatcher` - базовый класс
- `DispatchStrategy` - стратегии диспетчеризации (Enum)
- `HandlerInfo` - информация об обработчике
- `Scenario` - сценарий выполнения
- `ScenarioBuilder` - построитель сценариев

**Модули:**
- `dispatcher.py` - Dispatcher
- `base.py` - BaseDispatcher
- `types.py` - типы и стратегии
- `scenario_builder.py` - построитель сценариев
- `dispatch_handler.py` - обработчик диспетчеризации

### 12. GUIModule - GUI компоненты

**Классы:**
- `GUIProcessModule` - базовый класс для GUI процессов
- `BaseWindowManager` - базовый менеджер окон
- `WindowConfig` - конфигурация окна

**Модули:**
- `gui_process_module.py` - GUIProcessModule
- `window_manager.py` - BaseWindowManager

### 13. BaseManagerModule - Базовые менеджеры

**Классы:**
- `BaseManager` - базовый класс менеджера
- `BaseAdapter` - базовый класс адаптера
- `ObservableMixin` - миксин для наблюдаемости

**Модули:**
- `base_manager.py` - BaseManager
- `base_adapter.py` - BaseAdapter
- `observable_mixin.py` - ObservableMixin

---

## 📚 Классы и методы

### SystemLauncher

Главный запускатель системы процессов.

**Методы:**
- `__init__(config, bootstrap)` - инициализация
- `initialize_system(process_config)` - инициализация системы
- `start()` - запуск системы
- `stop()` - остановка системы
- `wait()` - ожидание завершения
- `get_status()` -> dict - получить статус системы
- `get_stats()` -> dict - получить статистику

**Пример:**
```python
launcher = SystemLauncher()
launcher.initialize_system(config_dict)
launcher.start()
launcher.wait()
```

### ProcessManager

Главный процесс системы, управляет всеми процессами.

**Наследуется от:** `ProcessModule`

**Методы (дополнительно к ProcessModule):**
- `register_process(name, class_path, config)` - регистрация процесса
- `start_process(name)` - запуск процесса
- `stop_process(name)` - остановка процесса
- `restart_process(name)` - перезапуск процесса
- `get_process_status(name)` -> dict - статус процесса
- `get_all_processes()` -> dict - все процессы
- `register_worker(process_name, worker_name, func, config)` - регистрация воркера
- `register_queue(process_name, queue_name, queue)` - регистрация очереди

**Связи:**
- Использует `ProcessManagerCore` для логики управления
- Управляет `SharedResourcesManager`
- Интегрирован с `ConsoleManager` и `ConfigManager`

### ProcessModule

Базовый класс для всех процессов системы.

**Методы:**

**Инициализация:**
- `__init__(name, shared_resources, config)` - инициализация

**Доступ к менеджерам:**
- `managers` -> dict - словарь менеджеров
- `adapters` -> dict - словарь адаптеров
- `worker_manager` -> WorkerManager - менеджер потоков
- `logger_manager` -> LoggerManager - менеджер логирования
- `command_manager` -> CommandManager - менеджер команд
- `router_manager` -> RouterManager - менеджер маршрутизации
- `router` -> RouterAdapter - адаптер роутера
- `logger_adapter` -> LoggerAdapter - адаптер логгера
- `command_adapter` -> CommandAdapter - адаптер команд

**Управление менеджерами:**
- `register_manager(name, manager)` - регистрация менеджера
- `register_adapter(name, adapter)` - регистрация адаптера
- `get_manager(name)` -> manager - получить менеджер
- `get_adapter(name)` -> adapter - получить адаптер
- `reload_manager(manager_name)` -> bool - перезагрузить менеджер

**Конфигурация:**
- `update_config(new_config)` -> bool - обновить конфигурацию

**Коммуникация:**
- `send(message)` -> dict - отправить сообщение
- `receive(timeout)` -> list - получить сообщения
- `send_to_process(target, message)` -> bool - отправить процессу
- `broadcast_message(message, exclude_self)` -> int - широковещательная отправка

**Логирование и команды:**
- `log(level, message, context)` - логирование
- `execute_command(command, data)` -> Any - выполнить команду

**Жизненный цикл:**
- `run()` - запуск процесса
- `stop()` - остановка процесса
- `should_stop()` -> bool - проверка флага остановки

**Статистика:**
- `get_stats()` -> dict - получить статистику
- `update_process_state(status, metadata)` - обновить состояние процесса

**Связи:**
- Использует `ProcessCore` для жизненного цикла
- Использует `ProcessConfigHandler` для конфигурации
- Использует `ManagersComponents` для менеджеров
- Использует `ProcessCommunication` для коммуникации
- Интегрирован с `SharedResourcesManager` через `shared_resources`

### SharedResourcesManager

Менеджер общих ресурсов для всех процессов.

**Методы:**
- `__init__(config)` - инициализация
- `get_process_state(name)` -> dict - состояние процесса
- `get_all_process_states()` -> dict - все состояния
- `update_process_state(name, status, metadata)` - обновить состояние
- `register_process(name, config)` - зарегистрировать процесс
- `unregister_process(name)` - удалить процесс
- `get_queue(process_name, queue_name)` -> Queue - получить очередь
- `register_queue(process_name, queue_name, queue)` - зарегистрировать очередь
- `get_stats()` -> dict - статистика

**Связи:**
- Содержит `ProcessStateRegistry` для состояний процессов
- Содержит `QueueRegistry` для очередей
- Содержит `EventManager` для событий
- Используется всеми процессами через `shared_resources`

### RouterManager

Менеджер маршрутизации сообщений.

**Методы:**
- `__init__(name, strategy)` - инициализация
- `send(message)` -> bool - отправить сообщение
- `receive(channel, timeout)` -> list - получить сообщения
- `register_channel(name, channel)` - зарегистрировать канал
- `unregister_channel(name)` - удалить канал
- `get_channel(name)` -> MessageChannel - получить канал

**Связи:**
- Использует `Dispatcher` для маршрутизации
- Использует `MessageChannel` для каналов
- Интегрирован с `ProcessModule` через `RouterAdapter`

### LoggerManager

Менеджер логирования.

**Методы:**
- `__init__(config)` - инициализация
- `log(level, message, context, scope)` - логирование
- `get_logger(name)` -> LoggerAdapter - получить логгер
- `update_config(config)` - обновить конфигурацию
- `shutdown()` - завершение работы

**Связи:**
- Использует `LogDispatcher` для диспетчеризации
- Использует `BatchManager` для батчинга
- Использует каналы из `channels.py` для записи
- Интегрирован с `ProcessModule` через `LoggerAdapter`

### WorkerManager

Менеджер потоков (воркеров).

**Методы:**
- `__init__(name)` - инициализация
- `register_worker(name, func, config)` -> bool - зарегистрировать воркер
- `start_worker(name)` -> bool - запустить воркер
- `stop_worker(name)` -> bool - остановить воркер
- `get_worker_status(name)` -> dict - статус воркера
- `get_all_workers()` -> dict - все воркеры

**Связи:**
- Используется `ProcessModule` для управления потоками
- Интегрирован с декоратором `@worker`

### CommandManager

Менеджер команд.

**Методы:**
- `__init__(name, strategy)` - инициализация
- `register(command, handler)` - зарегистрировать команду
- `execute(command, data)` -> Any - выполнить команду
- `unregister(command)` - удалить команду

**Связи:**
- Использует `Dispatcher` для диспетчеризации команд
- Интегрирован с `ProcessModule` через `CommandAdapter`

### ConfigManager

Менеджер конфигураций.

**Методы:**
- `__init__()` - инициализация
- `get(section, key, default)` -> Any - получить значение
- `set(section, key, value)` - установить значение
- `load_from_file(path)` - загрузить из файла
- `save_to_file(path)` - сохранить в файл

**Связи:**
- Используется всеми процессами для конфигурации
- Интегрирован с `ProcessConfigHandler`

---

## 🔗 Связи между компонентами

### Иерархия наследования

```
ProcessModule
    └── ProcessManager
        └── GUIProcessModule (опционально)

BaseManager
    ├── LoggerManager
    ├── CommandManager
    └── ConsoleManager

BaseAdapter
    ├── LoggerAdapter
    ├── CommandAdapter
    ├── RouterAdapter
    └── MessageAdapter
```

### Композиция ProcessModule

```
ProcessModule
├── ProcessCore (жизненный цикл)
├── ProcessConfigHandler (конфигурация)
├── ManagersComponents (менеджеры)
│   ├── WorkerManager
│   ├── LoggerManager
│   ├── CommandManager
│   └── RouterManager
└── ProcessCommunication (коммуникация)
```

### Потоки данных

```
Процесс A
    └── RouterManager
        └── QueueChannel
            └── SharedResourcesManager
                └── QueueRegistry
                    └── Процесс B
                        └── RouterManager
```

### Управление процессами

```
SystemLauncher
    └── ProcessManagerBootstrap
        └── ProcessManager
            ├── ProcessManagerCore
            │   ├── SharedResourcesManager
            │   ├── QueueRegistry
            │   └── ConfigManager
            └── Процессы (ProcessModule)
```

---

## 💡 Использование

### Базовый пример

```python
from multiprocess_framework import ProcessModule, process, worker, SystemLauncher, ProcessConfig

@process(name="MyProcess")
class MyProcess(ProcessModule):
    def __init__(self, name, shared_resources=None, config=None):
        super().__init__(name, shared_resources, config)
    
    @worker(name="my_worker")
    def my_worker(self):
        while not self.should_stop():
            self.log("INFO", "Working...", "worker")
            time.sleep(1)

# Запуск
config = ProcessConfig(
    name="MyProcess",
    class_path="__main__.MyProcess"
)

launcher = SystemLauncher()
launcher.initialize_system({"MyProcess": config.to_dict()})
launcher.start()
launcher.wait()
```

### Использование менеджеров

```python
class MyProcess(ProcessModule):
    def __init__(self, name, shared_resources=None, config=None):
        super().__init__(name, shared_resources, config)
    
    def some_method(self):
        # Логирование
        self.log("INFO", "Message", "context")
        
        # Отправка сообщения
        self.send({
            "type": "data",
            "target": "OtherProcess",
            "content": {"data": "value"}
        })
        
        # Выполнение команды
        result = self.execute_command("process_data", {"id": 123})
        
        # Регистрация воркера программно
        self.worker_manager.register_worker(
            "custom_worker",
            self.custom_worker_func,
            ThreadConfig(priority=ThreadPriority.NORMAL)
        )
```

### Использование SharedResources

```python
class MyProcess(ProcessModule):
    def __init__(self, name, shared_resources=None, config=None):
        super().__init__(name, shared_resources, config)
    
    def access_shared_resources(self):
        # Получить состояние процесса
        state = self.shared_resources.get_process_state("OtherProcess")
        
        # Обновить свое состояние
        self.update_process_state("running", {"custom": "data"})
        
        # Получить очередь другого процесса
        queue = self.shared_resources.get_queue("OtherProcess", "data")
        
        # Отправить в очередь
        queue.put({"message": "hello"})
```

---

## 📖 Дополнительная документация

- [Руководство по импортам](../../docs/IMPORT_GUIDE.md)
- [Использование пакета](../../docs/PACKAGE_USAGE.md)
- [Примеры](../../examples/)
- [Тесты](../../tests/)

---

## 🔧 Технические детали

### Декораторы

- `@process(name, priority)` - декоратор для определения процесса
- `@worker(name, priority)` - декоратор для определения воркера

### Конфигурации

- `ProcessConfig` - конфигурация процесса
- `QueueConfig` - конфигурация очереди
- `WorkerConfig` - конфигурация воркера
- `ConsoleConfig` - конфигурация консоли
- `ThreadConfig` - конфигурация потока

### Типы данных

- `ProcessData` - данные процесса (dataclass)
- `ProcessConfiguration` - конфигурация процесса (dataclass)
- `Message` - сообщение
- `MessageType` - типы сообщений (Enum)
- `ProcessStatus` - статусы процессов (Enum)
- `ProcessPriority` - приоритеты процессов (Enum)
- `ThreadPriority` - приоритеты потоков (Enum)
- `LogLevel` - уровни логирования (Enum)
- `DispatchStrategy` - стратегии диспетчеризации (Enum)

---

**Версия:** 1.0.0  
**Автор:** INNOTECH

