# ObservableMixin — архитектура наблюдаемости

## Проблема: как менеджер логирует, не зная о конкретных сервисах?

Представьте: `RouterManager` должен логировать сообщения. Но логирование — это забота отдельного сервиса (`logger_manager`), который может быть реализован по-разному (файл, консоль, Prometheus и т. д.). `RouterManager` не должен знать об этих деталях.

**Решение:** `ObservableMixin` — примесь, которая говорит: "Менеджер может сказать `self._log_info('msg')`, а я сам найду логгер и вызову его метод".

---

## Архитектура: два режима наблюдаемости

### Режим 1 — Приватные методы (по умолчанию, всегда pickle-совместимы)

```python
class RouterManager(BaseManager, ObservableMixin):
    def __init__(self, logger_mgr):
        BaseManager.__init__(self, "router")
        ObservableMixin.__init__(
            self,
            managers={'logger': logger_mgr}
        )
    
    def route(self, msg):
        self._log_info(f"Routing {msg}")  # ← приватный метод класса
        self._record_metric("router.messages", 1)
```

**Гарантия:** методы `_log_info`, `_record_metric`, `_track_error` — это **методы класса** на `ObservableMixin`, не замыкания. После `pickle/unpickle` они возвращают `None` пока менеджеры не перерегистрированы — но **не выбрасывают исключение**.

**Почему методы класса, а не `types.MethodType`?**

```python
# ❌ Неправильно (историческое):
def __init__(self, ...):
    def _log_info(msg):
        ...
    self._log_info = types.MethodType(_log_info, self)  # замыкание!
# На Windows spawn: замыкание не сериализуется → ошибка при pickle

# ✅ Правильно:
class ObservableMixin:
    def _log_info(self, msg):  # ← метод класса, сериализуется
        if not self.has_manager('logger'):
            return None
        return self._call_manager('logger', 'info', msg)
```

Методы класса — часть структуры класса, сериализуются как ссылки. Замыкания — части объекта экземпляра, не сериализуются на Windows spawn.

---

### Режим 2 — Публичные прокси-методы (удобство, опциональный)

```python
class MyManager(BaseManager, ObservableMixin):
    def __init__(self, logger_mgr):
        BaseManager.__init__(self, "my")
        ObservableMixin.__init__(
            self,
            managers={'logger': logger_mgr},
            auto_proxy=True  # ← создавать публичные методы
        )
    
    def work(self):
        self.log_info("work started")  # ← публичный прокси-метод
```

**Что происходит:**
1. При `__init__` с `auto_proxy=True` генерируются публичные методы:
   - `log_info`, `log_debug`, `log_warning`, ... (из `logger_manager`)
   - `record_metric`, `record_timing` (из `stats_manager`)
   - `track_error` (из `error_manager`)

2. Методы привязаны к экземпляру через `ProxyCreator.create_proxy_methods()`.

**Ловушка:** Эти методы **теряются после `pickle/unpickle`** (созданы динамически). Нужно переписать вручную:

```python
# Рекомендованный паттерн для multiprocessing:
class WorkerManager(BaseManager, ObservableMixin):
    def __init__(self, logger_mgr):
        BaseManager.__init__(self, "worker")
        ObservableMixin.__init__(
            self,
            managers={'logger': logger_mgr}
        )
    
    def restore_after_unpickle(self, logger_mgr):
        """Вызвать в новом процессе после unpickle."""
        self.register_manager('logger', logger_mgr)
        # Если нужны прокси-методы:
        # self._create_proxy_methods()
```

---

## Диаграмма вызовов (Режим 1)

```
Менеджер говорит:
    self._log_info("message")
            ↓
ObservableMixin._log_info(self, msg):
    if not self.has_manager('logger'):
        return None
    return self._call_manager('logger', 'info', msg)
            ↓
_call_manager(service_name, method_name, *args):
    manager = self._registry.get(service_name)
    if not manager or not self.is_enabled(service_name):
        return None
    return getattr(manager, method_name)(*args)
            ↓
ManagerRegistry.get('logger') → LoggerManager
            ↓
LoggerManager.info("message") → файл / консоль / Prometheus
```

---

## Управление менеджерами

### Регистрация и включение/отключение

```python
manager = MyManager()

# Регистрировать сервис
manager.register_manager('logger', logger_mgr)

# Проверить наличие
if manager.has_manager('logger'):
    ...

# Получить сервис
logger = manager.get_manager('logger')

# Отключить (вызовы вернут None)
manager.disable('logger')

# Включить обратно
manager.enable('logger')

# Временно отключить (контекстный менеджер)
with manager.context('logger', enabled=False):
    bulk_operation()  # не логируется
```

### Конфигурация (простая и подробная)

```python
# Простая форма:
config = {'logger': True, 'stats': False}

# Подробная форма:
config = {
    'logger': {'enabled': True},
    'stats': {'enabled': False}
}

# Обновить после инициализации:
manager.update_config({'stats': True})
```

