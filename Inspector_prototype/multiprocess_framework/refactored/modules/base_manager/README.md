# base_manager

**Базовый модуль фреймворка.** Фундамент, на котором строятся все 12 менеджеров системы.

Предоставляет два независимых строительных блока:

| Класс | Роль |
|---|---|
| `BaseManager` | Абстрактный менеджер: жизненный цикл, адаптеры, события |
| `ObservableMixin` | Наблюдаемость: прозрачное взаимодействие с logger/stats/error и любым сервисом |

---

## Быстрый старт

```python
from base_manager import BaseManager, ObservableMixin

class RouterManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None, stats=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={'logger': logger, 'stats': stats},
            config={'logger': True, 'stats': True},
        )

    def initialize(self) -> bool:
        self._log_info("RouterManager starting")
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        self.is_initialized = False
        return True

    def route(self, message: dict) -> bool:
        self._log_debug(f"Routing message: {message.get('type')}")
        self._record_metric("router.messages_processed")
        return True
```

---

## BaseManager

### Публичный API

#### Жизненный цикл

| Метод | Возвращает | Описание |
|---|---|---|
| `initialize()` | `bool` | Абстрактный. Реализуется в подклассе. |
| `shutdown()` | `bool` | Абстрактный. Реализуется в подклассе. |

#### Управление адаптерами

| Метод | Сигнатура | Описание |
|---|---|---|
| `attach_adapter` | `(adapter, name=None) → bool` | Подключить адаптер. Рекомендуется явно указывать `name`. |
| `get_adapter` | `(name=None) → Optional[Any]` | Получить адаптер по имени (предпочтительно). |
| `has_adapter` | `(name) → bool` | Проверить наличие. |
| `list_adapters` | `() → List[str]` | Список имён адаптеров. |
| `detach_adapter` | `(name) → bool` | Отключить адаптер. |

```python
adapter = CommandAdapter(manager, process)
manager.attach_adapter(adapter, name="command")

# Явный доступ (рекомендуется)
cmd = manager.get_adapter("command")

# Magic-доступ (удобно, но менее явно)
cmd = manager.command
```

#### События

| Метод | Описание |
|---|---|
| `on_event(event_type, callback)` | Зарегистрировать обработчик. |
| `emit_event(event_type, data)` | Генерировать событие. Ошибки в обработчиках перехватываются. |

```python
manager.on_event("message_processed", lambda data: log(data))
manager.emit_event("message_processed", {"count": 1})
```

#### Диагностика

| Метод | Описание |
|---|---|
| `get_stats()` | Имя, статус, список адаптеров, статистика адаптеров. |
| `get_debug_info()` | Полная диагностическая информация (включая ObservableMixin). |
| `print_debug_info()` | Вывод `get_debug_info()` в консоль. |

---

## ObservableMixin

### Концепция

`ObservableMixin` решает проблему: *"как менеджер должен логировать, собирать метрики и
трекировать ошибки, не зная ничего о конкретных реализациях сервисов?"*

Ответ: **через единый интерфейс вызова** `_call_manager(service_name, method_name, ...args)`.
Менеджер говорит `self._log_info("msg")` — mixin сам найдёт `logger_manager` и вызовет его `info()`.

### Режимы

**Режим 1 — Приватные методы** (по умолчанию, всегда pickle-совместимы):

```python
ObservableMixin.__init__(self, managers={'logger': logger, 'stats': stats})

# Использование в методах менеджера:
self._log_debug("debug message")
self._log_info("info message")
self._log_warning("warning message")
self._log_error("error message")
self._log_critical("critical message")

self._record_metric("operations.count", value=1)
self._record_timing("query.duration", 0.042)

self._track_error(exc, context={"method": "process"})
```

**Режим 2 — Публичные прокси-методы** (`auto_proxy=True`):

```python
ObservableMixin.__init__(
    self,
    managers={'logger': logger, 'stats': stats, 'errors': error_tracker},
    auto_proxy=True,
)

# Публичные методы создаются автоматически (только если менеджер зарегистрирован):
self.log_info("message")
self.record_metric("ops", value=5)
self.track_error(exc)
```

