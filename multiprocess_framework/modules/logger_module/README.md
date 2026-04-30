# logger_module

Менеджер логирования, интегрированный в единую иерархию через `ChannelRoutingManager`.
Собирает логи от всех менеджеров через `ObservableMixin`, принимает `LOG`-сообщения от дочерних
процессов через `RouterManager` и записывает в множество каналов используя батчинг.

---

## Архитектура и наследование

```
BaseManager + ObservableMixin
        │
        ▼
ChannelRoutingManager  ← базовый класс для менеджеров с каналами
        │
        ▼
LoggerManager (BatchBuffer, scope-based routing, ILogChannel)
        │
        ▼
ErrorManager  (override log() для level-based routing)
```

**Что дал LoggerManager от ChannelRoutingManager:**
- `_channel_registry` (thread-safe RLock вместо `channels: Dict`)
- `_dispatcher` для маршрутизации по ключу (scope, level)
- `BatchBuffer` — настраиваемая стратегия буферизации
- `_normalize_config()` — обработка Dict | RegisterBase | None
- Единая иерархия `ILogChannel(IChannel)`

**Что осталось специфичным LoggerManager:**
- Scope-based routing (SYSTEM, BUSINESS, PERFORMANCE, AUDIT, SECURITY, DEBUG)
- Логирование с контекстом (`push_context` / `pop_context`)
- Module-specific логирование (`enable_module_logging`)
- Priority flush для ERROR/CRITICAL

---

## Роль в архитектуре

```
┌──────────────────────────────────────────────────────────────────────┐
│  Любой менеджер (BaseManager + ObservableMixin)                      │
│                                                                        │
│  ObservableMixin.__init__(managers={'logger': logger_manager})        │
│  self._log_info("message")   ──→  LoggerManager.info(msg)            │
│  self._log_error("error")    ──→  LoggerManager.error(msg)           │
└──────────────────────────────────────────────────────────────────────┘
                    │
        ┌───────────▼──────────────────────────────────┐
        │         LoggerManager                         │
        │    (наследует ChannelRoutingManager)          │
        │                                               │
        │  ┌────────────┐  ┌──────────────┐  ┌──────┐  │
        │  │ ScopeFilter│  │BatchBuffer   │  │Router│  │
        │  │ (кэш scope)│  │(config batch)│  │route │  │
        │  └─────┬──────┘  └───┬──────────┘  └───┬──┘  │
        └────────┼──────────────┼─────────────────┼────┘
                 │              │                 │
        ┌────────▼──────────────▼─────────────────▼────┐
        │  ChannelRoutingManager._dispatcher           │
        │         (scope/level routing)                │
        │  ┌─────────────────────────────────────────┐ │
        │  │  scope dispatcher (from CRM)            │ │
        │  │  data → scope filter → channel list     │ │
        │  └─────────────────────────────────────────┘ │
        └─────────────────────────────────────────────┘
                 │
        ┌────────▼──────────────────────────────────┐
        │     ILogChannel (от CRM через наследование)│
        │  FileChannel  ConsoleChannel  HttpChannel  │
        │  + кастомные каналы (DatabaseChannel...) │
        └───────────────────────────────────────────┘
```

**Интеграция через ObservableMixin:**

| Метод ObservableMixin | Маршрутизируется в | Scope |
|---|---|---|
| `self._log_debug(msg)` | `LoggerManager.debug(msg)` | DEBUG |
| `self._log_info(msg)` | `LoggerManager.info(msg)` | BUSINESS |
| `self._log_warning(msg)` | `LoggerManager.warning(msg)` | SYSTEM |
| `self._log_error(msg)` | `LoggerManager.error(msg)` | SYSTEM |
| `self._log_critical(msg)` | `LoggerManager.critical(msg)` | SYSTEM |

---

## Структура модуля

```
logger_module/
├── interfaces.py             ← Публичный контракт (ILoggerManager, ILogChannel)
├── __init__.py               ← Публичный API
│
├── core/
│   ├── logger_manager.py     ← LoggerManager(ChannelRoutingManager, ILoggerManager)
│   ├── log_types.py          ← LogRecord (dataclass)
│   ├── log_config.py         ← реэкспорт LoggerManagerConfig, LogLevel, LogScope
│   └── log_enums.py          ← LogLevel, LogScope (enum)
├── configs/
│   └── logger_manager_config.py  ← LoggerManagerConfig(ChannelRoutingConfig)
│
├── channels/
│   └── log_channel.py        ← LogChannel(ILogChannel), FileChannel, ConsoleChannel, HttpChannel
│
├── adapters/
│   └── logger_adapter.py     ← LoggerAdapter (для интеграции с процессами)
│
└── tests/
    └── test_logger_manager.py
```

