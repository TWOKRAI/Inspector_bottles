# Руководство по использованию CommandModule

## Введение

CommandModule предоставляет систему управления командами с интеграцией BaseManager и ObservableMixin.

## Быстрый старт

### Базовое использование

```python
from multiprocess_framework.refactored.modules.command_module import CommandManager

# Создание менеджера команд
manager = CommandManager("my_process")

# Инициализация менеджера
manager.initialize()

# Регистрация команды
def greet_handler(data):
    name = data.get("name", "World")
    return f"Hello, {name}!"

manager.register_command("greet", greet_handler)

# Выполнение команды
message = {
    "command": "greet",
    "data": {"name": "Alice"}
}
result = manager.handle_command(message)
print(result)  # "Hello, Alice!"

# Завершение работы менеджера
manager.shutdown()
```

## Регистрация команд

### Простая регистрация

```python
def handler(data):
    return {"processed": True, "data": data}

manager.register_command("process", handler)
```

### Регистрация с метаданными

```python
manager.register_command(
    "process",
    handler,
    metadata={"description": "Обработка данных", "version": "1.0"},
    tags=["processing", "data"]
)
```

### Регистрация с различными стратегиями

```python
from multiprocess_framework.refactored.modules.dispatch_module import DispatchStrategy

# EXACT_MATCH (по умолчанию)
manager.register_command("exact_cmd", handler)

# PATTERN_MATCH
manager.register_command(
    r"pattern_\d+",
    handler,
    strategy=DispatchStrategy.PATTERN_MATCH
)

# FALLBACK_MATCH
manager.register_command(
    "fallback_cmd",
    handler,
    strategy=DispatchStrategy.FALLBACK_MATCH,
    efficiency=10
)
```

## Выполнение команд

### Базовое выполнение

```python
message = {
    "command": "process",
    "data": {"value": 10}
}
result = manager.handle_command(message)
```

### Выполнение с указанием стратегии

```python
message = {
    "command": "process",
    "strategy": "fallback",
    "data": {"value": 10}
}
result = manager.handle_command(message)
```

## Управление командами

### Получение списка команд

```python
commands = manager.get_commands()
for cmd in commands:
    print(f"Command: {cmd['key']}")
```

### Получение информации о команде

```python
info = manager.get_command_info("process")
print(info)
# {
#     "key": "process",
#     "metadata": {...},
#     "tags": [...],
#     ...
# }
```

### Поиск команд по тегу

```python
vision_commands = manager.get_commands_by_tag("vision")
for cmd in vision_commands:
    print(f"Vision command: {cmd['key']}")
```

### Обновление метаданных

```python
manager.update_command_metadata(
    "process",
    {"version": "2.0", "updated": True}
)
```

### Обновление тегов

```python
manager.update_command_tags("process", ["processing", "high_priority"])
```

### Перезапись команды

```python
def new_handler(data):
    return {"new": "result"}

manager.overwrite_command("process", new_handler)
```

## Интеграция с ObservableMixin

### Логирование

```python
from multiprocess_framework.modules.Logger_module import LoggerManager

logger = LoggerManager("command_logger")
manager = CommandManager(
    "my_process",
    managers={'logger': logger},
    config={'logger': True}
)

# Все команды будут логироваться автоматически
manager.register_command("test", handler)
manager.handle_command({"command": "test", "data": {}})
```

### Статистика

```python
manager = CommandManager(
    "my_process",
    managers={'statistics': stats_manager},
    config={'statistics': True}
)

# Метрики собираются автоматически
manager.handle_command({"command": "process", "data": {}})

# Получение статистики
stats = manager.get_stats()
print(stats)
# {
#     "manager_name": "my_process",
#     "total_commands": 5,
#     "commands": ["cmd1", "cmd2", ...],
#     ...
# }
```

## Использование адаптера

### Базовое использование адаптера

```python
from multiprocess_framework.refactored.modules.command_module import CommandAdapter

manager = CommandManager("my_process")
manager.initialize()

adapter = CommandAdapter(manager, process=current_process)
adapter.setup()

# Выполнение команды через систему сообщений
adapter.execute_via_message(
    command_name="process",
    args={"value": 10},
    targets=["target_process"],
    need_ack=True
)
```

## Примеры использования

### Пример 1: Простая обработка команд

```python
manager = CommandManager("app")
manager.initialize()

# Регистрация обработчиков
def add_handler(data):
    a = data.get("a", 0)
    b = data.get("b", 0)
    return a + b

def multiply_handler(data):
    a = data.get("a", 1)
    b = data.get("b", 1)
    return a * b

manager.register_command("add", add_handler, tags=["math"])
manager.register_command("multiply", multiply_handler, tags=["math"])

# Выполнение команд
result1 = manager.handle_command({"command": "add", "data": {"a": 5, "b": 3}})
print(result1)  # 8

result2 = manager.handle_command({"command": "multiply", "data": {"a": 4, "b": 7}})
print(result2)  # 28

manager.shutdown()
```

### Пример 2: Работа с метаданными

```python
manager = CommandManager("app")
manager.initialize()

def process_handler(data):
    return {"processed": True, "data": data}

# Регистрация с метаданными
manager.register_command(
    "process",
    process_handler,
    metadata={
        "description": "Обработка данных",
        "version": "1.0",
        "author": "System"
    },
    tags=["processing", "data"]
)

# Получение информации
info = manager.get_command_info("process")
print(info["metadata"]["description"])  # "Обработка данных"

# Обновление метаданных
manager.update_command_metadata("process", {
    "version": "2.0",
    "updated": True
})

manager.shutdown()
```

### Пример 3: Использование различных стратегий

```python
from multiprocess_framework.refactored.modules.dispatch_module import DispatchStrategy

manager = CommandManager("app")
manager.initialize()

# EXACT_MATCH (по умолчанию)
def exact_handler(data):
    return "exact"

manager.register_command("test", exact_handler, strategy=DispatchStrategy.EXACT_MATCH)

# PATTERN_MATCH
def pattern_handler(data):
    return "pattern"

manager.register_command(
    r"test.*",
    pattern_handler,
    strategy=DispatchStrategy.PATTERN_MATCH
)

# Выполнение
result1 = manager.handle_command({"command": "test", "data": {}})
# Используется EXACT_MATCH

result2 = manager.handle_command({"command": "test123", "data": {}})
# Используется PATTERN_MATCH

manager.shutdown()
```

## Лучшие практики

1. **Всегда вызывайте initialize()** после создания менеджера
2. **Всегда вызывайте shutdown()** перед завершением работы
3. **Используйте метаданные** для документирования команд
4. **Группируйте команды по тегам** для удобства управления
5. **Используйте ObservableMixin** для логирования и мониторинга
6. **Валидируйте входные данные** в обработчиках команд

## Дополнительные ресурсы

- [ARCHITECTURE.md](ARCHITECTURE.md) - Архитектура модуля
- [API_REFERENCE.md](API_REFERENCE.md) - Справочник API

