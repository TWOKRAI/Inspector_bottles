# ObservableMixin - Быстрый старт

## Минимальный пример

```python
from multiprocess_framework.modules.Base_manager_module import ObservableMixin

class MyService(ObservableMixin):
    def __init__(self, logger=None):
        managers = {}
        if logger:
            managers['logger'] = logger
        ObservableMixin.__init__(self, managers=managers, config={'logger': True})
    
    def do_work(self):
        self._log_info("Выполняю работу")
        return "done"
```

## Основные методы

### Логирование
```python
self._log_debug("Отладочное сообщение")
self._log_info("Информационное сообщение")
self._log_warning("Предупреждение")
self._log_error("Ошибка")
```

### Статистика
```python
self._record_metric("operations.count", value=1, tags={"type": "api"})
self._record_timing("operation.duration", duration=1.5, tags={"endpoint": "/users"})
```

### Ошибки
```python
try:
    result = risky_operation()
except Exception as e:
    self._track_error(e, {"context": "operation"})
    raise
```

### Управление состоянием
```python
obj.enable('logger')      # Включить
obj.disable('logger')     # Выключить
obj.is_enabled('logger')  # Проверить

# Временно отключить
with obj.context('logger', enabled=False):
    sensitive_operation()
```

## Декораторы

```python
@ObservableMixin.logged(level='info')
def my_method(self):
    pass

@ObservableMixin.timed(metric_name='operation.time')
def my_method(self):
    pass

@ObservableMixin.monitored(level='info', metric_name='operation')
def my_method(self):
    pass
```

## Полная документация

См. [README.md](README.md) для полной документации.