---

## Быстрый старт

```python
from logger_module import LoggerManager, LoggerManagerConfig, LogLevel, LogScope

# Вариант 1: минимальная конфигурация
logger = LoggerManager(manager_name="app_logger")
logger.initialize()

# Вариант 2: через dict (Dict at Boundary)
logger = LoggerManager(
    manager_name="app_logger",
    config={
        "app_name": "inspector",
        "default_level": "INFO",
        "channels": {
            "console": {"type": "console", "enabled": True},
            "file":    {"type": "file", "enabled": True, "file_path": "logs/app.log"},
        },
    }
)
logger.initialize()

# Вариант 3: через LoggerManagerConfig (SchemaBase)
config = LoggerManagerConfig.model_validate({
    "app_name": "inspector",
    "default_level": "INFO",
    "enable_batching": True,
    "batch_size": 100,
    "channels": {...},
})
logger = LoggerManager(manager_name="app_logger", config=config)
logger.initialize()
```

---

## API: LoggerManager

### Жизненный цикл

| Метод | Описание |
|---|---|
| `initialize()` | Инициализировать каналы, dispatcher, buffer из CRM. Запустить батчер. |
| `shutdown()` | `flush()` → закрыть каналы → остановить buffer → остановить dispatcher. |

### Быстрые методы по уровню

```python
logger.debug("variable value", module="router_module")
logger.info("process started", module="orchestrator")
logger.warning("queue almost full", module="worker_module")
logger.error("connection failed", module="network")
logger.critical("out of memory", module="allocator")
```

### Методы по области (scope явный)

```python
logger.system(LogLevel.INFO, "LoggerManager initialized", module="logger_module")
logger.business(LogLevel.INFO, "frame processed", module="processor")
logger.performance(LogLevel.DEBUG, "fps=60", module="camera")
logger.audit(LogLevel.INFO, "config changed", module="config_module")
logger.security(LogLevel.WARNING, "unauthorized access attempt", module="api")
```

### Полный метод `log()` — все параметры

```python
logger.log(
    scope=LogScope.SYSTEM,
    level=LogLevel.ERROR,
    message="critical component failed",
    module="router_module",
    trace_id="abc-123",      # **extra поля
    retry_count=3,
)
```

### Контекстное логирование

```python
# Все последующие вызовы автоматически получат эти поля
logger.push_context(request_id="req-42", user="admin")
logger.info("processing request")   # → extra = {request_id: req-42, user: admin}
logger.warning("slow query")
logger.pop_context()

# Контекст как контекстный менеджер (через contextvars)
from logger_module.core.logger_manager import log_context
token = log_context.set({"trace_id": "xyz-789"})
logger.info("message")  # → extra = {trace_id: xyz-789}
log_context.reset(token)
```

### Отдельные файлы для модулей

```python
# Включить отдельный файл логирования для модуля
logger.enable_module_logging("router_module", "logs/router.log")
logger.info("routing started", module="router_module")  # → записывается и в router.log

# Выключить
logger.disable_module_logging("router_module")
```

---

## Батчинг (BatchBuffer из CRM)

По умолчанию включен. Логи группируются в пачки и записываются пакетами.
`ERROR` и `CRITICAL` всегда записываются немедленно (priority flush).

```python
# Принудительный сброс (например, при shutdown)
logger.flush()
```

| Параметр | По умолчанию | Описание |
|---|---|---|
| `enable_batching` | `True` | Включить батчинг |
| `batch_size` | `100` | Максимальный размер пачки |
| `batch_interval` | `1.0 сек` | Интервал принудительного сброса |
| `priority_flush` | `True` | ERROR/CRITICAL записываются немедленно |

**Thread-safety:** `BatchBuffer` использует `threading.Lock` — несколько потоков одного процесса
могут одновременно вызывать `logger.info()` без гонок данных.

---

## Каналы (ILogChannel)

Все каналы наследуют `ILogChannel(IChannel)` из `channel_routing_module`:

