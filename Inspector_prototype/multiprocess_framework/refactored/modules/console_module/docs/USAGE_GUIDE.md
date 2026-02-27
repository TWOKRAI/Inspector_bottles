# Руководство по использованию ConsoleModule

## Содержание

1. [Быстрый старт](#быстрый-старт)
2. [Встроенный режим](#встроенный-режим)
3. [Отдельный процесс для отладки](#отдельный-процесс-для-отладки)
4. [Интерактивный режим](#интерактивный-режим)
5. [Перенаправление stdout/stderr](#перенаправление-stdoutstderr)
6. [Интеграция с RouterManager](#интеграция-с-routermanger)
7. [Интеграция с CommandManager](#интеграция-с-commandmanager)
8. [Примеры использования](#примеры-использования)

## Быстрый старт

### Базовое использование

```python
from multiprocess_framework.refactored.modules.console_module import ConsoleManager

# Создание менеджера
console_manager = ConsoleManager(
    manager_name="MyConsole",
    enabled=True
)

# Инициализация
console_manager.initialize()

# Отправка сообщения
console_manager.send_message("Hello, World!", level="INFO")

# Завершение работы
console_manager.shutdown()
```

### С интеграцией менеджеров

```python
from multiprocess_framework.refactored.modules.console_module import ConsoleManager
from multiprocess_framework.refactored.modules.command_module import CommandManager
from multiprocess_framework.refactored.modules.router_module import RouterManager

# Создание зависимостей
command_manager = CommandManager("MyProcess")
router_manager = RouterManager("MyRouter")

# Создание консольного менеджера
console_manager = ConsoleManager(
    manager_name="MyConsole",
    command_manager=command_manager,
    router_manager=router_manager,
    enabled=True,
    interactive=True,
    redirect_enabled=True
)

# Инициализация
console_manager.initialize()
command_manager.initialize()
router_manager.initialize()

# Регистрация каналов в роутере
console_manager.register_in_router(router_manager)
```

## Встроенный режим

Встроенный режим позволяет использовать консоль прямо в процессе.

### Включение/выключение консоли

```python
console_manager = ConsoleManager(manager_name="MyConsole")
console_manager.initialize()

# Включить консоль
console_manager.enable_console(enabled=True)

# Отправить сообщение
console_manager.send_message("Message 1", level="INFO")
console_manager.send_message("Message 2", level="WARNING")
console_manager.send_message("Message 3", level="ERROR")

# Выключить консоль
console_manager.enable_console(enabled=False)
```

### Проверка состояния

```python
if console_manager.is_console_enabled():
    console_manager.send_message("Console is enabled")
```

## Отдельный процесс для отладки

Отдельный процесс консоли создается через ProcessManager для отладки.

### Создание отдельного процесса

```python
from multiprocess_framework.refactored.modules.process_manager_module import ProcessManagerCore

# Создание менеджеров
process_manager = ProcessManagerCore("ProcessManager")
router_manager = RouterManager("Router")
command_manager = CommandManager("Commands")

console_manager = ConsoleManager(
    manager_name="MainConsole",
    command_manager=command_manager,
    router_manager=router_manager
)

# Инициализация
process_manager.initialize()
router_manager.initialize()
command_manager.initialize()
console_manager.initialize()

# Создание отдельного процесса для отладки
console_manager.create_debug_process(
    process_name="DebugConsole",
    process_manager=process_manager,
    router_manager=router_manager,
    command_manager=command_manager
)
```

### Отправка сообщений в отдельный процесс

```python
# Через роутер
router_manager.send({
    'channel': 'console.DebugConsole',
    'text': 'Debug message',
    'level': 'INFO',
    'timestamp': True
})

# Прямая отправка через консольный менеджер
console_manager._send_to_console(
    "Direct message",
    target_process="DebugConsole"
)
```

## Интерактивный режим

Интерактивный режим позволяет вводить команды и получать результаты.

### Включение интерактивного режима

```python
console_manager = ConsoleManager(
    manager_name="MyConsole",
    command_manager=command_manager,
    enabled=True,
    interactive=True
)

console_manager.initialize()

# Теперь можно вводить команды в консоли
# Команды обрабатываются через CommandManager
```

### Обработка команд

Команды из интерактивной консоли автоматически обрабатываются через CommandManager:

```python
# В консоли вводим команду
# > help

# Команда обрабатывается через CommandManager
# Результат отображается в консоли
```

## Перенаправление stdout/stderr

Перенаправление позволяет автоматически перенаправлять весь вывод в консоль.

### Включение перенаправления

```python
console_manager = ConsoleManager(
    manager_name="MyConsole",
    enabled=True,
    redirect_enabled=True
)

console_manager.initialize()

# Теперь весь вывод перенаправляется в консоль
print("This will appear in console")
import sys
sys.stdout.write("This too\n")
```

### Ручное управление

```python
console_manager = ConsoleManager(
    manager_name="MyConsole",
    enabled=True
)

console_manager.initialize()

# Включить перенаправление
console_manager.setup_redirect(enabled=True)

# Выключить перенаправление
console_manager.setup_redirect(enabled=False)
```

## Интеграция с RouterManager

### Регистрация каналов

```python
router_manager = RouterManager("Router")
console_manager = ConsoleManager(
    manager_name="MyConsole",
    router_manager=router_manager,
    enabled=True
)

console_manager.initialize()

# Регистрация каналов
channels = console_manager.register_in_router(router_manager, prefix="console")
print(f"Registered channels: {channels}")
```

### Отправка через роутер

```python
# Отправка сообщения через роутер
router_manager.send({
    'channel': 'console.MyConsole',
    'text': 'Message from router',
    'level': 'INFO',
    'timestamp': True
})
```

### Формат сообщений

```python
message = {
    'text': 'Текст сообщения',           # Обязательно
    'level': 'INFO',                     # INFO, WARNING, ERROR, DEBUG
    'timestamp': True,                    # Добавить временную метку
    'process': 'ProcessName',            # Имя процесса (опционально)
    'console': 'ConsoleName'              # Имя консоли (опционально)
}

router_manager.send({
    'channel': 'console.MyConsole',
    **message
})
```

## Интеграция с CommandManager

### Обработка команд из консоли

```python
from multiprocess_framework.refactored.modules.command_module import CommandManager

command_manager = CommandManager("Commands")
command_manager.initialize()

# Регистрация команды
@command_manager.register_command("hello")
def hello_command(message):
    return "Hello from command!"

console_manager = ConsoleManager(
    manager_name="MyConsole",
    command_manager=command_manager,
    enabled=True,
    interactive=True
)

console_manager.initialize()

# Теперь в интерактивной консоли можно ввести:
# > hello
# Результат: Hello from command!
```

## Примеры использования

### Пример 1: Простая консоль

```python
from multiprocess_framework.refactored.modules.console_module import ConsoleManager

console_manager = ConsoleManager(
    manager_name="SimpleConsole",
    enabled=True
)

console_manager.initialize()

# Отправка сообщений
console_manager.send_message("Starting application...", level="INFO")
console_manager.send_message("Application started", level="INFO")

console_manager.shutdown()
```

### Пример 2: Консоль с перенаправлением

```python
console_manager = ConsoleManager(
    manager_name="RedirectConsole",
    enabled=True,
    redirect_enabled=True
)

console_manager.initialize()

# Весь вывод перенаправляется
print("This goes to console")
import logging
logging.info("This too")

console_manager.shutdown()
```

### Пример 3: Интерактивная консоль

```python
from multiprocess_framework.refactored.modules.command_module import CommandManager

command_manager = CommandManager("Commands")
command_manager.initialize()

@command_manager.register_command("status")
def status_command(message):
    return "System is running"

console_manager = ConsoleManager(
    manager_name="InteractiveConsole",
    command_manager=command_manager,
    enabled=True,
    interactive=True
)

console_manager.initialize()

# В консоли можно вводить команды
# > status
# System is running

console_manager.shutdown()
```

### Пример 4: Отдельный процесс для отладки

```python
from multiprocess_framework.refactored.modules.process_manager_module import ProcessManagerCore
from multiprocess_framework.refactored.modules.router_module import RouterManager
from multiprocess_framework.refactored.modules.command_module import CommandManager

# Инициализация менеджеров
process_manager = ProcessManagerCore("ProcessManager")
router_manager = RouterManager("Router")
command_manager = CommandManager("Commands")

process_manager.initialize()
router_manager.initialize()
command_manager.initialize()

# Создание консольного менеджера
console_manager = ConsoleManager(
    manager_name="MainConsole",
    command_manager=command_manager,
    router_manager=router_manager
)
console_manager.initialize()

# Создание отдельного процесса для отладки
console_manager.create_debug_process(
    process_name="DebugConsole",
    process_manager=process_manager,
    router_manager=router_manager,
    command_manager=command_manager
)

# Отправка сообщений в отдельный процесс
router_manager.send({
    'channel': 'console.DebugConsole',
    'text': 'Debug message',
    'level': 'INFO'
})

console_manager.shutdown()
```

## Лучшие практики

1. **Всегда вызывайте `initialize()`** перед использованием консоли
2. **Всегда вызывайте `shutdown()`** при завершении работы
3. **Используйте уровни логирования** для лучшей организации вывода
4. **Регистрируйте каналы в RouterManager** для межпроцессного взаимодействия
5. **Используйте отдельный процесс** только для отладки, не для продакшена

## Обработка ошибок

```python
try:
    console_manager = ConsoleManager(manager_name="MyConsole")
    console_manager.initialize()
    
    if not console_manager.send_message("Test"):
        print("Failed to send message")
    
except Exception as e:
    print(f"Error: {e}")
finally:
    if console_manager.is_initialized:
        console_manager.shutdown()
```

