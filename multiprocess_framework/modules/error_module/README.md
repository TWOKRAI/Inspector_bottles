# error_module

Специализированный менеджер обработки ошибок — наследник `LoggerManager`.
Добавляет level-based channel routing (CRITICAL/ERROR/WARNING в отдельные файлы)
и `log_exception()` с форматированием traceback.

---

## Архитектура и наследование

```
BaseManager + ObservableMixin
        │
        ▼
ChannelRoutingManager  ← базовый класс
        │
        ▼
LoggerManager (синхронная запись, scope-based routing)
        │
        ▼
ErrorManager  (хук _route() для level-based routing; log() общий)
        │
        Чего добавляет ErrorManager:
        ├─ _level_to_channel: {CRITICAL→critical_file, ERROR→errors_file, WARNING→warnings_file}
        ├─ log_exception() — специфичный метод с traceback
        └─ _setup_level_routes() при initialize()
```

**Что дал ErrorManager от LoggerManager/ChannelRoutingManager:**
- Синхронная запись в каналы (батчинг снят в Ф7.4)
- `_channel_registry` thread-safe из CRM
- `_dispatcher` для маршрутизации из CRM
- Интеграция через ObservableMixin
- Методы debug/info/warning/error/critical

**Что добавило ErrorManager:**
- Level-based routing: WARNING/ERROR/CRITICAL → отдельные файлы
- `_level_to_channel` — O(1) lookup вместо scope-based routing
- `log_exception()` — специализированный метод для ошибок с traceback
- ErrorManagerConfig(SchemaBase) для конфигурации путей

---

## Роль в архитектуре

```
┌──────────────────────────────────────────────────────────────────────┐
│  Любой менеджер (BaseManager + ObservableMixin)                      │
│                                                                        │
│  ObservableMixin.__init__(managers={'errors': error_manager})         │
│  self._track_error(exc, context={"method": "process"})               │
│  self._log_error("error message")  ──→  ErrorManager.error(msg)      │
└──────────────────────────────────────────────────────────────────────┘
                    │
        ┌───────────▼──────────────────────────────────┐
        │         ErrorManager                          │
        │   (наследует LoggerManager + CRM)            │
        │                                               │
        │  Инициализация: _setup_level_routes()         │
        │  _level_to_channel = {                        │
        │    "CRITICAL": "critical_file",               │
        │    "ERROR":    "errors_file",                 │
        │    "WARNING":  "warnings_file",               │
        │  }                                            │
        └─────────────────┬──────────────────────────┘
                          │
        ┌─────────────────▼──────────────────────────┐
        │  _route() — ЕДИНСТВЕННЫЙ хук (Ф4.2)         │
        │  сам log() живёт в LoggerCore, один на всех │
        │                                            │
        │  if level in _level_to_channel:            │
        │    return [_level_to_channel[level]]        │
        │  else:                                     │
        │    return super()._route()  # каналы скоупа │
        └─────────────────┬──────────────────────────┘
                          │
        ┌─────────────────▼──────────────────────────┐
        │     ILogChannel (от CRM через наследование) │
        │  critical.log  errors.log  warnings.log     │
        │  + кастомные каналы (AlertChannel...)      │
        └────────────────────────────────────────────┘
```

**Аналогия с RouterManager:**

| RouterManager | ErrorManager |
|---|---|
| `message` → `channel_dispatcher(key=type)` → `IMessageChannel` | `error_record` → `_level_to_channel[level]` → `ILogChannel` |
| `QueueChannel` / `SocketChannel` | `FileChannel` / `ConsoleChannel` |
| `send_async()` с PriorityQueue | Синхронная запись на всех уровнях (Ф7.4) |
| `register_route("set_fps", "ctrl_channel")` | Автоматическая регистрация при `_setup_level_routes()` |

---

## Структура модуля