```python
class ILogChannel(IChannel):
    @property
    def name(self) -> str: ...
    @property
    def channel_type(self) -> str: return "log"
    def write(self, data: Dict[str, Any]) -> Dict[str, Any]: ...
    def close(self) -> None: ...
    def get_info(self) -> Dict[str, Any]: ...
```

### Встроенные каналы

- `FileChannel` — запись в файл
- `ConsoleChannel` — вывод на консоль
- `HttpChannel` — отправка в удалённый сервис логирования

### Кастомный канал

```python
from logger_module.interfaces import ILogChannel

class DatabaseChannel(ILogChannel):
    @property
    def name(self) -> str:
        return "database"

    def write(self, record: dict) -> dict:
        try:
            db.insert("logs", record)
            return {"status": "success", "channel": self.name}
        except Exception as e:
            return {"status": "error", "error": str(e), "channel": self.name}

    def close(self) -> None:
        db.close()

    def get_info(self) -> dict:
        return {"name": self.name, "active": db.is_connected()}

# Регистрация через register_channel()
logger.register_channel(DatabaseChannel())
```

---

## Конфигурация каналов

```python
from logger_module import LoggerManagerConfig

config = LoggerManagerConfig.model_validate({
    "app_name": "my_app",
    "default_level": "INFO",
    "enable_batching": True,
    "batch_size": 100,
    "batch_interval": 1.0,

    "channels": {
        "console": {
            "type": "console",
            "enabled": True,
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
        "app_file": {
            "type": "file",
            "enabled": True,
            "file_path": "logs/app.log",
            "max_size": 10485760,   # 10 MB
            "backup_count": 5,
        },
        "errors_file": {
            "type": "file",
            "enabled": True,
            "file_path": "logs/errors.log",
        },
    },

    "scopes": {
        "SYSTEM":      {"enabled": True,  "min_level": "WARNING", "channels": ["console", "app_file"]},
        "BUSINESS":    {"enabled": True,  "min_level": "INFO",    "channels": ["app_file"]},
        "DEBUG":       {"enabled": False, "min_level": "DEBUG"},
        "PERFORMANCE": {"enabled": True,  "min_level": "INFO",    "channels": ["app_file"]},
    },

    "modules": {
        "router_module": {"enabled": True, "file_path": "logs/router.log", "min_level": "DEBUG"},
    },
})
```

---

## Прием LOG-сообщений от дочерних процессов

Логи от дочерних процессов приходят через RouterManager как `Message(type='log')`.

```python
# При настройке оркестратора:
router.register_message_handler(
    key="log",
    handler=lambda msg: logger.log(
        scope=LogScope[msg.get("metadata", {}).get("scope", "BUSINESS").upper()],
        level=LogLevel[msg.get("level", "INFO").upper()],
        message=msg.get("message", ""),
        module=msg.get("module", "unknown"),
    ),
)
```

---

## Интеграция через ObservableMixin

Любой менеджер, использующий `ObservableMixin`, автоматически получает доступ к логированию:

```python
from base_manager import BaseManager, ObservableMixin

class RouterManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None, **kwargs):
        BaseManager.__init__(self, name)
        managers = {'logger': logger} if logger else {}

        ObservableMixin.__init__(
            self,
            managers=managers,
            config={'logger': True},
            auto_proxy=True,
        )

    def send(self, msg):
        self._log_debug(f"sending {msg.get('type')}")  # → LoggerManager.debug()
        # ...
        self._log_info("sent successfully")             # → LoggerManager.info()
```

---

## Dict at Boundary

| Формат | Пример |
|---|---|
| `None` | `LoggerManager()` — дефолтный конфиг |
| `dict` | `{"app_name": "app", "default_level": "INFO", "channels": {...}}` |
| `LoggerManagerConfig` | `LoggerManager(config=...)` |
| Объект с `build()` | `build()` возвращает `(manager_name: str, config: dict)` |

---

## Тесты

```bash
cd multiprocess_framework/refactored
pytest modules/logger_module/tests/ -v
```

Покрытие (~30 тестов):
- Жизненный цикл: `initialize()` / `shutdown()`
- Логирование по уровням: debug/info/warning/error/critical
- Логирование по областям: system/business/performance/audit/security
- Батчинг: size-based, time-based, priority flush
- Контекст: push/pop, contextvars integration
- Каналы: регистрация, удаление, кастомные каналы
- Интеграция с RouterManager: приём LOG-сообщений
