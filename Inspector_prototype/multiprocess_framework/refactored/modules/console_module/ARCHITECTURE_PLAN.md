# План архитектуры ConsoleModule (Refactored)

## Оценка идеи: ✅ Отлично!

Архитектура гибкая и продуманная:
- ✅ Гибридный подход (встроенный + отдельный процесс)
- ✅ Интеграция с CommandManager для обработки команд
- ✅ Интеграция с RouterManager для отправки сообщений
- ✅ Интерактивность (ввод и вывод)
- ✅ Опциональное включение/выключение

## Архитектура

### Режимы работы

1. **Встроенный режим** (в процессе):
   - ConsoleManager создается в каждом процессе
   - Опционально включается/выключается
   - Перенаправляет stdout/stderr
   - Интерактивный ввод команд через CommandManager

2. **Отдельный процесс** (для отладки):
   - Создается через ProcessManager
   - Только прием сообщений и вывод
   - Использует CommandManager для обработки команд
   - Использует RouterManager для отправки сообщений

### Компоненты

```
ConsoleManager (BaseManager + ObservableMixin)
├── Режимы работы:
│   ├── Встроенный режим (в процессе)
│   └── Отдельный процесс (через ProcessManager)
├── Интеграция:
│   ├── CommandManager - обработка команд
│   ├── RouterManager - отправка сообщений
│   └── ProcessManager - создание отдельного процесса
├── Функциональность:
│   ├── Перенаправление stdout/stderr
│   ├── Интерактивный ввод команд
│   ├── Отправка сообщений через роутер
│   └── Отправка сообщений напрямую
└── Компоненты:
    ├── ConsoleChannel - канал для RouterManager
    ├── ConsoleRedirector - перенаправление вывода
    └── ConsoleProcess - отдельный процесс консоли
```

## Структура модуля

```
console_module/
├── __init__.py
├── ARCHITECTURE_PLAN.md
├── core/
│   ├── __init__.py
│   └── console_manager.py      # Главный менеджер
├── channels/
│   ├── __init__.py
│   └── console_channel.py      # Канал для RouterManager
├── redirectors/
│   ├── __init__.py
│   └── console_redirector.py   # Перенаправление stdout/stderr
├── processes/
│   ├── __init__.py
│   └── console_process.py      # Отдельный процесс консоли
├── adapters/
│   ├── __init__.py
│   └── console_adapter.py      # Адаптер для интеграции
├── interfaces.py               # Интерфейсы
├── docs/                       # Документация
└── tests/                      # Тесты
```

## API ConsoleManager

### Инициализация

```python
console_manager = ConsoleManager(
    manager_name="ConsoleManager",
    process=current_process,
    command_manager=command_manager,  # Для обработки команд
    router_manager=router_manager,     # Для отправки сообщений
    enabled=False,                     # По умолчанию выключен
    interactive=False                  # Интерактивный режим
)
```

### Встроенный режим

```python
# Включить консоль в процессе
console_manager.enable_console(enabled=True)

# Настроить перенаправление stdout/stderr
console_manager.setup_redirect(enabled=True)

# Отправить сообщение
console_manager.send_message("Hello", level="INFO")

# Отправить через print (автоматически перенаправляется)
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
```

### Интерактивный режим

```python
# Включить интерактивный режим
console_manager.enable_interactive(enabled=True)

# Команды обрабатываются через CommandManager
# Пользователь вводит команды в консоли
# Команды отправляются в CommandManager для обработки
```

### Интеграция с RouterManager

```python
# Зарегистрировать каналы в роутере
channels = console_manager.register_in_router(
    router_manager=router_manager,
    prefix="console"
)

# Отправка через роутер
router_manager.send({
    'channel': 'console.ProcessName',
    'text': 'Hello from router',
    'level': 'INFO'
})
```

## Поток данных

### Встроенный режим

```
print() / stdout
    ↓
ConsoleRedirector
    ↓
ConsoleManager.send_message()
    ↓
Отображение в консоли процесса
```

### Отдельный процесс

```
RouterManager.send()
    ↓
ConsoleChannel
    ↓
Queue (межпроцессная)
    ↓
ConsoleProcess (отдельный процесс)
    ↓
Отображение в консоли
```

### Интерактивный режим

```
Пользователь вводит команду
    ↓
ConsoleManager (читает ввод)
    ↓
CommandManager.handle_command()
    ↓
Результат → ConsoleManager.send_message()
    ↓
Отображение результата
```

## Интеграция с другими модулями

### CommandManager
- Обработка команд из интерактивной консоли
- Регистрация команд для консоли

### RouterManager
- Отправка сообщений в консоль через каналы
- Регистрация каналов консоли

### ProcessManager
- Создание отдельного процесса для отладки
- Управление жизненным циклом процесса консоли

## Преимущества архитектуры

1. **Гибкость**: два режима работы
2. **Интеграция**: работает со всеми модулями системы
3. **Простота**: опциональное включение/выключение
4. **Мощность**: интерактивный режим + перенаправление вывода
5. **Отладка**: отдельный процесс для отладки без лишних воркеров