```
error_module/
├── interfaces.py         ← Публичный контракт (IErrorManager)
├── __init__.py           ← Публичный API
│
├── core/
│   ├── error_manager.py           ← ErrorManager(LoggerManager)
│   └── error_config_assembly.py   ← expand_error_manager_config (merge severity channels)
│
├── configs/
│   └── error_manager_config.py    ← ErrorManagerConfig(SchemaBase), только поля
│
└── tests/
    ├── test_error_manager.py
    ├── test_error_config.py
    ├── test_error_level_routing.py
    └── test_error_integration.py
```

---

## Быстрый старт

```python
from error_module import ErrorManager, ErrorManagerConfig

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

# Вариант 3: SchemaBase-конфиг
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
| `initialize()` | Инит каналов + `_setup_level_routes()` → регистрация level→channel маппинга. |
| `shutdown()` | `flush()` → закрыть каналы → остановить dispatcher. |

### Методы логирования (наследует от LoggerManager)

```python
em.error("connection failed", module="network")         # → errors.log (через _level_to_channel)
em.critical("out of memory", module="allocator")        # → critical.log
em.warning("queue almost full", module="worker")        # → warnings.log
em.info("retry succeeded", module="retry_handler")      # → scope-based routing (в errors.log если default)
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

Параметр `include_stacktrace` в конфиге (`True` по умолчанию) можно переопределить на уровне вызова.

### track_error() — интеграция с ObservableMixin

Для использования через `_track_error()` из ObservableMixin (регистрация как `errors`):

```python
em.track_error(error, context={"message": "context", "module": "my_module"})
# → вызывает log_exception() с контекстом
```

### get_stats()

```python
stats = em.get_stats()
# {
#     "app_name": "errors",
#     "messages_processed": 42,
#     "messages_skipped": 0,
#     "channels_count": 3,

#     "include_stacktrace": True,
#     "level_routes": {               ← новое поле (level → channel)
#         "CRITICAL": "critical_file",
#         "ERROR":    "errors_file",
#         "WARNING":  "warnings_file",
#     },
# }
```

---

## Level-based routing (ключевое отличие от LoggerManager)

После `initialize()` автоматически вызывается `_setup_level_routes()`, которая строит
`_level_to_channel` маппинг:

```
CRITICAL → critical_file  (если канал не настроен → fallback в errors_file)
ERROR    → errors_file
WARNING  → warnings_file  (если канал не настроен → fallback в errors_file)
```

Маппинг применяется через хук резолва приёмников — `log()` **не переопределяется**
(Ф4.2, ADR-EM-007):

```python
def _route(self, scope, level, module):
    channel_name = self._level_to_channel.get(level.value)
    if channel_name is None:
        return super()._route(scope, level, module)  # DEBUG/INFO → каналы скоупа
    return [channel_name]
```

Это **вся** разница между двумя путями эмиссии. Сборка записи, контекст, tap'ы,
пол ошибок и учёт потерь — общие и физически в одном месте (`LoggerCore.log`).

> **Почему так, а не override `log()`.** Полный override стоил фазе четырёх
> ручных зеркалирований улучшений родителя: 0.4 — в двух местах, 0.9 — в двух,
> tap'ы — в двух, а Ф0.5 забыли, из-за чего на ГЛАВНОМ производственном пути
> ошибок пропал `proc_name`. Развилка воспроизводит этот дефект при каждой
> следующей правке `log()`, поэтому убрана до фаз адресации и `trace_id`.

Гейт скоупа на severity-пути **не спрашивается**, и это осознанно: приёмник
ошибки определяет severity, а порог скоупа (у `SYSTEM` это `WARNING`) не должен
уметь заглушить `ERROR`. Закреплено характеризационным тестом
`test_severity_path_ignores_scope_gate`.

---

## Конфигурация через ErrorManagerConfig

