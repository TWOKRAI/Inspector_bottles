# Руководство по использованию ObservableMixin

## Обзор

`ObservableMixin` предоставляет универсальный способ интеграции логирования, обработки ошибок и статистики в любые классы без усложнения основного функционала.

## Основные возможности

1. **Опциональная интеграция** - менеджеры передаются опционально, класс работает и без них
2. **Включение/выключение в реальном времени** - можно управлять функциями динамически
3. **Контекстные менеджеры** - временное изменение состояния
4. **Декораторы** - автоматическое логирование и статистика методов
5. **Безопасность** - ошибки в менеджерах не ломают основной функционал

## Базовое использование

### Простое использование (без менеджеров)

```python
# Работает как обычно, без дополнительных зависимостей
dispatcher = Dispatcher("my_dispatcher")
dispatcher.register_handler("test", lambda data: {"result": "ok"})
result = dispatcher.dispatch({"command": "test", "data": {}})
```

### С менеджерами

```python
from src.Modules.Dispatch_module import Dispatcher
from src.Modules.Logger_module import LoggerManager, LogConfig

# Инициализация менеджеров
logger_manager = LoggerManager(LogConfig(app_name="my_app"))
# error_manager = ErrorManager(...)  # Когда будет реализован
# stats_manager = StatisticsManager(...)  # Когда будет реализован

# Создание диспетчера с менеджерами
dispatcher = Dispatcher(
    "my_dispatcher",
    logger_manager=logger_manager,
    # error_manager=error_manager,
    # statistics_manager=stats_manager
)
```

## Управление состоянием

### Включение/выключение функций

```python
# Включить/выключить логирование
dispatcher.enable_logging(True)   # Включить
dispatcher.enable_logging(False)  # Выключить

# Проверить состояние
if dispatcher.is_logging_enabled():
    print("Логирование включено")

# Аналогично для других функций
dispatcher.enable_error_tracking(True)
dispatcher.enable_statistics(True)
```

### Контекстные менеджеры (временное изменение)

```python
# Временно отключить логирование для конкретной операции
with dispatcher.logging_context(enabled=False):
    result = dispatcher.dispatch(sensitive_message)

# Временно включить статистику
with dispatcher.statistics_context(enabled=True):
    result = dispatcher.dispatch(message)

# Комбинированное использование
with dispatcher.logging_context(enabled=False), \
     dispatcher.statistics_context(enabled=True):
    result = dispatcher.dispatch(message)
```

## Декораторы для методов

### Автоматическое логирование

```python
class MyHandler:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
    
    @dispatcher.logged(level="info", log_args=True, log_result=True)
    def process_data(self, data):
        return {"processed": data}
```

### Измерение времени выполнения

```python
@dispatcher.timed(metric_name="data_processing", tags={"type": "batch"})
def process_batch(self, items):
    # Обработка данных
    return results
```

### Комбинированный мониторинг

```python
@dispatcher.monitored(level="info", metric_name="critical_operation")
def critical_operation(self, data):
    # Критическая операция
    return result
```

## Использование в CommandManager

```python
from src.Modules.Command_module import CommandManager
from src.Modules.Dispatch_module import DispatchStrategy

# Создание с менеджерами
manager = CommandManager(
    "my_process",
    logger_manager=logger_manager,
    statistics_manager=stats_manager,
    enable_logging=True,
    enable_statistics=True
)

# Регистрация команды (автоматически логируется)
manager.register_command("process", handler)

# Выполнение команды (автоматически логируется и измеряется)
result = manager.handle_command({"command": "process", "data": {...}})

# Временно отключить логирование
with manager.logging_context(enabled=False):
    result = manager.handle_command(sensitive_command)
```

## Примеры сценариев

### Сценарий 1: Отладка в продакшене

```python
# Включить детальное логирование только для отладки
dispatcher.enable_logging(True)
dispatcher._log_debug("Debug message", module="my_module")

# После отладки выключить
dispatcher.enable_logging(False)
```

### Сценарий 2: Мониторинг производительности

```python
# Включить статистику для измерения производительности
dispatcher.enable_statistics(True)

# Выполнить операции
for i in range(100):
    dispatcher.dispatch(messages[i])

# Получить статистику (когда будет реализован StatisticsManager)
# stats = dispatcher._statistics_manager.get_stats()
```

### Сценарий 3: Обработка ошибок

```python
# Включить отслеживание ошибок
dispatcher.enable_error_tracking(True)

try:
    result = dispatcher.dispatch(message)
except Exception as e:
    # Ошибка автоматически отслеживается через _track_error
    pass

# Получить статистику ошибок (когда будет реализован ErrorManager)
# errors = dispatcher._error_manager.get_recent_errors()
```

## Интерфейсы менеджеров

Для совместимости менеджеры должны поддерживать следующие методы:

### LoggerManager
- `debug(message, module="main", **extra)`
- `info(message, module="main", **extra)`
- `warning(message, module="main", **extra)`
- `error(message, module="main", **extra)`

### ErrorManager (будущий)
- `track_error(error: Exception, context: Dict)`
- или `record_error(error: Exception, context: Dict)`

### StatisticsManager (будущий)
- `record_metric(name: str, value: Any, tags: Dict)`
- или `increment(name: str, tags: Dict)`
- `record_timing(name: str, duration: float, tags: Dict)`
- или `timing(name: str, duration: float, tags: Dict)`

## Преимущества подхода

1. **Не усложняет код** - все опционально, работает и без менеджеров
2. **Гибкость** - можно включать/выключать функции в реальном времени
3. **Безопасность** - ошибки в менеджерах не ломают основной функционал
4. **Расширяемость** - легко добавлять новые менеджеры
5. **Переиспользование** - один mixin для всех классов

## Рекомендации

1. **По умолчанию** - передавайте менеджеры только когда они нужны
2. **Конфигурация** - используйте конфиги для управления включением/выключением
3. **Производительность** - отключайте логирование в критичных местах
4. **Мониторинг** - включайте статистику для важных операций
5. **Ошибки** - всегда включайте отслеживание ошибок в продакшене

