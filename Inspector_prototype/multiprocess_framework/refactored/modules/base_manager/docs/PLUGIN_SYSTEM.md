# Плагин-система для ObservableMixin

## Обзор

Плагин-система позволяет расширять функциональность ObservableMixin без изменения основного кода. Это особенно полезно для:
- Кастомных менеджеров с уникальными методами
- Специфичных интеграций между менеджерами
- Расширения функциональности для конкретных случаев использования

## Архитектура

```
ObservableMixin
    ├── PluginRegistry (управление плагинами)
    ├── ObservablePlugin (базовый класс плагина)
    └── BuiltinPlugins (встроенные плагины для стандартных менеджеров)
```

## Создание плагина

### Базовый пример

```python
from multiprocess_framework.refactored.modules.base_manager.mixins.plugins import ObservablePlugin

class CustomLoggerPlugin(ObservablePlugin):
    """Плагин для кастомного логгера."""
    
    def get_manager_names(self) -> list[str]:
        """Имена менеджеров, которые поддерживает плагин."""
        return ['custom_logger']
    
    def create_proxy_methods(self, instance, managers, call_manager_func):
        """Создать публичные прокси-методы."""
        if 'custom_logger' in managers:
            instance.custom_log = lambda msg: call_manager_func('custom_logger', 'log', msg)
            instance.custom_debug = lambda msg: call_manager_func('custom_logger', 'debug', msg)
    
    def create_private_methods(self, instance, call_manager_func):
        """Создать приватные методы."""
        instance._custom_log = lambda msg: call_manager_func('custom_logger', 'log', msg)
```

### Использование плагина

```python
from multiprocess_framework.refactored.modules.base_manager import BaseManager, ObservableMixin

class MyManager(BaseManager, ObservableMixin):
    def __init__(self, name, custom_logger=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={'custom_logger': custom_logger},
            plugins=[CustomLoggerPlugin()]  # Регистрируем плагин
        )
    
    def process(self):
        # Используем методы, созданные плагином
        self.custom_log("Custom log message")
        self._custom_log("Private method also works")
        return "result"
```

## Методы плагина

### get_manager_names()

Возвращает список имен менеджеров, которые поддерживает плагин.

```python
def get_manager_names(self) -> list[str]:
    return ['my_manager', 'another_manager']
```

### create_proxy_methods()

Создает публичные методы-прокси для менеджеров.

```python
def create_proxy_methods(self, instance, managers, call_manager_func):
    if 'my_manager' in managers:
        instance.my_method = lambda arg: call_manager_func('my_manager', 'method', arg)
```

### create_private_methods()

Создает приватные методы для менеджеров.

```python
def create_private_methods(self, instance, call_manager_func):
    instance._my_private_method = lambda arg: call_manager_func('my_manager', 'method', arg)
```

### create_decorators()

Создает декораторы для менеджеров.

```python
def create_decorators(self, instance, call_manager_func):
    def my_decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            call_manager_func('my_manager', 'before', func.__name__)
            result = func(*args, **kwargs)
            call_manager_func('my_manager', 'after', func.__name__)
            return result
        return wrapper
    
    instance.my_decorator = my_decorator
```

## Примеры использования

### Пример 1: Кастомный логгер

```python
class CustomLoggerPlugin(ObservablePlugin):
    def get_manager_names(self):
        return ['custom_logger']
    
    def create_proxy_methods(self, instance, managers, call_manager_func):
        if 'custom_logger' in managers:
            instance.log_custom = lambda level, msg: call_manager_func(
                'custom_logger', 'log', level, msg
            )

# Использование
manager = MyManager("test", custom_logger=my_logger)
manager.log_custom("INFO", "Message")
```

### Пример 2: Менеджер метрик

```python
class MetricsPlugin(ObservablePlugin):
    def get_manager_names(self):
        return ['metrics']
    
    def create_proxy_methods(self, instance, managers, call_manager_func):
        if 'metrics' in managers:
            instance.count = lambda name: call_manager_func('metrics', 'count', name)
            instance.gauge = lambda name, value: call_manager_func('metrics', 'gauge', name, value)
            instance.histogram = lambda name, value: call_manager_func('metrics', 'histogram', name, value)
    
    def create_decorators(self, instance, call_manager_func):
        def count_calls(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                call_manager_func('metrics', 'count', f"{func.__name__}.calls")
                return func(*args, **kwargs)
            return wrapper
        
        instance.count_calls = count_calls

# Использование
@manager.count_calls
def my_function():
    pass
```

### Пример 3: Комплексный плагин для процесса

```python
class ProcessPlugin(ObservablePlugin):
    """Плагин для интеграции с процессом."""
    
    def get_manager_names(self):
        return ['process']
    
    def create_proxy_methods(self, instance, managers, call_manager_func):
        if 'process' in managers:
            instance.send_to_process = lambda msg: call_manager_func('process', 'send', msg)
            instance.get_process_state = lambda: call_manager_func('process', 'get_state')
            instance.restart_process = lambda: call_manager_func('process', 'restart')
    
    def create_private_methods(self, instance, call_manager_func):
        instance._process_send = lambda msg: call_manager_func('process', 'send', msg)
        instance._process_get_state = lambda: call_manager_func('process', 'get_state')

# Использование
manager = ProcessManager("test", process=my_process)
manager.send_to_process("message")
state = manager.get_process_state()
```

## Динамическая регистрация плагинов

Плагины можно регистрировать динамически:

```python
manager = MyManager("test")

# Регистрируем плагин после создания
plugin = CustomLoggerPlugin()
manager.register_plugin(plugin)

# Теперь доступны методы плагина
manager.custom_log("Message")
```

## Встроенные плагины

ObservableMixin использует встроенные плагины для стандартных менеджеров:
- `LoggerPlugin` - для 'logger'
- `StatsPlugin` - для 'stats' и 'statistics'
- `ErrorPlugin` - для 'error' и 'errors'

Эти плагины применяются автоматически при `auto_proxy=True`.

## Преимущества плагин-системы

1. **Расширяемость** - легко добавлять новую функциональность
2. **Изоляция** - плагины не влияют на основной код
3. **Переиспользование** - плагины можно использовать в разных менеджерах
4. **Гибкость** - разные менеджеры могут использовать разные плагины
5. **Тестируемость** - плагины легко тестировать отдельно

## Рекомендации

1. **Один плагин - одна ответственность** - плагин должен решать одну задачу
2. **Используйте имена менеджеров** - четко указывайте какие менеджеры поддерживает плагин
3. **Обработка ошибок** - плагины должны gracefully обрабатывать отсутствие менеджеров
4. **Документация** - документируйте какие методы создает плагин





