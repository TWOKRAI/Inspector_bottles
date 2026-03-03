# Руководство по расширению менеджеров

## Обзор

`ManagerExtensionMixin` - это универсальный mixin для расширения функциональности менеджеров без нарушения их основной логики. Он позволяет легко добавлять возможности других менеджеров (логирование, статистика, ошибки и т.д.) к любому менеджеру.

## Основные возможности

- ✅ **Не нарушает логику класса** - только дополняет функциональность
- ✅ **Легко добавлять новые расширения** - простой API регистрации
- ✅ **Опциональность** - работает и без расширений
- ✅ **Единый интерфейс** - одинаковый подход для всех менеджеров
- ✅ **Автоматические прокси-методы** - удобные методы для стандартных расширений

## Быстрый старт

### Базовое использование

```python
from multiprocess_framework.modules.Base_manager_module.base_manager import BaseManager
from multiprocess_framework.modules.Base_manager_module.manager_extension_mixin import ManagerExtensionMixin

class MyManager(BaseManager, ManagerExtensionMixin):
    def __init__(self, name, logger=None, stats=None):
        # Инициализация базового менеджера
        BaseManager.__init__(self, name)
        
        # Инициализация расширений
        ManagerExtensionMixin.__init__(
            self,
            extensions={
                'logger': logger,
                'stats': stats
            }
        )
    
    def process(self):
        # Используем автоматически созданные методы-прокси
        self.log_info("Начинаю обработку")
        
        try:
            result = self.do_work()
            self.record_metric("operations.success")
            return result
        except Exception as e:
            self.log_error(f"Ошибка обработки: {e}")
            self.track_error(e)
            raise
```

## Стандартные расширения

### Логирование (logger)

Автоматически создаются методы:
- `log_debug(message, **kwargs)` - отладочное сообщение
- `log_info(message, **kwargs)` - информационное сообщение
- `log_warning(message, **kwargs)` - предупреждение
- `log_error(message, **kwargs)` - ошибка
- `log_critical(message, **kwargs)` - критическая ошибка

```python
# Регистрация logger расширения
ManagerExtensionMixin.__init__(
    self,
    extensions={'logger': logger_manager}
)

# Использование
self.log_info("Операция выполнена успешно")
self.log_error("Произошла ошибка", extra={"context": "processing"})
```

### Статистика (stats/statistics)

Автоматически создаются методы:
- `record_metric(name, value=1, tags=None)` - запись метрики
- `increment(name, tags=None)` - инкремент счетчика
- `record_timing(name, duration, tags=None)` - запись времени выполнения
- `gauge(name, value, tags=None)` - установка значения метрики

```python
# Регистрация stats расширения
ManagerExtensionMixin.__init__(
    self,
    extensions={'stats': stats_manager}
)

# Использование
self.record_metric("requests.count", value=1)
self.increment("operations.total")
self.record_timing("operation.duration", duration=0.5)
```

### Ошибки (errors/error)

Автоматически создаются методы:
- `track_error(error, context=None)` - отслеживание ошибки
- `record_error(error, context=None)` - запись ошибки

```python
# Регистрация errors расширения
ManagerExtensionMixin.__init__(
    self,
    extensions={'errors': error_manager}
)

# Использование
try:
    result = risky_operation()
except Exception as e:
    self.track_error(e, context={"operation": "risky"})
    raise
```

## Кастомные расширения

Вы можете добавить любое расширение и вызывать его методы через универсальный API:

```python
class MyManager(BaseManager, ManagerExtensionMixin):
    def __init__(self, name, custom_service=None):
        BaseManager.__init__(self, name)
        ManagerExtensionMixin.__init__(
            self,
            extensions={'custom': custom_service}
        )
    
    def use_custom(self):
        # Вызов метода кастомного расширения
        result = self.call_extension_method('custom', 'do_something', arg1, arg2)
        return result
```

## Управление расширениями

### Регистрация расширений

```python
# Регистрация нового расширения
self.register_extension('cache', cache_manager, enabled=True)

# Получение расширения
cache = self.get_extension('cache')

# Проверка наличия расширения
if self.has_extension('cache'):
    # Использование расширения
    pass
```

