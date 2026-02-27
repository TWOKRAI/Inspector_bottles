# Отчет о рефакторинге ConsoleModule

## Статус: ✅ Основные компоненты созданы

## Выполненные задачи

### 1. Структура модуля ✅
- Создана новая структура в `refactored/modules/console_module`
- Организованы директории: `core/`, `channels/`, `redirectors/`, `processes/`, `adapters/`, `docs/`, `tests/`

### 2. ConsoleRedirector ✅
- Реализован класс для перенаправления stdout/stderr
- Поддержка множественных получателей (дублирование в несколько консолей)
- Методы для восстановления оригинальных потоков

### 3. ConsoleChannel ✅
- Реализован канал для RouterManager
- Наследуется от MessageChannel из router_module
- Поддержка форматирования сообщений (уровни, временные метки)
- Интеграция с ConsoleManager

### 4. ConsoleManager ✅
- Наследуется от BaseManager и ObservableMixin
- Два режима работы:
  - Встроенный режим: консоль в процессе (опционально включается/выключается)
  - Отдельный процесс: создается через ProcessManager для отладки
- Интеграция с CommandManager для обработки команд
- Интеграция с RouterManager для отправки сообщений
- Перенаправление stdout/stderr
- Интерактивный режим с вводом команд
- Поток для отображения вывода

### 5. ConsoleWindowProcess ✅
- Процесс окна консоли для отдельного процесса отладки
- Поддержка Windows и Unix систем
- Чтение из Queue и отображение в консоли

### 6. Интерфейсы ✅
- Создан интерфейс `IConsoleManager` для менеджера консоли
- Создан интерфейс `IConsoleChannel` для канала консоли

## Архитектурные решения

### Гибридный подход
- **Встроенный режим**: консоль работает в процессе, опционально включается/выключается
- **Отдельный процесс**: создается через ProcessManager для отладки, использует ProcessModule

### Интеграция с модулями
- **CommandManager**: обработка команд из интерактивной консоли
- **RouterManager**: отправка сообщений через каналы консоли
- **ProcessManager**: создание отдельного процесса для отладки

### Каналы
- Каждый модуль создает свой канал в своей папке `channels/`
- Канал наследуется от `MessageChannel` из `router_module`
- Канал регистрируется в RouterManager через `register_channel()`
- Универсально и удобно - каждый модуль отвечает за свой канал

## Структура файлов

```
console_module/
├── __init__.py
├── README.md
├── ARCHITECTURE_PLAN.md
├── REFACTORING_SUMMARY.md
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
│   └── window_process.py       # Процесс окна консоли
├── adapters/                   # Адаптеры (если нужны)
├── interfaces.py               # Интерфейсы
├── docs/                       # Документация
└── tests/                      # Тесты
```

## Использование

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

## Тесты ✅

Созданы тесты для всех компонентов:

- **test_console_manager.py** - тесты для ConsoleManager
  - Инициализация и завершение работы
  - Включение/выключение консоли
  - Отправка сообщений
  - Перенаправление stdout/stderr
  - Интерактивный режим
  - Регистрация в RouterManager

- **test_console_channel.py** - тесты для ConsoleChannel
  - Инициализация канала
  - Отправка сообщений
  - Форматирование сообщений
  - Обработка ошибок

- **test_console_redirector.py** - тесты для ConsoleRedirector
  - Инициализация с одной/несколькими очередями
  - Запись данных
  - Сброс буфера
  - Закрытие и восстановление

## Документация ✅

Создана полная документация:

- **README.md** - обзор модуля, быстрый старт, структура
- **USAGE_GUIDE.md** - подробное руководство по использованию
  - Встроенный режим
  - Отдельный процесс для отладки
  - Интерактивный режим
  - Перенаправление stdout/stderr
  - Интеграция с RouterManager и CommandManager
  - Примеры использования
- **API_REFERENCE.md** - полный справочник API
  - ConsoleManager
  - ConsoleChannel
  - ConsoleRedirector
  - ConsoleWindowProcess
  - Интерфейсы

## Следующие шаги

1. ✅ Основные компоненты созданы
2. ✅ Создать тесты
3. ✅ Создать документацию
4. ⏳ Адаптеры (не требуются по запросу пользователя)
5. ⏳ Доработать интерактивный режим (полная реализация чтения команд)
6. ⏳ Доработать create_debug_process (интеграция с ProcessManager)

## Примечания

- Каналы хранятся в RouterManager, каждый модуль создает свой канал
- Отдельный процесс консоли создается через ProcessManager (используя ProcessModule)
- Интерактивный режим читает команды из stdin и обрабатывает через CommandManager
- Перенаправление stdout/stderr работает автоматически при включении

