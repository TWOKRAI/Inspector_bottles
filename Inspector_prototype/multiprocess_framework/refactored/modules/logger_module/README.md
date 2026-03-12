# logger_module

Центральный менеджер логирования системы. Собирает логи от всех менеджеров
через `ObservableMixin`, принимает `LOG`-сообщения от дочерних процессов
через `RouterManager` и записывает в множество каналов.

---

## Роль в архитектуре

```
┌──────────────────────────────────────────────────────────────────────┐
│  Любой менеджер (ObservableMixin)                                     │
│                                                                        │
│  ObservableMixin.__init__(managers={'logger': logger_manager})         │
│  self._log_info("message")   ──→  LoggerManager.info(msg)             │
│  self._log_error("error")    ──→  LoggerManager.error(msg)            │
└──────────────────────────────────────────────────────────────────────┘
                    │
          ┌─────────▼────────────────────────────────────┐
          │              LoggerManager                    │
          │                                               │
          │  ┌────────────┐  ┌──────────┐  ┌──────────┐  │
          │  │ ScopeFilter│  │  Batcher │  │ Router   │  │
          │  │ (кэш)      │  │  (batch) │  │ routing  │  │
          │  └─────┬──────┘  └────┬─────┘  └────┬─────┘  │
          └────────┼──────────────┼──────────────┼────────┘
                   │              │              │
          ┌────────▼──────────────▼──────────────▼────────┐
          │         LogDispatcher → каналы                 │
          │  FileChannel  ConsoleChannel  HttpChannel  ... │
          └─────────────────────────────────────────────────┘
```

```
Дочерний процесс
      │
      │  Message(type='log', level='error', message='...')
      │
      ▼
RouterManager (channel='log')
      │
      ▼
LoggerManager.receive() / handler
      │
      ▼
Каналы записи
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
│   ├── logger_manager.py     ← LoggerManager (основной класс)
│   ├── log_dispatcher.py     ← LogDispatcher + LogRecord
│   └── log_config.py         ← LogConfig, LogLevel, LogScope, ChannelConfig, ...
│
├── channels/
│   └── log_channel.py        ← LogChannel, FileChannel, ConsoleChannel, HttpChannel
│
├── batcher/
│   └── batch_manager.py      ← BatchManager, BatchConfig
│
├── adapters/
│   └── logger_adapter.py     ← LoggerAdapter (для интеграции с процессами)
│
└── tests/
    └── test_logger_manager.py
```

---

## Области логирования (LogScope)

| Scope | Константа | Назначение |
|---|---|---|
| `"system"` | `LogScope.SYSTEM` | Запуск, остановка, конфигурация системы |
| `"business"` | `LogScope.BUSINESS` | Бизнес-логика, обработка данных |
| `"perf"` | `LogScope.PERFORMANCE` | Время выполнения, throughput |
| `"audit"` | `LogScope.AUDIT` | Действия пользователей, изменения |
| `"security"` | `LogScope.SECURITY` | Аутентификация, авторизация |
| `"debug"` | `LogScope.DEBUG` | Отладочная информация |

## Уровни логирования (LogLevel)

```
CRITICAL > ERROR > WARNING > INFO > DEBUG
```

---

## API: LoggerManager

### Создание

```python
from logger_module import LoggerManager, LogConfig, LogLevel, LogScope

# Минимальная конфигурация
logger = LoggerManager(manager_name="app_logger")
logger.initialize()

# С конфигурацией через dict (Dict at Boundary)
config = LogConfig.from_dict({
    "app_name": "inspector",
    "default_level": "INFO",
    "enable_batching": True,
    "batch_size": 100,
    "channels": {
        "console": {"type": "console", "enabled": True},
        "file":    {"type": "file", "enabled": True, "file_path": "logs/app.log"},
    },
})
logger = LoggerManager(manager_name="app_logger", config=config)
logger.initialize()

# С RouterManager (для межпроцессного логирования)
logger = LoggerManager(
    manager_name="app_logger",
    config=config,
    router_manager=router,
    enable_router_routing=True,
)
```

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
logger.warning("slow query")        # → extra = {request_id: req-42, user: admin}
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

## API: LoggerAdapter (для интеграции с процессами)

```python
from logger_module import LoggerAdapter

# Создание в ProcessModule:
adapter = LoggerAdapter(logger_manager=logger, process=self)
adapter.setup()

# Логирование с автоматическим scope:
adapter.log_with_auto_scope("info", "starting", context="my_process")
adapter.log_with_auto_scope(LogLevel.ERROR, "failed", context="my_process")

# Переключение роутера:
adapter.set_router_routing(True)   # логи пойдут через RouterManager

# Статистика:
stats = adapter.get_stats()
```

---

## Интеграция через ObservableMixin

Любой менеджер, использующий `ObservableMixin`, автоматически получает
доступ к логированию через LoggerManager:

```python
from base_manager import BaseManager, ObservableMixin

class RouterManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None, **kwargs):
        BaseManager.__init__(self, name)
        managers = {}
        if logger:
            managers['logger'] = logger

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

**Pickle-совместимость:** после unpickle (Windows spawn) нужно заново
вызвать `manager.register_manager('logger', logger_manager)`.

---

## Прием LOG-сообщений от процессов

Логи от дочерних процессов приходят через RouterManager как `Message(type='log')`.
Регистрация обработчика:

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

## Конфигурация каналов

```python
from logger_module import LogConfig

config = LogConfig.from_dict({
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
        "remote": {
            "type": "http",
            "enabled": False,
            "url": "https://logs.example.com/ingest",
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
```

---

## Батчинг

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

---

## Публичный контракт (interfaces.py)

```python
from logger_module.interfaces import ILoggerManager, ILogChannel

def configure_logging(manager: ILoggerManager) -> None:
    manager.enable_module_logging("my_module")
    manager.system(LogLevel.INFO, "configured", module="setup")

class MyLogChannel(ILogChannel):
    # Реализация кастомного канала
    ...
```
