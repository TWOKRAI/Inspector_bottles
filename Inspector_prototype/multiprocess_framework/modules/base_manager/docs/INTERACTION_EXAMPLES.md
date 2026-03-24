# Примеры взаимодействия компонентов ObservableMixin

## Диаграмма взаимодействия

```
┌─────────────────────────────────────────────────────────────┐
│                    ObservableMixin                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐ │
│  │              ManagerRegistry                          │ │
│  │  - Регистрация менеджеров                             │ │
│  │  - Управление состоянием (enabled/disabled)          │ │
│  │  - Конфигурация                                       │ │
│  └──────────────────────────────────────────────────────┘ │
│                          │                                  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐ │
│  │              MethodCache                             │ │
│  │  - Кэширование методов менеджеров                   │ │
│  │  - Оптимизация вызовов                               │ │
│  └──────────────────────────────────────────────────────┘ │
│                          │                                  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐ │
│  │              _call_manager()                         │ │
│  │  - Универсальный вызов методов менеджеров            │ │
│  │  - Использует кэш для оптимизации                   │ │
│  └──────────────────────────────────────────────────────┘ │
│                          │                                  │
│        ┌─────────────────┼─────────────────┐              │
│        ▼                 ▼                 ▼              │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐           │
│  │ Logging  │    │  Stats   │    │  Error   │           │
│  │ Methods  │    │ Methods  │    │ Methods  │           │
│  └──────────┘    └──────────┘    └──────────┘           │
│        │                 │                 │              │
│        └─────────────────┼─────────────────┘              │
│                          │                                  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐ │
│  │              ProxyCreator                            │ │
│  │  - Создание публичных прокси-методов                │ │
│  │  - Использование встроенных плагинов                │ │
│  │  - Применение кастомных плагинов                    │ │
│  └──────────────────────────────────────────────────────┘ │
│                          │                                  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐ │
│  │              PluginRegistry                          │ │
│  │  - Регистрация плагинов                              │ │
│  │  - Индексация по менеджерам                         │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Примеры использования в разных сценариях

### Сценарий 1: Простой менеджер с логированием

```python
class SimpleManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={'logger': logger},
            config={'logger': True},
            auto_proxy=False  # Используем только приватные методы
        )
    
    def initialize(self) -> bool:
        self._log_info("Инициализация SimpleManager")
        self.is_initialized = True
        return True
    
    def do_work(self):
        self._log_info("Выполняю работу")
        # ... логика ...
        self._log_info("Работа завершена")
```

**Взаимодействие:**
1. `ObservableMixin.__init__()` → создает `ManagerRegistry` и `MethodCache`
2. `LoggingMethods.create_logging_methods()` → создает `_log_info()`, `_log_error()` и т.д.
3. При вызове `self._log_info()` → `_call_manager('logger', 'info', ...)`
4. `_call_manager()` → проверяет кэш → вызывает метод логгера

### Сценарий 2: Менеджер с логированием и статистикой

```python
class MonitoredManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None, stats=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={
                'logger': logger,
                'stats': stats
            },
            config={'logger': True, 'stats': True},
            auto_proxy=True  # Автоматические прокси-методы
        )
    
    def process_data(self, data):
        self.log_info("Начало обработки данных")
        self.record_metric("data.processed", value=len(data))
        
        try:
            result = self._process(data)
            self.record_metric("data.success")
            self.log_info("Обработка завершена успешно")
            return result
        except Exception as e:
            self.log_error(f"Ошибка обработки: {e}")
            self.record_metric("data.errors")
            raise
```

**Взаимодействие:**
1. `ObservableMixin.__init__()` → создает компоненты
2. `ProxyCreator.create_proxy_methods()` → создает `log_info()`, `record_metric()`
3. При вызове `self.log_info()` → прокси вызывает `_call_manager('logger', 'info', ...)`
4. `_call_manager()` → использует кэш → вызывает метод логгера
5. Аналогично для `record_metric()` → вызывает статистику

### Сценарий 3: Менеджер с кастомным плагином

```python
class CustomMetricsPlugin(ObservablePlugin):
    def get_manager_names(self):
        return ['custom_metrics']
    
    def create_proxy_methods(self, instance, managers, call_manager_func):
        if 'custom_metrics' in managers:
            instance.track_event = lambda name, data: call_manager_func(
                'custom_metrics', 'track', name, data
            )
            instance.record_duration = lambda name, duration: call_manager_func(
                'custom_metrics', 'duration', name, duration
            )

class AdvancedManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None, custom_metrics=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={
                'logger': logger,
                'custom_metrics': custom_metrics
            },
            plugins=[CustomMetricsPlugin()]  # Кастомный плагин
        )
    
    def handle_request(self, request):
        self._log_info(f"Обработка запроса: {request.id}")
        self.track_event("request.received", {"id": request.id})
        
        start_time = time.time()
        try:
            result = self._process_request(request)
            duration = time.time() - start_time
            
            self.record_duration("request.duration", duration)
            self.track_event("request.success", {"id": request.id})
            return result
        except Exception as e:
            self._log_error(f"Ошибка обработки запроса: {e}")
            self.track_event("request.error", {"id": request.id, "error": str(e)})
            raise
