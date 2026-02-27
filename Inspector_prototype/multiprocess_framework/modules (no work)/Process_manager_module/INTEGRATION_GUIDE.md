# Руководство по Интеграции Process Manager Module

## 📚 Обзор

ProcessManager - это главный процесс системы для создания многопроцессных приложений.
Он выступает как централизованная точка управления, обеспечивающая:

- **Хранилище SharedResources** - общие ресурсы для всех процессов
- **Мониторинг процессов** - отслеживание состояний всех процессов
- **Широковещательное общение** - связь между процессами через роутер
- **Управление в реальном времени** - создание, запуск, остановка процессов
- **Интеграция с модулями** - удобная работа с ConfigManager, ConsoleManager и другими

## 🔗 Интеграция с ConfigManager

ProcessManager использует ConfigManager для удобной работы с конфигурациями процессов.

### Загрузка конфигурации

```python
from src.Modules.Process_manager_module import ProcessManager

# ProcessManager автоматически загружает конфигурацию при инициализации
manager = ProcessManager(shared_resources=shared_resources, config="config/processes.yaml")

# Или загрузить конфигурацию программно
manager.config_manager.load_process_config("config/processes.yaml")
manager.config_manager.update_process_config(validated_config)
```

### Работа с конфигурациями процессов

```python
# Получить все конфигурации процессов
all_configs = manager.config_manager.get_process_config()

# Получить конфигурацию конкретного процесса
process_config = manager.config_manager.get_process_config().get("ProcessName")

# Обновить конфигурацию процесса
current_config = manager.config_manager.get_process_config()
current_config["ProcessName"]["config"]["new_key"] = "new_value"
manager.config_manager.update_process_config(current_config)

# Валидация конфигурации (автоматически через ProcessConfig)
validated = manager.config_manager.load_process_config(config_source)
```

### Команды для работы с конфигурацией

ProcessManager обрабатывает команды через роутер:

```python
# Обновление конфигурации процесса (команда)
message = {
    "type": "command",
    "command": "update_config",
    "data": {
        "process_name": "ProcessName",
        "config": {"new_key": "new_value"}
    },
    "sender": "YourProcess",
    "target": "ProcessManager"
}
router.send(message)

# Получение конфигурации (batch операция)
message = {
    "type": "operation",
    "operation": "get_config",
    "data": {"process_name": "ProcessName"},  # или None для всех
    "sender": "YourProcess",
    "target": "ProcessManager"
}
router.send(message)
```

## 🖥️ Интеграция с ConsoleManager

ProcessManager интегрирован с ConsoleManager для управления консолями процессов.

### Автоматическая настройка консолей

При создании процессов консоли настраиваются автоматически из конфигурации:

```yaml
ProcessName:
  console:
    enabled: true
    title: "Process Console"
    recipient: "main_console"  # или список ["console1", "console2"]
```

### Управление консолями в реальном времени

```python
# Команда для настройки консоли процесса
message = {
    "type": "command",
    "command": "configure_console",
    "data": {
        "process_name": "ProcessName",
        "console_config": {
            "enabled": True,
            "title": "New Console Title",
            "recipient": "main_console"
        }
    },
    "sender": "YourProcess",
    "target": "ProcessManager"
}
router.send(message)

# Команда для удаления консоли процесса
message = {
    "type": "command",
    "command": "remove_console",
    "data": {
        "process_name": "ProcessName"
    },
    "sender": "YourProcess",
    "target": "ProcessManager"
}
router.send(message)
```

### Получение информации о консолях

```python
# Через ConsoleManager напрямую
console_status = manager.console_manager.get_status("ProcessName")

# Через ProcessData
process_data = manager.shared_resources.get_process_data("ProcessName")
console_info = process_data.custom.get("console_info", {})
```

## 🔄 Интеграция с SharedResourcesManager

ProcessManager выступает как централизованное хранилище SharedResources для всех процессов.

### Доступ к SharedResources