```python
from error_module import ErrorManagerConfig

config = ErrorManagerConfig(
    manager_name="AppErrors",
    app_name="my_app",

    # Severity channels (пути файлов)
    critical_file_path="logs/critical.log",  # CRITICAL
    error_file_path="logs/errors.log",        # ERROR
    warnings_file_path="logs/warnings.log",   # WARNING (None → не создавать)

    # Уровень и батчинг
    default_level="WARNING",   # Минимальный уровень для всех каналов
    include_stacktrace=True,

    # Дополнительные каналы через наследованный channels
    channels={
        "telegram": {
            "type": "custom",
            "handler": "send_telegram_alert",
        }
    }
)

em = ErrorManager(config=config)
em.initialize()
```

**ErrorManagerConfig наследует SchemaBase** → плоские поля путей и опциональный `channels`;
полная сборка под `LoggerManager` — в `expand_error_manager_config()`.

---

## Кастомный severity-канал

```python
from logger_module.interfaces import ILogChannel

class AlertChannel(ILogChannel):
    @property
    def name(self) -> str:
        return "alerts"

    def write(self, record: dict) -> dict:
        send_telegram(f"🔴 CRITICAL: {record['message']}")
        return {"status": "success", "channel": self.name}

    def close(self) -> None:
        pass

    def get_info(self) -> dict:
        return {"name": self.name, "type": "alert"}

# Регистрация напрямую в registry:
alert_ch = AlertChannel()
em.register_channel(alert_ch)

# ErrorManager уже содержит _level_to_channel маппинг
# Новый канал автоматически доступен для маршрутизации
```

---

## Запись синхронна (батчинг снят в Ф7.4)

Все уровни, включая `WARNING`, пишутся в вызывающем потоке. Раньше `WARNING` шёл через
`BatchBuffer`, а `ERROR`/`CRITICAL` — мимо него; замер показал, что батчинг не экономит
вызовы на границе ОС и ухудшает хвост эмитента в 18 раз, поэтому механизм снят целиком.
Ключи `enable_batching` / `batch_*` из конфига убраны; секция `observability` жалуется,
если встретит их (молча игнорировать снятую ручку — это «проглоченный сбой»).

**Пол ошибок.** Severity-маршрут конфиго-зависим целиком (`_setup_level_routes` строит
`_level_to_channel` из фактически созданных каналов). Если канал уровня отсутствует, снят через
`logger.sink.disable` или упал на записи — запись уходит в общий `errors_floor.jsonl`
(JSON Lines, полный трейсбек и `extra`). Пол срабатывает **только** при непринявшем канале,
поэтому дубля «и в канал, и в пол» не бывает. Счётчик: `get_stats()["errors_to_floor"]`.

**Ф0.6:** `ErrorManager` адресуется командой `logger.sink.enable|disable` отдельно от
логгера — параметром `manager="error"`. Раньше команда била только в `logger_manager`,
хотя методы у `ErrorManager` были: дыра была не в методах, а в адресуемости.

**Thread-safety:** запись синхронна; несколько потоков одного процесса могут одновременно
вызывать `em.error()`.

---

## Интеграция через ObservableMixin

```python
from base_manager import BaseManager, ObservableMixin

class RouterManager(BaseManager, ObservableMixin):
    def __init__(self, name, error_manager=None):
        BaseManager.__init__(self, name)
        managers = {'errors': error_manager} if error_manager else {}

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
| `LogConfig` | `ErrorManager(config=log_config)` — наследуемая конфигурация |
| `ErrorManagerConfig` | `ErrorManager(config=ErrorManagerConfig(...))` |
| Объект с `build()` | `build()` возвращает `(manager_name: str, config: dict)` |

---

## Тесты

```bash
cd multiprocess_framework/modules
python -m pytest error_module/tests/ -v
```

Покрытие (25 тестов): expand/config, инициализация ErrorManager, `log_exception`, `get_stats`,
level routing и fallback, DEBUG/INFO через родителя, `track_error`, интеграция записи в файл.
