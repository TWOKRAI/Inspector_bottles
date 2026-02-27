# Process Manager Module

Модуль управления процессами в многопроцессной архитектуре. Предоставляет централизованное управление жизненным циклом процессов, их приоритетами, статусами и конфигурациями.

## 📁 Структура модуля

Модуль организован по папкам с четкой ответственностью:

```
Process_manager_module/
├── core/                    # Утилитарные классы с логикой управления
│   ├── process_manager_core.py    # Основная логика управления процессами
│   ├── process_lifecycle.py       # Жизненный цикл процессов
│   ├── process_priority.py        # Управление приоритетами
│   └── process_status.py           # Мониторинг статусов
├── process/                 # ProcessManager как процесс системы
│   └── process_manager_process.py  # ProcessManagerProcess (наследуется от ProcessModule)
├── bootstrap/              # Bootstrap для запуска ProcessManagerProcess
│   └── process_manager_bootstrap.py
├── legacy/                  # Старый ProcessManager (обратная совместимость)
│   └── Processes_Manager.py
├── config/                  # Конфигурация процессов
│   └── process_config.py
├── runner/                  # Запуск процессов
│   └── process_runner.py
├── monitor/                 # Мониторинг процессов
│   └── process_monitor.py
├── platforms/              # Платформо-зависимые адаптеры
│   ├── base.py
│   ├── windows.py
│   └── linux.py
└── helpers/                # Вспомогательные классы
```

## 🚀 Быстрый старт

### Новая архитектура (рекомендуется)

```python
from src.Modules.Process_manager_module import ProcessManagerBootstrap

# Создание и запуск ProcessManagerProcess
bootstrap = ProcessManagerBootstrap(config="config/processes.yaml")
bootstrap.start()
bootstrap.wait()
```

### Старая архитектура (обратная совместимость)

```python
from src.Modules.Process_manager_module import ProcessManager

# Создание менеджера процессов
pm = ProcessManager(config="config/processes.yaml")

# Инициализация процессов
pm.initialize_processes()

# Запуск всех процессов
pm.start_processes()

# Ожидание завершения
pm.wait_for_processes()

# Остановка процессов
pm.stop_processes()
```

## 🏗️ Архитектура

### Новая архитектура

```
Bootstrap
    ↓ создает
ProcessManagerProcess (ProcessModule)
    ↓ использует
ProcessManagerCore (утилитарный класс)
    ↓ создает
Другие процессы
```

**Преимущества новой архитектуры:**
- ✅ ProcessManagerProcess - полноценный процесс системы
- ✅ Команды через роутер (start/stop, register_worker, register_queue)
- ✅ Множественные воркеры с разными приоритетами
- ✅ Единообразие с остальными процессами
- ✅ Централизованное управление через shared_resources

### Компоненты

#### ProcessManagerCore

Утилитарный класс с логикой управления процессами (не процесс).

```python
from src.Modules.Process_manager_module import ProcessManagerCore

core = ProcessManagerCore(
    shared_resources=shared_resources,
    queue_registry=queue_registry,
    config_manager=config_manager,
    console_manager=console_manager,
    logger=logger,
    platform_adapter=platform,
    stop_event=stop_event
)

# Создание процесса
process = core.create_process(
    name="MyProcess",
    class_path="module.path.ClassName",
    config={...},
    priority="normal"
)

# Запуск процесса
core.start_process("MyProcess")
```

#### ProcessManagerProcess

ProcessManager как процесс системы (наследуется от ProcessModule).

```python
from src.Modules.Process_manager_module import ProcessManagerProcess

# Создается автоматически через Bootstrap
# Получает команды через роутер:
# - start_process, stop_process, restart_process
# - register_worker, register_queue
# - get_stats, get_process_status
```

**Воркеры ProcessManagerProcess:**
- `priority_command_processor` - приоритетные команды (REALTIME, 0.01s)
- `normal_command_processor` - обычные команды (NORMAL, 0.1s)
- `batch_processor` - batch операции (BATCH, 1.0s)