### Включение/выключение расширений

```python
# Включить расширение
self.enable_extension('logger', enabled=True)

# Выключить расширение
self.disable_extension('logger')

# Проверить состояние
if self.is_extension_enabled('logger'):
    self.log_info("Логирование включено")

# Получить список включенных расширений
enabled = self.get_enabled_extensions()
```

### Временное изменение состояния

```python
# Временно выключить логирование
with self.extension_context('logger', enabled=False):
    # Логирование выключено
    do_something()
# Логирование автоматически включится обратно
```

## Декораторы

### Автоматическое логирование

```python
class MyManager(BaseManager, ManagerExtensionMixin):
    @self.logged(extension_name='logger', level='info', log_args=True)
    def process(self, data):
        # Метод автоматически логируется
        return process_data(data)
```

### Автоматическое измерение времени

```python
class MyManager(BaseManager, ManagerExtensionMixin):
    @self.timed(extension_name='stats', metric_name='process.duration')
    def process(self, data):
        # Время выполнения автоматически записывается
        return process_data(data)
```

### Комбинированный мониторинг

```python
class MyManager(BaseManager, ManagerExtensionMixin):
    @self.monitored(logger_ext='logger', stats_ext='stats')
    def process(self, data):
        # Автоматически логируется и измеряется время
        return process_data(data)
```

## Сравнение с ObservableMixin

| Особенность | ObservableMixin | ManagerExtensionMixin |
|-------------|----------------|----------------------|
| Назначение | Специализированный для логирования/статистики/ошибок | Универсальный для любых расширений |
| Автоматические методы | Да (специфичные) | Да (универсальные + стандартные) |
| Кастомные расширения | Ограниченно | Полная поддержка |
| Гибкость | Средняя | Высокая |
| Простота использования | Высокая | Высокая |

**Рекомендация:** 
- Используйте `ObservableMixin` если нужны только логирование/статистика/ошибки
- Используйте `ManagerExtensionMixin` если нужна универсальная система расширений

## Примеры использования

### Пример 1: Менеджер с логированием и статистикой

```python
class DataProcessor(BaseManager, ManagerExtensionMixin):
    def __init__(self, name, logger=None, stats=None):
        BaseManager.__init__(self, name)
        ManagerExtensionMixin.__init__(
            self,
            extensions={
                'logger': logger,
                'stats': stats
            }
        )
    
    def process(self, data):
        self.log_info(f"Обработка данных: {len(data)} элементов")
        
        try:
            result = self._process_data(data)
            self.record_metric("processing.success", value=1)
            return result
        except Exception as e:
            self.log_error(f"Ошибка обработки: {e}")
            self.record_metric("processing.errors", value=1)
            raise
```

### Пример 2: Динамическое добавление расширений

```python
class FlexibleManager(BaseManager, ManagerExtensionMixin):
    def __init__(self, name):
        BaseManager.__init__(self, name)
        ManagerExtensionMixin.__init__(self, extensions={})
    
    def add_logger(self, logger):
        """Добавить логирование позже."""
        self.register_extension('logger', logger)
    
    def add_cache(self, cache):
        """Добавить кэш позже."""
        self.register_extension('cache', cache)
    
    def use_cache(self, key):
        """Использовать кэш если доступен."""
        if self.has_extension('cache'):
            return self.call_extension_method('cache', 'get', key)
        return None
```

## Лучшие практики

1. **Инициализация расширений в __init__** - регистрируйте расширения при создании менеджера
2. **Проверка наличия расширений** - всегда проверяйте наличие расширения перед использованием
3. **Обработка ошибок** - расширения могут быть недоступны, обрабатывайте это
4. **Использование декораторов** - используйте декораторы для автоматизации мониторинга
5. **Документирование расширений** - документируйте какие расширения использует ваш менеджер

## Заключение

`ManagerExtensionMixin` предоставляет мощный и гибкий механизм расширения функциональности менеджеров. Используйте его для создания модульных и расширяемых компонентов системы.

