# logger_module

Менеджер логирования, интегрированный в единую иерархию через `ChannelRoutingManager`.
Собирает логи от всех менеджеров через `ObservableMixin`, принимает `LOG`-сообщения от дочерних
процессов через `RouterManager` и записывает в множество каналов используя батчинг.

> **Observability control plane:** новый тип sink добавляется одной строкой
> `register_sink_factory(type, cls)` (`channels/log_channel.py`) — без правки `create_channel`.
> Runtime-перенастройка каналов/уровней — `reconfigure(config: dict)` (база CRM, хук
> `_rebuild_from_config` + `invalidate_decision_cache`). Hot-reload из файла —
> `process_module/managers/observability_reload.py`. Точки расширения и якоря —
> ADR-CRM-006 в [`../channel_routing_module/DECISIONS.md`](../channel_routing_module/DECISIONS.md).

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
│   ├── logger_adapter.py     ← LoggerAdapter (для интеграции с процессами)
│   └── std_facade.py         ← StdLoggerFacade / get_std_logger (мост из stdlib-стиля)
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

### Прикладной код в stdlib-стиле — `get_std_logger()`

Модуль, написанный как `logger = logging.getLogger(__name__)`, в процессе фреймворка
пишет в никуда: у корневого stdlib-логгера нет хендлеров, запись не попадает ни в
`logs/<proc>/*.log`, ни в консольный канал. Мост — `StdLoggerFacade`:

```python
from multiprocess_framework.modules.logger_module import get_std_logger

logger = get_std_logger("gui")          # имя per-module файла: gui/trace/camera/…
logger.warning("процесс '%s' не удалён", name)   # → logs/<proc>/gui.log + scope-каналы
```

Поверхность совпадает со stdlib (`debug/info/warning/error/critical/exception/log`),
включая `%`-форматирование. Если `LoggerManager` ещё не поднят — запись уходит в
обычный `logging` (фолбэк `mpf.<module>`), а не теряется. Резолв менеджера ленивый:
модули импортируются до `init_logging()`.

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

# Факт про ПРОЦЕСС ЦЕЛИКОМ — виден из всех потоков
logger.set_base_context(proc_name="camera_0")
logger.clear_base_context()

