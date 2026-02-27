# Архитектура CommandModule

## Обзор

CommandModule предоставляет систему управления командами с интеграцией BaseManager и ObservableMixin.

## Архитектурные компоненты

### Основные классы

**Расположение:** `core/`

- **BaseCommandManager** - базовый абстрактный класс для командных менеджеров
- **CommandManager** - основная реализация менеджера команд

### Адаптеры

**Расположение:** `adapters/`

- **CommandAdapter** - адаптер для интеграции с процессом

### Интерфейсы

**Расположение:** `interfaces.py`

- **ICommandManager** - интерфейс для командных менеджеров

## Архитектурная диаграмма

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

## Поток выполнения команды

### 1. Регистрация команды

```
register_command()
  → Dispatcher.register_handler()
  → Сохранение обработчика в диспетчере
  → Логирование через ObservableMixin
```

### 2. Выполнение команды

```
handle_command(message)
  → Извлечение имени команды из сообщения
  → Dispatcher.dispatch()
  → Выполнение обработчика
  → Логирование и статистика через ObservableMixin
  → Возврат результата
```

## Интеграция с BaseManager

CommandManager наследуется от BaseManager, что обеспечивает:

- **Жизненный цикл** - стандартные методы initialize/shutdown
- **Адаптеры** - поддержка адаптеров через attach_adapter()
- **События** - поддержка событий через on_event() и emit_event()
- **Статистика** - автоматический сбор статистики через get_stats()

## Интеграция с ObservableMixin

CommandManager использует ObservableMixin для:

- **Логирование** - автоматическое логирование операций через `_log_*` методы
- **Статистика** - сбор метрик через `_record_metric` и `_record_timing`
- **Обработка ошибок** - отслеживание ошибок через `_track_error`

## Интеграция с Dispatcher

CommandManager использует Dispatcher для диспетчеризации команд:

- Все стратегии диспетчеризации доступны
- Работа со сценариями через dispatcher
- Гибкая маршрутизация команд

## Расширяемость

### Создание кастомного командного менеджера

```python
from ..core.base_command_manager import BaseCommandManager
from ...base_manager import BaseManager, ObservableMixin

class CustomCommandManager(BaseManager, ObservableMixin, BaseCommandManager):
    def __init__(self, manager_name, process=None, **kwargs):
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        ObservableMixin.__init__(self, **kwargs)
        BaseCommandManager.__init__(self, manager_name)
        # Дополнительная инициализация
    
    def initialize(self) -> bool:
        # Реализация инициализации
        pass
    
    def shutdown(self) -> bool:
        # Реализация завершения
        pass
    
    def register_command(self, command_name, handler, **kwargs) -> bool:
        # Реализация регистрации
        pass
    
    def handle_command(self, message) -> Any:
        # Реализация выполнения
        pass
    
    def get_commands(self) -> List[Dict]:
        # Реализация получения списка
        pass
```

### Использование интерфейсов

```python
from ..interfaces import ICommandManager

class CustomCommandManager(ICommandManager):
    # Реализация интерфейса
    pass
```

## Производительность

### Сложность операций

- **Регистрация команды**: O(1) - делегируется Dispatcher
- **Выполнение команды**: O(1) для EXACT_MATCH, O(n) для PATTERN_MATCH
- **Получение списка команд**: O(n) где n - количество команд

### Рекомендации

1. Используйте EXACT_MATCH для максимальной производительности
2. Используйте PATTERN_MATCH только когда необходимо
3. Группируйте команды по тегам для удобства управления

## Потоки данных

### Регистрация команды

```
CommandManager.register_command()
  → Dispatcher.register_handler()
  → Сохранение в хранилище диспетчера
  → Логирование через ObservableMixin
```

### Выполнение команды

```
Message → CommandManager.handle_command()
  → Dispatcher.dispatch()
  → Поиск обработчика
  → Выполнение обработчика
  → Логирование и статистика
  → Результат
```

## Безопасность

- Валидация команд перед выполнением
- Обработка ошибок на всех уровнях
- Логирование всех операций через ObservableMixin

## Тестируемость

Модуль разработан с учетом тестируемости:

- Разделение на базовые классы и реализации
- Интерфейсы позволяют создавать моки для тестирования
- ObservableMixin можно отключить для unit-тестов

## Дополнительные ресурсы

- [USAGE_GUIDE.md](USAGE_GUIDE.md) - Руководство по использованию
- [API_REFERENCE.md](API_REFERENCE.md) - Справочник API