#### ProcessManagerBootstrap

Легковесный Bootstrap для запуска ProcessManagerProcess.

```python
from src.Modules.Process_manager_module import ProcessManagerBootstrap

bootstrap = ProcessManagerBootstrap(config="config/processes.yaml")
bootstrap.start()      # Запускает ProcessManagerProcess
bootstrap.wait()       # Ожидает завершения
bootstrap.stop()       # Останавливает ProcessManagerProcess
```

## 📦 Основные компоненты

### ProcessManagerCore

Утилитарный класс с логикой управления процессами.

#### Методы

```python
# Создание процесса
process = core.create_process(name, class_path, config, priority)

# Создание процессов из конфигурации
count = core.create_processes_from_config(config_data)

# Управление процессами
core.start_process(process_name=None)  # None = все процессы
core.stop_process(process_name=None)

# Регистрация
core.register_worker(process_name, worker_name, ...)
core.register_queue(process_name, queue_name, maxsize)

# Статус
status = core.get_process_status(process_name=None)
```

### ProcessManagerProcess

ProcessManager как процесс системы.

**Обработка команд через роутер:**

```python
# Приоритетные команды (канал: priority_commands)
{
    "command": "start_process",
    "data": {"process_name": "MyProcess"}
}

{
    "command": "stop_process",
    "data": {"process_name": "MyProcess"}
}

{
    "command": "restart_process",
    "data": {"process_name": "MyProcess"}
}

# Обычные команды (канал: normal_commands)
{
    "command": "register_worker",
    "data": {
        "process_name": "MyProcess",
        "worker_name": "my_worker",
        "worker_class_path": "module.path.WorkerClass",
        "config": {...},
        "priority": "normal",
        "auto_start": True
    }
}

{
    "command": "register_queue",
    "data": {
        "process_name": "MyProcess",
        "queue_name": "custom_queue",
        "maxsize": 100
    }
}

# Batch операции (канал: batch_operations)
{
    "operation": "get_stats"
}

{
    "operation": "get_process_status",
    "data": {"process_name": "MyProcess"}
}

{
    "operation": "health_check"
}
```

### ProcessManager (Legacy)

Старый ProcessManager для обратной совместимости.

#### Инициализация

```python
pm = ProcessManager(platform_adapter=None, config=None)
```

#### Основные методы

```python
# Загрузка конфигурации
config = pm.load_config(config_source)

# Инициализация процессов
pm.initialize_processes(config_source=None)

# Управление жизненным циклом
pm.start_processes()
pm.stop_processes()
pm.join_processes(timeout=3.0)
pm.wait_for_processes()

# Регистрация
pm.register_process(name, class_path, config, priority, enabled, ...)
pm.register_queue(process_name, queue_name, maxsize)
pm.register_worker(process_name, worker_name, worker_class_path, ...)

# Мониторинг
status = pm.get_process_status()
stats = pm.get_stats()
config = pm.get_process_config()
```

## 💡 Примеры использования

### Пример 1: Новая архитектура

```python
from src.Modules.Process_manager_module import ProcessManagerBootstrap

# Запуск ProcessManagerProcess
bootstrap = ProcessManagerBootstrap(config="config/processes.yaml")
bootstrap.start()

# ProcessManagerProcess автоматически создаст и запустит процессы из конфигурации
bootstrap.wait()
```

### Пример 2: Отправка команд в ProcessManagerProcess

```python
from src.Modules.Message_module.message import Message
from src.Modules.Message_module.message_types import MessageType

# Создаем сообщение для ProcessManagerProcess
message = Message(
    message_type=MessageType.COMMAND,
    sender="MyProcess",
    target="ProcessManager",
    content={
        "command": "start_process",
        "data": {"process_name": "NewProcess"}
    }
)

# Отправляем через роутер
router.send(message)
```

### Пример 3: Старая архитектура

