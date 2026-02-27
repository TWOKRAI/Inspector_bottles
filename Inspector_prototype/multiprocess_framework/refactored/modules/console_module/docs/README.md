# ConsoleModule - Модуль управления консольными окнами

## Обзор

`ConsoleModule` предоставляет систему управления консольными окнами с интеграцией всех модулей системы. Поддерживает два режима работы: встроенный (консоль в процессе) и отдельный процесс для отладки.

## Основные возможности

- ✅ **Встроенный режим**: консоль в процессе (опционально включается/выключается)
- ✅ **Отдельный процесс**: создается через ProcessManager для отладки
- ✅ **Интеграция с CommandManager**: обработка команд из интерактивной консоли
- ✅ **Интеграция с RouterManager**: отправка сообщений через каналы консоли
- ✅ **Перенаправление stdout/stderr**: автоматическое перенаправление вывода
- ✅ **Интерактивный режим**: ввод команд и отображение результатов
- ✅ **Наследование от BaseManager**: единообразие со всеми менеджерами

## Структура модуля

```
console_module/
├── core/
│   └── console_manager.py      # Главный менеджер консоли
├── channels/
│   └── console_channel.py      # Канал для RouterManager
├── redirectors/
│   └── console_redirector.py   # Перенаправление stdout/stderr
├── processes/
│   └── window_process.py       # Процесс окна консоли
├── interfaces.py               # Интерфейсы
├── docs/                       # Документация
└── tests/                      # Тесты
```

## Быстрый старт

### Встроенный режим

```python
from multiprocess_framework.refactored.modules.console_module import ConsoleManager

# Создание менеджера
console_manager = ConsoleManager(
    manager_name="ConsoleManager",
    command_manager=command_manager,
    router_manager=router_manager,
    enabled=True,
    interactive=True,
    redirect_enabled=True
)

# Инициализация
console_manager.initialize()

# Отправка сообщения
console_manager.send_message("Hello", level="INFO")

# print автоматически перенаправляется
print("Hello from print")
```

### Отдельный процесс для отладки

```python
# Создать отдельный процесс
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

## Компоненты

### ConsoleManager

Главный менеджер консоли, наследуется от `BaseManager` и `ObservableMixin`.

**Основные методы:**
- `enable_console(enabled=True)` - включить/выключить консоль
- `send_message(text, level="INFO")` - отправить сообщение
- `setup_redirect(enabled=True)` - настроить перенаправление stdout/stderr
- `enable_interactive(enabled=True)` - включить интерактивный режим
- `register_in_router(router_manager)` - зарегистрировать каналы в RouterManager

### ConsoleChannel

Канал для отправки сообщений в консоль через RouterManager.

**Особенности:**
- Наследуется от `MessageChannel` из `router_module`
- Поддержка форматирования сообщений (уровни, временные метки)
- Интеграция с ConsoleManager

### ConsoleRedirector

Перенаправитель stdout/stderr в консоль.

**Особенности:**
- Поддержка множественных получателей (дублирование в несколько консолей)
- Методы для восстановления оригинальных потоков
- Работает как file-like объект

### ConsoleWindowProcess

Процесс окна консоли для отдельного процесса отладки.

**Особенности:**
- Поддержка Windows и Unix систем
- Чтение из Queue и отображение в консоли
- Используется для отдельного процесса консоли

## Интеграция

### С CommandManager

```python
# Интерактивный режим автоматически обрабатывает команды через CommandManager
console_manager = ConsoleManager(
    command_manager=command_manager,
    enabled=True,
    interactive=True
)
```

### С RouterManager

```python
# Регистрация каналов
channels = console_manager.register_in_router(router_manager)

# Отправка через роутер
router_manager.send({
    'channel': 'console.ProcessName',
    'text': 'Message',
    'level': 'INFO'
})
```

### С ProcessManager

```python
# Создание отдельного процесса для отладки
console_manager.create_debug_process(
    process_name="DebugConsole",
    process_manager=process_manager,
    router_manager=router_manager,
    command_manager=command_manager
)
```

## Документация

- [USAGE_GUIDE.md](USAGE_GUIDE.md) - Подробное руководство по использованию
- [API_REFERENCE.md](API_REFERENCE.md) - Справочник API

## Тесты

Все компоненты покрыты тестами:
- `test_console_manager.py` - тесты для ConsoleManager
- `test_console_channel.py` - тесты для ConsoleChannel
- `test_console_redirector.py` - тесты для ConsoleRedirector

## Версия

2.0.0

