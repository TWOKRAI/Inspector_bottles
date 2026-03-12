# error_module

Специализированный менеджер ошибок — наследник `LoggerManager`. Добавляет
severity-based channel routing и `log_exception()` с форматированием traceback.

---

## Роль в архитектуре

```
┌──────────────────────────────────────────────────────────────────────┐
│  Любой менеджер (ObservableMixin)                                     │
│                                                                        │
│  ObservableMixin.__init__(managers={'errors': error_manager})          │
│  self._track_error(exc, context={"method": "process"})                │
│  self._log_error("error message")  ──→  ErrorManager.error(msg)       │
└──────────────────────────────────────────────────────────────────────┘
                    │
          ┌─────────▼──────────────────────────────────────────────┐
          │              ErrorManager (наследует LoggerManager)     │
          │                                                         │
          │  _setup_level_routes() после initialize():              │
          │  CRITICAL → critical_file                               │
          │  ERROR    → errors_file                                 │
          │  WARNING  → warnings_file                               │
          │                                                         │
          │  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
          │  │BatchManager │  │LogDispatcher │  │RouterManager  │  │
          │  │(thread-safe)│  │route_by_level│  │(если нужен)   │  │
          │  └──────┬──────┘  └──────┬───────┘  └───────┬───────┘  │
          └─────────┼───────────────┼───────────────────┼──────────┘
                    │               │                   │
          ┌─────────▼───────────────▼───────────────────▼──────────┐
          │  ILogChannel — каналы записи                            │
          │  critical.log    errors.log    warnings.log             │
          └────────────────────────────────────────────────────────┘
```

**Аналогия с RouterManager:**

| RouterManager | ErrorManager |
|---|---|
| `message` → `channel_dispatcher(key=type)` → `IMessageChannel` | `error_record` → `level_dispatcher(key=level)` → `ILogChannel` |
| `QueueChannel` / `SocketChannel` | `FileChannel` / `ConsoleChannel` |
| `send_async()` с PriorityQueue | `BatchManager` с priority_flush |
| `register_route("set_fps", "ctrl_channel")` | `register_level_route("ERROR", "errors_file", handler)` |

---

## Структура модуля

```
error_module/
├── interfaces.py         ← Публичный контракт (IErrorManager, ErrorConfigLike)
├── __init__.py           ← Публичный API (ErrorManager, ErrorManagerConfig)
│
├── core/
│   └── error_manager.py  ← ErrorManager (наследник LoggerManager)
│
├── config/
│   └── error_config.py   ← ErrorManagerConfig (RegisterBase)
│
└── tests/
    ├── test_error_manager.py
    └── test_error_config.py
```

---

## Быстрый старт

```python
from error_module import ErrorManager

# Вариант 1: дефолтный конфиг (3 severity-канала)
em = ErrorManager()
em.initialize()

# Вариант 2: dict (Dict at Boundary)
em = ErrorManager(config={
    "app_name": "my_errors",
    "default_level": "WARNING",
    "channels": {
        "errors_file": {"type": "file", "enabled": True, "file_path": "logs/errors.log"},
    },
})
em.initialize()

# Вариант 3: RegisterBase-конфиг
from error_module import ErrorManagerConfig

config = ErrorManagerConfig(
    error_file_path="var/log/errors.log",
    critical_file_path="var/log/critical.log",
    warnings_file_path="var/log/warnings.log",
    include_stacktrace=True,
)
em = ErrorManager(config=config)
em.initialize()

em.shutdown()
```

---

## API: ErrorManager

### Жизненный цикл

| Метод | Описание |
|---|---|
| `initialize()` | Инит каналов + `_setup_level_routes()` + dispatcher. |
| `shutdown()` | `flush()` → закрыть каналы → остановить dispatcher. |

### Методы логирования (наследует LoggerManager)

```python
em.error("connection failed", module="network")         # → errors.log
em.critical("out of memory", module="allocator")        # → critical.log
em.warning("queue almost full", module="worker")        # → warnings.log
em.info("retry succeeded", module="retry_handler")      # → errors.log (если нет отдельного)
```

### log_exception() — специфичный метод

```python
try:
    risky_operation()
except ValueError as e:
    em.log_exception(
        exc=e,
        message="Input validation failed",  # опционально
        module="validator",
        include_stacktrace=True,            # переопределяет конфиг
    )
# → errors.log: "Input validation failed: invalid literal ..."
#               "\nTraceback (most recent call last): ..."
```

Параметр `include_stacktrace` в конфиге (`True` по умолчанию) можно переопределить
на уровне вызова.

### get_stats()

```python
stats = em.get_stats()
# {
#     "app_name": "errors",
#     "messages_processed": 42,
#     "messages_skipped": 0,
#     "channels_count": 3,
#     "batching_enabled": True,
#     "include_stacktrace": True,
#     "level_routes": {           ← новое поле
#         "CRITICAL": ["critical_file"],
#         "ERROR":    ["errors_file"],
#         "WARNING":  ["warnings_file"],
#     },
# }
```