### Управление менеджерами

| Метод | Описание |
|---|---|
| `register_manager(name, manager)` | Зарегистрировать сервис. Автоматически обновляет proxy-методы. |
| `unregister_manager(name)` | Удалить сервис из реестра. |
| `get_manager(name)` | Получить сервис по имени. |
| `has_manager(name)` | Проверить наличие. |

### Управление состоянием

| Метод | Описание |
|---|---|
| `enable(name, enabled=True)` | Включить или выключить менеджер. |
| `disable(name)` | Выключить (вызовы тихо игнорируются). |
| `is_enabled(name)` | Проверить состояние. |
| `get_enabled_managers()` | Множество включённых имён. |
| `context(name, enabled=True)` | Контекстный менеджер для временного изменения. |

```python
# Временно отключить логирование (e.g. для шумных операций):
with self.context('logger', enabled=False):
    bulk_process(data)

# Выключить статистику до инициализации:
manager.disable('stats')
manager.initialize()
manager.enable('stats')
```

### Конфигурация

```python
# Простая форма:
config = {'logger': True, 'stats': False}

# Подробная форма:
config = {'logger': {'enabled': True}, 'stats': {'enabled': False}}

# Обновить после инициализации:
manager.update_config({'stats': True})
```

### Плагины

Плагины позволяют подключить произвольный сервис к системе proxy-методов:

```python
from base_manager.mixins.plugins.plugin_base import ObservablePlugin

class MetricsPlugin(ObservablePlugin):
    def get_manager_names(self):
        return ['metrics']

    def create_proxy_methods(self, instance, managers, call_manager_func):
        if 'metrics' not in managers:
            return

        def push_metric(name, value):
            return call_manager_func('metrics', 'push', name, value)

        instance.push_metric = push_metric


# Регистрация при инициализации:
ObservableMixin.__init__(
    self,
    managers={'metrics': my_metrics_service},
    plugins=[MetricsPlugin()],
    auto_proxy=True,
)
self.push_metric("latency", 42)

# Или позже:
manager.register_plugin(MetricsPlugin())
```

### Pickle-совместимость (multiprocessing, Windows spawn)

| Что | Поведение после pickle/unpickle |
|---|---|
| `_log_*`, `_record_*`, `_track_*` | **Работают** (методы класса). Возвращают None пока managers не перерегистрированы. |
| `log_info`, `record_metric`, … | **Отсутствуют** после unpickle — воссоздаются через `register_manager()`. |
| `manager_name`, `is_initialized`, адаптеры | **Сохраняются**. |
| Зарегистрированные managers | **Теряются** (они hold ресурсы — сокеты, очереди). Владелец перерегистрирует их. |

```python
# Рекомендованный паттерн для multiprocessing:
class WorkerManager(BaseManager, ObservableMixin):
    def restore_after_unpickle(self, logger, stats):
        """Вызвать после получения объекта в другом процессе."""
        self.register_manager('logger', logger)
        self.register_manager('stats', stats)
```

### Диагностика

```python
# Показать все зарегистрированные менеджеры и методы:
manager.print_available_methods()

# Получить снимок состояния:
state = manager.get_state()
# {'managers': ['logger', 'stats'], 'enabled': {...}, 'plugins': [...]}
```

---

## BaseAdapter

`BaseAdapter` — абстрактный класс для адаптеров, которые инкапсулируют
взаимодействие менеджера с процессом или внешним ресурсом.

```python
from base_manager import BaseAdapter

class CommandAdapter(BaseAdapter):
    def setup(self) -> bool:
        # Настройка и интеграция с manager и process
        self._initialized = True
        return True

    def execute(self, command: str) -> bool:
        self._log("info", f"Executing: {command}")
        return True
```

### Логирование внутри адаптера

`BaseAdapter._log()` использует трёхуровневый fallback:

1. `manager._call_manager('logger', ...)` — если менеджер использует `ObservableMixin`
2. `process.logger_manager.{level}(...)` — прямой доступ к логгеру процесса
3. `print(...)` — последний fallback

---

## Структура модуля

```
base_manager/
├── __init__.py              BaseManager, BaseAdapter, ObservableMixin
├── interfaces.py            IBaseManager, IBaseAdapter, IObservableMixin
├── core/
│   └── base_manager.py      BaseManager (ABC + IBaseManager)
├── adapters/
│   └── base_adapter.py      BaseAdapter (ABC + IBaseAdapter)
├── mixins/
│   ├── observable_mixin.py  ObservableMixin (IObservableMixin)
│   ├── core/
│   │   ├── manager_registry.py   ManagerRegistry
│   │   └── method_cache.py       MethodCache
│   ├── proxies/
│   │   └── proxy_creator.py      ProxyCreator
│   ├── decorators/
│   │   └── observable_decorators.py  ObservableDecorators (logged, timed, monitored)
│   └── plugins/
│       ├── plugin_base.py        ObservablePlugin (ABC)
│       ├── plugin_registry.py    PluginRegistry
│       └── builtin_plugins.py    LoggerPlugin, StatsPlugin, ErrorPlugin
├── utils/
│   └── name_utils.py        get_adapter_name_from_class()
└── tests/
    ├── test_base_manager.py      24 теста (BaseManager + IBaseManager + pickle)
    ├── test_observable_mixin.py  25 тестов (приватные методы, proxy, pickle)
    ├── test_mixin_integration.py 8 тестов (интеграция, несколько менеджеров)
    └── test_plugin_system.py     12 тестов (встроенные и кастомные плагины)
```

---

## Кто использует модуль

```
BaseManager + ObservableMixin:
  ├── logger_module          LoggerManager
  ├── config_module          ConfigManager
  ├── router_module          RouterManager
  ├── command_module         CommandManager
  ├── worker_module          WorkerManager
  ├── process_module         ProcessModule
  ├── console_module         ConsoleManager
  ├── dispatch_module        Dispatcher
  └── shared_resources_module:
        ├── SharedResourcesManager
        ├── QueueRegistry
        ├── EventManager
        └── MemoryManager
```

---

## Чек-лист интеграции нового менеджера

```python
class MyNewManager(BaseManager, ObservableMixin):
    def __init__(self, name: str, logger=None, stats=None, process=None):
        # 1. BaseManager всегда первым
        BaseManager.__init__(self, name, process)

        # 2. ObservableMixin — передавать только реальные сервисы (не None-значения)
        managers = {}
        if logger:
            managers['logger'] = logger
        if stats:
            managers['stats'] = stats

        ObservableMixin.__init__(
            self,
            managers=managers,
            config={k: True for k in managers},
        )

    # 3. Реализовать оба абстрактных метода
    def initialize(self) -> bool:
        self._log_info("MyNewManager initializing")
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        self.is_initialized = False
        return True
```

---

## Архитектурные решения

**Почему методы класса вместо types.MethodType?**
Предыдущая реализация использовала `types.MethodType` с замыканиями из `LoggingMethods`, `StatsMethods`, `ErrorMethods`. Это порождало баг при pickle на Windows (spawn): замыкания не сериализуемы. Методы класса (`_log_info` как `def _log_info(self, ...)` прямо на `ObservableMixin`) полностью устраняют проблему.

**Почему `IObservableMixin` наследует `ObservableMixin`?**
Это позволяет писать `isinstance(manager, IObservableMixin)` для обнаружения
наблюдаемости, а также помогает mypy/pyright проверить что менеджер реализует
полный контракт.

**Почему `LoggerPlugin` теперь создаёт методы только при наличии 'logger'?**
Согласованность с `StatsPlugin` и `ErrorPlugin`. Публичный метод `log_info` имеет
смысл только когда логгер реально зарегистрирован. Это устраняет "мёртвые" методы.