```python
# ProcessManager владеет SharedResourcesManager
shared_resources = manager.shared_resources

# Все процессы получают доступ к одному экземпляру
# ProcessData с конфигурацией доступен через:
process_data = shared_resources.get_process_data("ProcessName")
config = process_data.config.process  # Конфигурация процесса
```

### Регистрация процессов

```python
# ProcessManager автоматически регистрирует процессы при создании
# Регистрация происходит в ProcessManagerCore.create_process()
process = manager.core.create_process(
    name="ProcessName",
    class_path="module.path.ClassName",
    config={...},
    priority="normal"
)

# Процесс регистрируется в SharedResources с конфигурацией
process_data = shared_resources.get_process_data("ProcessName")
```

### Мониторинг состояний

ProcessManager автоматически отслеживает изменения состояний процессов:

```python
# ProcessManager отправляет broadcast сообщения при изменении статуса
# В вашем процессе можно получать эти сообщения:

def handle_system_message(message):
    if message.get("subtype") == "process_status_changed":
        process_name = message["process_name"]
        old_status = message["old_status"]
        new_status = message["new_status"]
        print(f"Process {process_name} status: {old_status} -> {new_status}")

# Подписка на системные сообщения через роутер
router.subscribe("system", handle_system_message)
```

## 📨 Команды ProcessManager

### Приоритетные команды (канал: `priority_commands`)

```python
# Запуск процесса
{
    "type": "command",
    "command": "start_process",
    "data": {"process_name": "ProcessName"},
    "sender": "YourProcess",
    "target": "ProcessManager"
}

# Остановка процесса
{
    "type": "command",
    "command": "stop_process",
    "data": {"process_name": "ProcessName"},
    "sender": "YourProcess",
    "target": "ProcessManager"
}

# Перезапуск процесса
{
    "type": "command",
    "command": "restart_process",
    "data": {"process_name": "ProcessName"},
    "sender": "YourProcess",
    "target": "ProcessManager"
}
```

### Обычные команды (канал: `normal_commands`)

```python
# Регистрация воркера
{
    "type": "command",
    "command": "register_worker",
    "data": {
        "process_name": "ProcessName",
        "worker_name": "worker_name",
        "worker_class_path": "module.path.WorkerClass",
        "config": {...},
        "priority": "normal",
        "auto_start": True
    },
    "sender": "YourProcess",
    "target": "ProcessManager"
}

# Регистрация очереди
{
    "type": "command",
    "command": "register_queue",
    "data": {
        "process_name": "ProcessName",
        "queue_name": "queue_name",
        "maxsize": 100
    },
    "sender": "YourProcess",
    "target": "ProcessManager"
}

# Обновление конфигурации
{
    "type": "command",
    "command": "update_config",
    "data": {
        "process_name": "ProcessName",
        "config": {"key": "value"}
    },
    "sender": "YourProcess",
    "target": "ProcessManager"
}

# Настройка консоли
{
    "type": "command",
    "command": "configure_console",
    "data": {
        "process_name": "ProcessName",
        "console_config": {
            "enabled": True,
            "title": "Console Title",
            "recipient": "main_console"
        }
    },
    "sender": "YourProcess",
    "target": "ProcessManager"
}

# Удаление консоли
{
    "type": "command",
    "command": "remove_console",
    "data": {
        "process_name": "ProcessName"
    },
    "sender": "YourProcess",
    "target": "ProcessManager"
}
```

### Batch операции (канал: `batch_operations`)

```python
# Получение статистики
{
    "type": "operation",
    "operation": "get_stats",
    "data": {},
    "sender": "YourProcess",
    "target": "ProcessManager"
}

# Получение статуса процесса
{
    "type": "operation",
    "operation": "get_process_status",
    "data": {"process_name": "ProcessName"},
    "sender": "YourProcess",
    "target": "ProcessManager"
}

# Проверка здоровья системы
{
    "type": "operation",
    "operation": "health_check",
    "data": {},
    "sender": "YourProcess",
    "target": "ProcessManager"
}

# Получение конфигурации
{
    "type": "operation",
    "operation": "get_config",
    "data": {"process_name": "ProcessName"},  # или None для всех
    "sender": "YourProcess",
    "target": "ProcessManager"
}
```