---

## Severity-based channel routing

После `initialize()` автоматически вызывается `_setup_level_routes()`, которая
регистрирует level-based routing через `LogDispatcher.register_level_route()`:

```
CRITICAL → critical_file  (если канал не настроен → fallback в errors_file)
ERROR    → errors_file
WARNING  → warnings_file  (если канал не настроен → fallback в errors_file)
```

Это позволяет использовать `dispatcher.route_by_level(record)`:

```python
# Напрямую через dispatcher (для расширенных сценариев):
em.dispatcher.route_by_level(record)
# → Dispatcher.dispatch(record_dict, key_field='level')
# → "ERROR" → errors_file_channel.write(record_dict)
```

### Кастомный severity-канал

```python
from logger_module.interfaces import ILogChannel

class AlertChannel(ILogChannel):
    @property
    def name(self) -> str: return "alerts"

    def write(self, record: dict) -> dict:
        send_telegram(f"🔴 CRITICAL: {record['message']}")
        return {"status": "success", "channel": self.name}

    def close(self) -> None: pass
    def get_info(self) -> dict: return {"name": self.name}

# Регистрация канала напрямую в dispatcher:
em.dispatcher.register_level_route(
    level="CRITICAL",
    channel_name="alerts",
    handler=alert_channel.write,
)
```

---

## Конфигурация через ErrorManagerConfig

```python
from error_module import ErrorManagerConfig

config = ErrorManagerConfig(
    manager_name="AppErrors",
    app_name="my_app",

    # Severity channels
    critical_file_path="logs/critical.log",  # CRITICAL
    error_file_path="logs/errors.log",        # ERROR
    warnings_file_path="logs/warnings.log",   # WARNING (None → не создавать)

    # Уровень и батчинг
    default_level="WARNING",   # Минимальный уровень для всех каналов
    include_stacktrace=True,
    enable_batching=True,
    batch_size=50,
    batch_interval=0.5,        # сброс каждые 0.5 сек или при ERROR/CRITICAL
)
```

---

## Интеграция через ObservableMixin

```python
from base_manager import BaseManager, ObservableMixin

class RouterManager(BaseManager, ObservableMixin):
    def __init__(self, name, error_manager=None):
        BaseManager.__init__(self, name)
        managers = {}
        if error_manager:
            managers['errors'] = error_manager

        ObservableMixin.__init__(
            self,
            managers=managers,
            config={'errors': True},
        )

    def send(self, msg):
        try:
            ...
        except Exception as exc:
            self._track_error(exc, context={"method": "send"})  # → ErrorManager
```

---

## Приём ERROR-сообщений от дочерних процессов

Ошибки от дочерних процессов приходят через RouterManager как `Message(type='log', level='error')`.

```python
# При настройке оркестратора:
router.register_message_handler(
    key="log",
    handler=lambda msg: (
        error_manager.log_exception(
            Exception(msg.get("message", "")),
            module=msg.get("module", "unknown"),
            include_stacktrace=False,   # Трейс уже в тексте сообщения
        )
        if msg.get("level") in ("error", "critical")
        else None
    ),
)
```

---

## Dict at Boundary

| Формат | Пример |
|---|---|
| `None` | `ErrorManager()` — дефолтный конфиг |
| `dict` | `{"app_name": "errors", "default_level": "WARNING", "channels": {...}}` |
| `LogConfig` | `ErrorManager(config=log_config)` |
| `ErrorManagerConfig` | `ErrorManager(config=ErrorManagerConfig(...))` |
| Объект с `build()` | `build()` возвращает `(manager_name: str, config: dict)` |

---

## Батчинг

| Параметр | По умолчанию | Описание |
|---|---|---|
| `enable_batching` | `True` | Включить батчинг |
| `batch_size` | `50` | Максимальный размер пачки |
| `batch_interval` | `0.5 сек` | Интервал принудительного сброса |
| `priority_flush` | `True` | ERROR/CRITICAL записываются немедленно |

`BatchManager` потокобезопасен — несколько потоков одного процесса могут
одновременно вызывать `error_manager.error()` без гонок данных.

---

## Тесты

```bash
python -m pytest Inspector_prototype/multiprocess_framework/refactored/modules/error_module/tests/ -v
```

Покрытие (10 тестов):
- `ErrorManagerConfig.build()`: tuple, required keys, include_stacktrace, custom values
- `ErrorManager.__init__()`: None / dict / ErrorManagerConfig / build-object / invalid
- `log_exception()`: не падает при активном исключении
- `TypeError` при невалидном config

---

## Публичный контракт (interfaces.py)

```python
from error_module.interfaces import IErrorManager, ErrorConfigLike

def handle_errors(errors: IErrorManager) -> None:
    try:
        risky_operation()
    except Exception as exc:
        errors.log_exception(exc, "risky failed", module="handler")
```
