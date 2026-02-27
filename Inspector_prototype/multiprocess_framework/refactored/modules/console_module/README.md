# Console Module (Refactored)

Модуль управления консольными окнами с интеграцией всех модулей системы.

## 🚀 Особенности

- ✅ **Два режима работы**: встроенный в процессе + отдельный процесс для отладки
- ✅ **Интеграция с BaseManager** - единообразие со всеми менеджерами
- ✅ **Интерактивный режим** - ввод команд через консоль
- ✅ **Интеграция с CommandManager** - обработка команд
- ✅ **Интеграция с RouterManager** - отправка сообщений через роутер
- ✅ **Перенаправление stdout/stderr** - автоматическое перенаправление вывода
- ✅ **Опциональное включение/выключение** - можно включать только когда нужно

## 📋 Режимы работы

### 1. Встроенный режим (в процессе)

Консоль работает внутри процесса:
- Опционально включается/выключается
- Перенаправляет stdout/stderr
- Интерактивный ввод команд (опционально)
- Отправка сообщений через print или API

### 2. Отдельный процесс (для отладки)

Создается отдельный процесс через ProcessManager:
- Только прием сообщений и вывод
- Использует CommandManager для обработки команд
- Использует RouterManager для отправки сообщений
- Без лишних воркеров

## 💡 Быстрый старт

### Встроенный режим

```python
from multiprocess_framework.refactored.modules.console_module import ConsoleManager

# Создание менеджера
console_manager = ConsoleManager(
    manager_name="ConsoleManager",
    command_manager=command_manager,
    router_manager=router_manager
)

# Инициализация
console_manager.initialize()

# Включить консоль
console_manager.enable_console(enabled=True)

# Настроить перенаправление stdout/stderr
console_manager.setup_redirect(enabled=True)

# Отправить сообщение
console_manager.send_message("Hello", level="INFO")

# Теперь print автоматически перенаправляется
print("Hello from print")
```

### Отдельный процесс для отладки

```python
# Создать отдельный процесс через ProcessManager
console_manager.create_debug_process(
    process_name="DebugConsole",
    process_manager=process_manager,
    router_manager=router_manager,
    command_manager=command_manager
)

# Отправка через роутер
router_manager.send({
    'channel': 'console.DebugConsole',
    'text': 'Debug message',
    'level': 'INFO'
})
```

### Интерактивный режим

```python
# Включить интерактивный режим
console_manager.enable_interactive(enabled=True)

# Команды обрабатываются через CommandManager
# Пользователь вводит команды в консоли
```

## 📖 Документация

Подробная документация находится в папке `docs/`:
- `ARCHITECTURE.md` - архитектура модуля
- `USAGE_GUIDE.md` - руководство пользователя
- `API_REFERENCE.md` - справочник API

## 🔗 Интеграция

Модуль интегрируется с:
- `base_manager` - для единообразия со всеми менеджерами
- `command_module` - для обработки команд
- `router_module` - для отправки сообщений
- `process_manager_module` - для создания отдельного процесса