```

**Взаимодействие:**
1. `ObservableMixin.__init__()` → регистрирует плагин в `PluginRegistry`
2. `PluginRegistry.register()` → индексирует плагин по менеджерам
3. `CustomMetricsPlugin.create_proxy_methods()` → создает `track_event()`, `record_duration()`
4. При вызове `self.track_event()` → прокси вызывает `_call_manager('custom_metrics', 'track', ...)`
5. `_call_manager()` → использует кэш → вызывает метод менеджера метрик

### Сценарий 4: Процесс-менеджер с множеством менеджеров

```python
class ProcessManagerPlugin(ObservablePlugin):
    """Плагин для интеграции с процессом."""
    
    def get_manager_names(self):
        return ['process']
    
    def create_proxy_methods(self, instance, managers, call_manager_func):
        if 'process' in managers:
            instance.send_message = lambda msg: call_manager_func('process', 'send', msg)
            instance.get_process_info = lambda: call_manager_func('process', 'get_info')
            instance.restart = lambda: call_manager_func('process', 'restart')
    
    def create_decorators(self, instance, call_manager_func):
        def process_monitored(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                call_manager_func('process', 'before', func.__name__)
                try:
                    result = func(*args, **kwargs)
                    call_manager_func('process', 'after', func.__name__)
                    return result
                except Exception as e:
                    call_manager_func('process', 'error', func.__name__, str(e))
                    raise
            return wrapper
        
        instance.process_monitored = process_monitored

class ProcessManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None, stats=None, process=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={
                'logger': logger,
                'stats': stats,
                'process': process
            },
            config={'logger': True, 'stats': True, 'process': True},
            auto_proxy=True,
            plugins=[ProcessManagerPlugin()]
        )
    
    @process_monitored
    def start_process(self):
        self.log_info("Запуск процесса")
        self.send_message({"command": "start"})
        self.record_metric("process.started")
    
    def monitor_process(self):
        info = self.get_process_info()
        self.log_info(f"Состояние процесса: {info}")
        self.record_metric("process.monitored")
```

**Взаимодействие:**
1. Множество менеджеров регистрируются в `ManagerRegistry`
2. Встроенные плагины создают стандартные методы (`log_info`, `record_metric`)
3. Кастомный плагин создает специфичные методы (`send_message`, `get_process_info`)
4. Все методы используют единый `_call_manager()` с кэшированием
5. Декоратор `@process_monitored` интегрируется с процессом

## Паттерны использования

### Паттерн 1: Ленивая инициализация менеджеров

```python
class LazyManager(BaseManager, ObservableMixin):
    def __init__(self, name):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(self)
        # Менеджеры добавляются позже
    
    def setup_logger(self, logger):
        self.register_manager('logger', logger)
        # Методы логирования становятся доступны автоматически
    
    def setup_stats(self, stats):
        self.register_manager('stats', stats, enabled=True)
        if hasattr(self, '_proxy_created') and self._proxy_created:
            # Пересоздаем прокси-методы
            self._create_proxy_methods()
```

### Паттерн 2: Условное использование менеджеров

```python
class ConditionalManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None, stats=None, use_stats=False):
        BaseManager.__init__(self, name)
        managers = {'logger': logger}
        config = {'logger': True}
        
        if use_stats and stats:
            managers['stats'] = stats
            config['stats'] = True
        
        ObservableMixin.__init__(
            self,
            managers=managers,
            config=config,
            auto_proxy=True
        )
    
    def process(self):
        self.log_info("Обработка")
        # Методы статистики доступны только если stats зарегистрирован
        if self.has_manager('stats'):
            self.record_metric("operations.count")
```

### Паттерн 3: Динамическое переключение менеджеров

```python
class DynamicManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger1=None, logger2=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={'logger': logger1},
            auto_proxy=True
        )
        self._logger2 = logger2
    
    def switch_logger(self):
        """Переключить на второй логгер."""
        if self._logger2:
            self.unregister_manager('logger')
            self.register_manager('logger', self._logger2)
            # Прокси-методы автоматически обновятся
```

## Взаимодействие с другими менеджерами системы

### Интеграция с RouterManager

```python
class RouterIntegrationPlugin(ObservablePlugin):
    def get_manager_names(self):
        return ['router']
    
    def create_proxy_methods(self, instance, managers, call_manager_func):
        if 'router' in managers:
            instance.route_message = lambda msg, target: call_manager_func(
                'router', 'route', msg, target
            )
            instance.broadcast = lambda msg: call_manager_func('router', 'broadcast', msg)

# Использование
manager = SomeManager("test", router=router_manager)
manager.route_message(message, "target_process")
```

### Интеграция с WorkerManager

```python
class WorkerIntegrationPlugin(ObservablePlugin):
    def get_manager_names(self):
        return ['worker']
    
    def create_proxy_methods(self, instance, managers, call_manager_func):
        if 'worker' in managers:
            instance.start_worker = lambda name: call_manager_func('worker', 'start', name)
            instance.stop_worker = lambda name: call_manager_func('worker', 'stop', name)
            instance.get_worker_status = lambda name: call_manager_func('worker', 'status', name)
```

## Рекомендации по использованию

1. **Используйте приватные методы** для внутренней логики (`_log_info`)
2. **Используйте публичные методы** для удобного API (`log_info` при `auto_proxy=True`)
3. **Создавайте плагины** для кастомных менеджеров
4. **Регистрируйте менеджеры явно** для ясности
5. **Используйте конфигурацию** для управления состоянием менеджеров