## 📋 Примеры Использования

### Пример 1: Создание процесса через ProcessManager

```python
from src.Modules.Process_manager_module import ProcessManagerBootstrap

# Запуск ProcessManager
bootstrap = ProcessManagerBootstrap(config="config/processes.yaml")
bootstrap.start()

# ProcessManager автоматически создаст и запустит процессы из конфигурации
bootstrap.wait()
```

### Пример 2: Управление процессами в реальном времени

```python
# В вашем процессе отправляем команду в ProcessManager
from src.Modules.Message_module.message import Message
from src.Modules.Message_module.message_types import MessageType

# Запуск процесса
message = Message(
    message_type=MessageType.COMMAND,
    sender="YourProcess",
    target="ProcessManager",
    content={
        "command": "start_process",
        "data": {"process_name": "NewProcess"}
    }
)
router.send(message)

# Получение статуса
message = Message(
    message_type=MessageType.OPERATION,
    sender="YourProcess",
    target="ProcessManager",
    content={
        "operation": "get_process_status",
        "data": {"process_name": "NewProcess"}
    }
)
router.send(message)
```

### Пример 3: Подписка на изменения статусов процессов

```python
def on_process_status_changed(message):
    """Обработчик изменения статуса процесса"""
    process_name = message["process_name"]
    old_status = message["old_status"]
    new_status = message["new_status"]
    
    print(f"📊 Process '{process_name}' status: {old_status} → {new_status}")
    
    # Ваша логика обработки изменения статуса
    if new_status == "error":
        # Обработка ошибки
        pass

# Подписка на системные сообщения через роутер
router.subscribe("system", on_process_status_changed)
```

### Пример 4: Работа с конфигурациями

```python
# Получение конфигурации через команду
message = Message(
    message_type=MessageType.OPERATION,
    sender="YourProcess",
    target="ProcessManager",
    content={
        "operation": "get_config",
        "data": {"process_name": "ProcessName"}
    }
)
router.send(message)

# Обновление конфигурации
message = Message(
    message_type=MessageType.COMMAND,
    sender="YourProcess",
    target="ProcessManager",
    content={
        "command": "update_config",
        "data": {
            "process_name": "ProcessName",
            "config": {
                "new_setting": "new_value"
            }
        }
    }
)
router.send(message)
```

### Пример 5: Управление консолями

```python
# Настройка консоли для процесса
message = Message(
    message_type=MessageType.COMMAND,
    sender="YourProcess",
    target="ProcessManager",
    content={
        "command": "configure_console",
        "data": {
            "process_name": "ProcessName",
            "console_config": {
                "enabled": True,
                "title": "My Process Console",
                "recipient": "main_console"
            }
        }
    }
)
router.send(message)
```

## 🎯 Лучшие Практики

1. **Используйте ProcessManager как центральную точку управления**
   - Все команды управления процессами отправляйте через ProcessManager
   - Используйте broadcast сообщения для связи между процессами

2. **Конфигурация через ConfigManager**
   - Храните все конфигурации в ConfigManager
   - Используйте ProcessConfig для валидации

3. **Мониторинг состояний**
   - Подписывайтесь на системные сообщения для отслеживания изменений статусов
   - Используйте health_check для проверки состояния системы

4. **Управление консолями**
   - Настраивайте консоли в конфигурации процесса
   - Используйте команды для динамического управления консолями

5. **Интеграция с SharedResources**
   - ProcessManager - единственный владелец SharedResourcesManager
   - Все процессы получают доступ через shared_resources параметр

## 📖 Дополнительная Документация

- [ProcessManager README](README.md) - основная документация
- [Класс ProcessManager](process/manager_process.py) - исходный код
- [ProcessManagerCore](core/process_manager_core.py) - логика управления
- [ConfigManager Documentation](../../Config_module/README.md) - работа с конфигурациями
- [ConsoleManager Documentation](../../Console_module/README.md) - управление консолями

