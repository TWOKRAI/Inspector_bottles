# Command Module (Refactored)

Модуль управления командами с интеграцией BaseManager и ObservableMixin.

## Описание

CommandModule предоставляет систему управления командами, которая позволяет:
- Регистрировать обработчики команд
- Выполнять команды с различными стратегиями диспетчеризации
- Управлять метаданными и тегами команд
- Интегрироваться с системой логирования, статистики и обработки ошибок
- Работать со сценариями выполнения команд

## Основные компоненты

1. **BaseCommandManager** - абстрактный базовый класс, определяющий интерфейс
2. **CommandManager** - основная реализация менеджера команд
3. **CommandAdapter** - адаптер для упрощенной работы с командами

## Быстрый старт

```python
from multiprocess_framework.refactored.modules.command_module import CommandManager

# Создание менеджера
manager = CommandManager("my_process")

# Инициализация
manager.initialize()

# Регистрация команды
def greet_handler(data):
    return f"Hello, {data.get('name', 'World')}!"

manager.register_command("greet", greet_handler)

# Выполнение команды
result = manager.handle_command({"command": "greet", "data": {"name": "Alice"}})
print(result)  # "Hello, Alice!"

# Завершение работы
manager.shutdown()
```

## Архитектура

```
CommandManager
├── BaseManager (жизненный цикл, адаптеры, события)
├── ObservableMixin (логирование, статистика, ошибки)
├── ICommandManager (интерфейс)
└── Dispatcher (диспетчеризация команд)
    ├── EXACT_MATCH
    ├── PATTERN_MATCH
    ├── FALLBACK_MATCH
    └── CHAIN_MATCH
```

## Структура модуля

```
command_module/
├── __init__.py              # Экспорт основных классов
├── README.md                # Основная документация
├── interfaces.py            # Интерфейсы модуля
├── core/                    # Основные классы
│   ├── base_command_manager.py  # Базовый класс
│   └── command_manager.py   # Основной менеджер
├── adapters/                # Адаптеры
│   └── command_adapter.py   # Адаптер команд
├── docs/                    # Документация
│   ├── README.md           # Навигация по документации
│   ├── USAGE_GUIDE.md      # Руководство по использованию
│   ├── ARCHITECTURE.md     # Архитектура модуля
│   └── API_REFERENCE.md    # Справочник API
└── tests/                  # Тесты
    ├── test_command_manager.py  # Тесты CommandManager
    ├── test_command_adapter.py   # Тесты CommandAdapter
    └── test_base_command_manager.py  # Тесты BaseCommandManager
```

## Документация

См. `docs/` для детальной документации:
- `docs/USAGE_GUIDE.md` - Подробное руководство по использованию с примерами
- `docs/ARCHITECTURE.md` - Архитектура модуля
- `docs/API_REFERENCE.md` - Справочник API

## Тесты

Тесты находятся в `tests/`:
- `test_command_manager.py` - Тесты для CommandManager
- `test_command_adapter.py` - Тесты для CommandAdapter
- `test_base_command_manager.py` - Тесты для BaseCommandManager

Запуск тестов:
```bash
python -m pytest tests/ -v
```

## Интеграция

### С BaseManager

CommandManager наследуется от BaseManager, что обеспечивает:
- Стандартный жизненный цикл (initialize/shutdown)
- Поддержку адаптеров
- Поддержку событий
- Автоматическую статистику

### С ObservableMixin

CommandManager использует ObservableMixin для:
- Автоматического логирования операций
- Сбора метрик производительности
- Отслеживания и обработки ошибок

### С Dispatcher

CommandManager использует Dispatcher для диспетчеризации команд:
- Поддержка всех стратегий диспетчеризации
- Работа со сценариями
- Гибкая маршрутизация команд

## Обратная совместимость

- ✅ Старый API продолжает работать
- ✅ Все методы доступны как раньше
- ✅ Параметры совместимы

## Лицензия

См. основную лицензию проекта.