# Контекст как контекстный менеджер (через contextvars)
from logger_module.core.logger_manager import log_context
token = log_context.set({"trace_id": "xyz-789"})
logger.info("message")  # → extra = {trace_id: xyz-789}
log_context.reset(token)
```

**Два слоя, и это не украшение API (Ф0.5).** `push_context` действительно
потоковый — контекст виден только своему потоку (и своему asyncio-таску), соседний
поток его не видит и своего не теряет. До Ф0.5 стек был **один на инстанс** вопреки
имени `_get_thread_context()`: два потока перетирали контекст друг другу, и запись
могла уехать с чужим `request_id`.

Но одного потокового слоя мало. Единственный производственный потребитель — процесс,
который на старте кладёт `proc_name` **из главного потока**, а пишут логи потоки-воркеры.
Сделай контекст просто thread-local — и `proc_name` молча исчезнет из всех записей
воркеров (это верно и для `ContextVar`: новый поток стартует с чистым контекстом).
Поэтому слоёв два, по числу фактов:

| Слой | Что кладут | Кто видит |
|---|---|---|
| `log_context` (ContextVar) | публичная «форточка» | текущий поток/таск |
| `set_base_context()` | факт про процесс (`proc_name`) | **все потоки** |
| `push_context()` | факт про текущую работу (`request_id`) | только свой поток/таск |
| `extra=` в вызове | факт про конкретную запись | только эта запись |

Приоритет — сверху вниз по таблице: каждый следующий слой знает больше про конкретную
запись и перекрывает предыдущий по совпадающим ключам.

> ⚠️ **Контекст привязан к потоку, а не к задаче.** Пул потоков переиспользует поток,
> поэтому `push_context` без парного `pop_context` достанется следующей задаче на том же
> потоке. Снимает тот, кто положил — по `finally`. Свойство зафиксировано тестом
> `test_unpopped_context_persists_on_a_reused_thread`.

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

По умолчанию включён. `DEBUG`/`INFO`/`WARNING` группируются в пачки и записываются пакетами.

**`ERROR` и `CRITICAL` батчинг не проходят вовсе** (Ф0.9): `log()` сбрасывает пачку целевых
каналов, а затем пишет запись **напрямую в канал**, синхронно, в вызывающем потоке. Это не
зависит ни от `enable_batching`, ни от `priority_flush` — выключение батчинга ничего не меняет
для ошибок, они и так синхронны.

> Историческая справка, чтобы не искать заново: раньше здесь было написано «ERROR и CRITICAL
> всегда записываются немедленно (priority flush)». Это было **неправдой** — механизм
> `priority_flush` существовал в `BatchBuffer`, но приоритет в него не передавал никто, и окно
> потери crash-лога равнялось `batch_interval`. Ф0.1 передала приоритет, Ф0.9 убрала ошибки из
> пачки совсем. Параметр `priority_flush` остался штатной возможностью `BatchBuffer`, но
> **лог-слой им больше не пользуется**.

```python
# Принудительный сброс (например, при shutdown)
logger.flush()
```

| Параметр | По умолчанию | Описание |
|---|---|---|
| `enable_batching` | `True` | Включить батчинг **для DEBUG/INFO/WARNING**. На ERROR/CRITICAL не влияет |
| `batch_size` | `100` | Максимальный размер пачки |
| `batch_interval` | `1.0 сек` | Интервал принудительного сброса |
| `batch_max_pending` | `10 000` | Потолок неотправленных записей **на канал**. `0` — без потолка |
| `batch_overflow_policy` | `drop_oldest` | Что терять при переполнении: `drop_oldest` (кольцо) или `drop_newest` |

**Потолок буфера (Ф0.3).** Медленный сток (диск под нагрузкой, зависший stdout, канал под
удержанным локом) раньше копил записи в памяти без предела и без следа. Теперь пачка канала
ограничена, а потеря названа: `get_stats()["batch_stats"]` содержит `dropped` и
`dropped_by_channel` с именем канала-виновника. Оба параметра задаются и секцией
`observability` (`batch_max_pending`, `batch_overflow_policy`) — то есть меняются на живой
системе через `config.reload`, а читаются командой `introspect.observability`.

**Цена синхронного пути.** Сброс пачки перед записью ошибки стоит ~1.3 мс p50 / 1.6 мс p95 на
полной пачке из 100 записей — **на каждый канал scope** (дефолт `SYSTEM → [console, system_file]`,
то есть вдвое). Шторм ошибок цену не множит: первый сброс осушает пачку, последующие ошибки
стоят ~0.02 мс. Подробности и границы — `STATUS.md`, «Известные проблемы».

**Пол ошибок.** Если запись `ERROR`/`CRITICAL` не принял **ни один** канал (приёмники выключены
в конфиге, сняты через `logger.sink.disable` или все `write` упали), она уходит в
`errors_floor.jsonl` рядом с логами — JSON Lines, полная запись с трейсбеком и `extra`.
Пол пишет **только** при нуле принявших каналов, поэтому второй копии записи не создаёт.
Непустой `errors_floor.jsonl` — сигнал «штатный маршрут ошибок сломан», а не норма.
Счётчики: `get_stats()["errors_to_floor"]` и секция `error_floor` (`path` / `written` /
`failures`); у живого процесса — `introspect.observability`.

**Канала нет — запись не исчезает бесследно (Ф0.4).** Имя канала может не резолвиться: опечатка
в `scopes`, канал снят через `logger.sink.disable`, module-канал удалён. Раньше такая запись
пропадала молча на обоих путях доставки. Теперь она считается **по записи**, а имя виновника
названо:

| Ключ `get_stats()` | Что значит |
|---|---|
| `unresolved_channel_records` | сколько записей адресовано несуществующему каналу |
| `unresolved_channels` | то же в разбивке `{имя канала: число}` |
| `channel_write_errors` | сколько записей потеряно из-за **исключения** в `write()` канала |
| `channel_write_errors_by_channel` | то же в разбивке по каналам |

Отказ канала статусом (`{"status": "error"}`) в `channel_write_errors` **не** попадает — он виден
как разница «отдано минус принято» (`batch_stats.flush_failed`). Все четыре ключа присутствуют
всегда, нулями: «ключа нет» и «потерь нет» — разные факты. Наружу выходят через
`introspect.observability`.

Предупреждение об этом пишется в fallback-логгер (stdlib) **ровно один раз на имя канала** за
жизнь процесса — имя от записи к записи не меняется, а лог-шторм внутри логгера ровно та
болезнь, ради которой соседние `except` стоят молча. Учёт при этом не глушится никогда.
Для `ERROR`/`CRITICAL` «канала нет» не означает потерю: запись подхватывает пол (см. выше),
поэтому `unresolved_channel_records` и `errors_to_floor` растут вместе и не противоречат.

**Sink-control и tap'ы живут в базе (Ф0.6).** `set_sink_enabled`, `add_tap` / `remove_tap`
и `_fallback_log` подняты в `ChannelRoutingManager` — они одинаковы у логов, ошибок и
статистики, и держать три копии было бы третьей копией одной операции. У логгера остался
только хук `_recreate_channel`: «откуда взять параметры канала при включении обратно»
(из `config.channels[name]`, даже если там `enabled=False` — включение через control-plane
это явный override оператора).

Методы переименованы: `add_log_tap` / `remove_log_tap` → **`add_tap` / `remove_tap`**.
Старые имена удалены, а не оставлены обёртками. Команда `logger.sink.enable|disable`
принимает `manager=logger|error|stats` (дефолт `logger` — старые вызовы бьют туда же).

**Thread-safety:** `BatchBuffer` использует `threading.Lock` — несколько потоков одного процесса
могут одновременно вызывать `logger.info()` без гонок данных. Счётчики потерь Ф0.4 защищены
отдельным локом, который берётся **только** на пути потери (замер: 12 потоков × 3000 записей без
лока дают 29 261 инкремент из 36 000 — счётчик потерь врал бы в меньшую сторону).

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
- Батчинг: size-based, time-based (ошибки идут мимо батчинга — см. «Батчинг» выше)
- Пол ошибок: синхронная запись, floor при нуле приёмников, отсутствие дубля
- Контекст: push/pop, contextvars integration
- Каналы: регистрация, удаление, кастомные каналы
- Интеграция с RouterManager: приём LOG-сообщений