```python
from src.Modules.Process_manager_module import ProcessManager

pm = ProcessManager()
pm.load_config("config/processes.yaml")
pm.initialize_processes()
pm.start_processes()
pm.wait_for_processes()
```

### Пример 4: Программная регистрация (Legacy)

```python
from src.Modules.Process_manager_module import ProcessManager

pm = ProcessManager()

# Регистрация процесса
pm.register_process(
    name="MyProcess",
    class_path="src.Modules.Process_module.process_module.ProcessModule",
    config={"key": "value"},
    priority="high",
    enabled=True,
    console_config={"enabled": True, "title": "My Process"},
    queue_config={"system": {"maxsize": 100}}
)

# Регистрация очереди
pm.register_queue("MyProcess", "custom_queue", maxsize=200)

# Регистрация воркера
pm.register_worker(
    process_name="MyProcess",
    worker_name="my_worker",
    worker_class_path="MyModule.MyWorker",
    config={"interval": 1.0},
    priority="normal",
    auto_start=True
)

pm.initialize_processes()
pm.start_processes()
```

## 📋 Формат конфигурации

### YAML формат

```yaml
ProcessName:
  name: ProcessName
  class: "module.path.ClassName"
  priority: "normal"  # high, normal, low, above_normal, below_normal
  enabled: true
  config:
    key: value
    nested:
      key: value
  queues:
    system:
      maxsize: 100
    data:
      maxsize: 50
  console:
    enabled: true
    title: "Process Console"
    recipient: "main_console"
  workers:
    worker_name:
      class: "module.path.WorkerClass"
      priority: "normal"
      auto_start: true
      config:
        interval: 1.0
```

## 🔗 Интеграция с другими модулями

### SharedResourcesManager

ProcessManager использует `SharedResourcesManager` для передачи данных между процессами.

### ConfigManager

Все конфигурации хранятся в `ConfigManager` и автоматически валидируются.

### LoggerManager

Логирование через `LoggerManager` с поддержкой файлов по модулям.

## 🧪 Тесты

```bash
# Все тесты Process Manager модуля
pytest tests/Test_Process_manager_module/ -v

# Конкретные тесты
pytest tests/Test_Process_manager_module/test_process_manager.py -v
pytest tests/Test_Process_manager_module/test_process_monitor.py -v
pytest tests/Test_Process_manager_module/test_process_lifecycle.py -v

# С покрытием кода
pytest tests/Test_Process_manager_module/ --cov=src.Modules.Process_manager_module
```

## 🎯 Ключевые особенности

- ✅ **Новая архитектура**: ProcessManager как процесс системы
- ✅ **Единообразие**: Все процессы наследуются от ProcessModule
- ✅ **Производительность**: Множественные воркеры с разными приоритетами
- ✅ **Гибкость**: Команды через роутер, легко расширять
- ✅ **Централизованное управление**: ProcessManager владеет shared_resources
- ✅ **Обратная совместимость**: Старый ProcessManager сохранен
- ✅ **Кроссплатформенность**: Автоматическое определение Windows/Linux
- ✅ **Мониторинг**: Автоматический мониторинг состояний процессов

## 📖 Дополнительная документация

- **[Process Module](../Process_module/README.md)** - Базовый класс процессов
- **[Worker Module](../Worker_module/README.md)** - Управление воркерами
- **[Router Module](../Router_module/README.md)** - Маршрутизация сообщений
- **[Архитектура системы](../../docs/ARCHITECTURE_EVALUATION.md)** - Общая архитектура

## ⚠️ Важные замечания

1. **Новая архитектура**: Рекомендуется использовать `ProcessManagerBootstrap` и `ProcessManagerProcess`
2. **Обратная совместимость**: Старый `ProcessManager` сохранен в `legacy/`
3. **Windows**: На Windows используется `spawn` метод для multiprocessing
4. **Конфигурация**: Все конфигурации хранятся в `ConfigManager` и автоматически валидируются
5. **Процессы**: Процессы создаются как дочерние процессы ОС через `multiprocessing.Process`