---

## Pickle-совместимость для Windows spawn

### Что сохраняется после `pickle/unpickle`

| Что | Сохраняется? | Поведение |
|---|---|---|
| `_log_*`, `_record_*`, `_track_*` | **ДА** (методы класса) | Работают, возвращают `None` если менеджеры не перерегистрированы |
| `log_info`, `record_metric`, ... | **НЕТ** (динамические) | Теряются; воссоздать через `register_manager()` или переписать через приватные методы |
| `manager_name`, `is_initialized` | **ДА** | Сохраняются как есть |
| Адаптеры (`_adapters`) | **ДА** | Сохраняются, но менеджер-владелец, если он был, теряется |
| Зарегистрированные менеджеры | **НЕТ** | Теряются (они hold ресурсы: сокеты, файлы). Владелец перерегистрирует в новом процессе |

### Тестирование pickle-безопасности

```python
import pickle

manager = MyManager(logger_mgr, stats_mgr)
pickled = pickle.dumps(manager)

# В "другом процессе":
restored = pickle.loads(pickled)

# Приватные методы работают (возвращают None):
restored._log_info("test")  # None (ок!)

# Нужно перерегистрировать менеджеры:
restored.restore_after_unpickle(logger_mgr, stats_mgr)

# Теперь работает:
restored._log_info("test")  # вызовет logger_mgr.info()
```

---

## Почему были удалены плагины и декораторы?

### Плагины (ADR-114)

**Проблема:** `PluginRegistry` + `ObservablePlugin` + встроенные плагины дублировали приватные методы.

```python
# ❌ Плагин дублировал то, что уже было в классе:
class LoggerPlugin(ObservablePlugin):
    def create_proxy_methods(self, instance, ...):
        def log_info(msg):
            return call_manager_func('logger', 'info', msg)
        instance.log_info = log_info

# ✅ Уже есть в ObservableMixin:
class ObservableMixin:
    def _log_info(self, msg):
        ...
    # И можно добавить публичный прокси через auto_proxy=True
```

**Решение:** Удалена папка `mixins/plugins/`, приватные методы остаются, публичные прокси создаются через `auto_proxy=True`.

### Декораторы (ADR-115)

**Проблема:** `@logged`, `@timed`, `@monitored` дублировали режим 1, но были не pickle-safe.

```python
# ❌ Декоратор не сериализуется на Windows spawn:
@manager.logged("info")
def process(data):
    ...
# Замыкание декоратора при pickle → ошибка

# ✅ Вместо этого — приватные методы:
def process(self, data):
    self._log_info("started")
    ...
    self._record_timing("process.duration", elapsed)
```

**Решение:** Удалена папка `mixins/decorators/`, используйте приватные методы.

---

## Расширение для новых менеджеров

Раньше плагины позволяли добавить методы для нового менеджера. Теперь это делается через подклассы:

```python
# ❌ Старый способ (плагины, удалён):
class MetricsPlugin(ObservablePlugin):
    def get_manager_names(self):
        return ['metrics']
    def create_proxy_methods(self, instance, managers, call_manager_func):
        instance.push_metric = lambda name, value: call_manager_func('metrics', 'push', name, value)

ObservableMixin.__init__(self, plugins=[MetricsPlugin()])

# ✅ Новый способ (подклассы):
class CustomObservableMixin(ObservableMixin):
    def _push_metric(self, name, value):
        return self._call_manager('metrics', 'push', name, value)

class MyManager(BaseManager, CustomObservableMixin):
    def work(self):
        self._push_metric("latency", 42)
```

Это явнее, pickle-safe и проще.

---

## Итоговая архитектура

```
ObservableMixin
├── Приватные методы (всегда работают, pickle-safe):
│   ├── _log_info / debug / warning / error / critical
│   ├── _record_metric / _record_timing
│   └── _track_error
│
├── Управление менеджерами:
│   ├── register_manager / unregister_manager
│   ├── get_manager / has_manager
│   ├── enable / disable / is_enabled
│   └── context(name, enabled)
│
├── Публичные прокси-методы (опциональный mode, auto_proxy=True):
│   ├── log_info / log_debug / ...
│   ├── record_metric / record_timing
│   └── track_error
│
└── ManagerRegistry (реестр менеджеров)
    └── {'logger': LoggerManager, 'stats': StatsManager, ...}
```

---

## Практические советы

1. **По умолчанию используйте режим 1** (приватные методы).
2. **`auto_proxy=True` только если нужна красивая синтаксис** и ваш менеджер не будет пиклиться в multiprocessing.
3. **Для multiprocessing всегда реализуйте `restore_after_unpickle()`** или явно перерегистрируйте в новом процессе.
4. **Проверяйте pickle-безопасность в тестах:**
   ```python
   import pickle
   manager = YourManager(...)
   unpickled = pickle.loads(pickle.dumps(manager))
   assert unpickled._log_info("test") is None  # No exception
   ```
