# channel_routing_module — Базовый модуль маршрутизации

> «Телефонная станция для данных: принимает сигнал, смотрит в справочник, отправляет в нужный канал.»

Устраняет дублирование, существовавшее между `RouterManager`, `LoggerManager` и `ErrorManager`.
Один раз написанный `ChannelRoutingManager` становится базовым классом для всех.

---

## Проблема, которую решает модуль

До создания этого модуля три менеджера независимо реализовывали один паттерн:

```
RouterManager          LoggerManager          ErrorManager
─────────────────      ────────────────       ─────────────────
ChannelRegistry        channels: Dict         (через LoggerManager)
  (threading.RLock)      (без lock ⚠️)
AsyncSender            BatchManager           (через LoggerManager)
  (PriorityQueue)        (deque + timer)
Dispatcher             LogDispatcher          LogDispatcher
  (channel routing)      (обёртка над          (level routing)
                          Dispatcher)
register_channel()     (свой метод)           (через LoggerManager)
unregister_channel()   (свой метод)           (через LoggerManager)
get_channel()          (отсутствует ⚠️)       (отсутствует ⚠️)
```

**Результат**: 3 независимых реализации → ошибки в одном не исправляются в других, разный уровень thread-safety.

---

## Решение: единая иерархия

```
BaseManager + ObservableMixin
        │
        ▼
ChannelRoutingManager  ←── НОВЫЙ БАЗОВЫЙ КЛАСС
        │
        ├── LoggerManager       (BatchBuffer,       key=level/scope)
        │       │
        │       └── ErrorManager  (_level_to_channel, severity routing)
        │
        └── RouterManager       (AsyncSender,       channel+msg dispatchers)
```

`ChannelRoutingManager` пишет один раз:
- `ChannelRegistry` — thread-safe (RLock), работает с `IChannel`
- `Dispatcher` — маршрутизация ключ → обработчик
- `IBufferStrategy` — pluggable буферизация
- `normalize_config()` — Dict at Boundary
- `ChannelRoutingConfig` — базовый RegisterBase-конфиг

Каждый наследник **настраивает**, но **не переписывает**.

---

## Иерархия интерфейсов каналов

```
IChannel (channel_routing_module)
    │  name, channel_type, write(), close(), get_info()
    │
    ├── ILogChannel (logger_module)
    │       close() — abstract
    │       Реализует: LogChannel → FileChannel / ConsoleChannel / HttpChannel
    │
    └── IMessageChannel (router_module)
            send() — abstract (write = alias)
            poll() — abstract
            start/stop_listening()
            Реализует: MessageChannel → QueueChannel / SocketChannel
```

**Все каналы фреймворка совместимы с `ChannelRegistry`** — единый реестр для всего.

---

## Конфигурация через RegisterBase

```
ChannelRoutingConfig (RegisterBase)
    manager_name: str
    channels: Dict[str, dict]   ← общая секция
    build() → (name, dict)

    ├── LoggerManagerConfig (будущий)
    │       default_level, batch_size, scopes
    │
    └── ErrorManagerConfig
            critical_file_path, error_file_path, warnings_file_path
            include_stacktrace, enable_batching, batch_size
            channels ← унаследован (точка расширения для Telegram/Slack)
```

`normalize_config()` обрабатывает любой формат:
```python
normalize_config(None)         # → {}
normalize_config({"key": v})   # → {"key": v}
normalize_config(MyConfig())   # → config.build()[1] → dict
```

---

## Стратегии буферизации

| Стратегия | Когда использовать | Используется в |
|---|---|---|
| `DirectBuffer` | Тесты, синхронные операции, низкая нагрузка | Тесты CRM |
| `BatchBuffer` | Запись в файлы, агрегация логов (I/O-bound) | `LoggerManager` |
| `AsyncSenderBuffer` | Message-очереди, низкая задержка | Тесты CRM |
| `AsyncSender` (в RouterManager) | Полный pipeline с middleware | `RouterManager` |

> **Почему RouterManager не использует AsyncSenderBuffer?**
> `AsyncSenderBuffer` работает с pre-resolved каналами: `enqueue(channel_name, data)`.
> RouterManager буферизует ПОЛНЫЙ pipeline: `enqueue(msg) → middleware → resolve → send`.
> Это намеренное архитектурное решение (ADR-015): AsyncSender в RouterManager буферизует
> более сложную цепочку, включая middleware-трансформации.

---

## Публичный API

### `ChannelRoutingManager`

| Метод | Вход | Выход | Описание |
|---|---|---|---|
| `initialize()` | — | bool | Запустить dispatcher + buffer |
| `shutdown()` | — | bool | flush → stop → close channels |
| `register_channel(ch)` | IChannel | bool | Thread-safe регистрация |
| `unregister_channel(name)` | str | bool | Thread-safe удаление |
| `get_channel(name)` | str | IChannel? | Найти канал по имени |
| `get_all_channels()` | — | List[IChannel] | Все каналы |
| `register_route(key, ch_name)` | str, str | bool | Ключ → канал |
| `register_broadcast(key, names)` | str, List[str] | bool | Ключ → несколько каналов |
| `route(data, key_field?)` | dict | dict | Маршрутизировать данные |
| `flush()` | — | None | Сбросить buffer |
| `get_stats()` | — | dict | channels + buffer + routing |

### `ChannelRoutingConfig`

| Поле | Тип | Описание |
|---|---|---|
| `manager_name` | str | Имя менеджера |
| `channels` | Dict[str, dict] | Дополнительные каналы |
| `build()` | → (str, dict) | Для normalize_config() |

---

## Быстрый старт — создать новый менеджер

```python
from channel_routing_module import (
    ChannelRoutingManager, IChannel,
    BatchBuffer, BatchConfig, ChannelRoutingConfig,
)
from data_schema_module import register_schema, FieldMeta
from typing import Annotated, List, Dict, Any


# 1. Создать конфиг
@register_schema("MyManagerConfig")
class MyManagerConfig(ChannelRoutingConfig):
    manager_name: str = "MyManager"
    output_path: str = "data/output.jsonl"
    batch_size: Annotated[int, FieldMeta("Размер батча", min=1, max=10000)] = 100

    def build(self) -> tuple[str, dict]:
        return (self.manager_name, {
            "channels": {"output": {"type": "file", "path": self.output_path}},
            "batch_size": self.batch_size,
        })


# 2. Создать канал
class MyChannel(IChannel):
    def __init__(self, name: str, path: str):
        self._name = name
        self._path = path

    @property
    def name(self) -> str: return self._name

    @property
    def channel_type(self) -> str: return "file"

    def write(self, data: Dict[str, Any]) -> Dict[str, Any]:
        with open(self._path, "a") as f:
            import json; f.write(json.dumps(data) + "\n")
        return {"status": "success", "channel": self._name}

    def close(self) -> None: pass


# 3. Создать менеджер
class MyManager(ChannelRoutingManager):
    def __init__(self, config=None):
        cfg = MyManagerConfig() if config is None else config

        super().__init__(
            "MyManager",
            config=cfg,
            buffer_strategy=BatchBuffer(
                flush_fn=self._on_flush,
                config=BatchConfig(max_size=100, flush_interval=1.0),
            ),
            dispatcher_key_field="event_type",
        )
        self._output_ch = MyChannel("output", "data/output.jsonl")

    def _on_flush(self, channel: str, batch: List[Dict]) -> None:
        ch = self._channel_registry.get(channel)
        if ch:
            for item in batch:
                ch.write(item)

    def initialize(self) -> bool:
        result = super().initialize()
        if result:
            self.register_channel(self._output_ch)
            self.register_route("data_event", "output")
            self.register_route("error_event", "output")
        return result

    def emit(self, event_type: str, payload: dict) -> None:
        self.route({"event_type": event_type, **payload})


# 4. Использовать
mgr = MyManager()
mgr.initialize()
mgr.emit("data_event", {"value": 42, "sensor": "A1"})
mgr.emit("error_event", {"code": "E_001", "msg": "sensor offline"})
mgr.flush()
mgr.shutdown()
```

---

## Примеры из реальных наследников

### LoggerManager — BatchBuffer + scope routing

```python
class LoggerManager(ChannelRoutingManager, ILoggerManager):
    def __init__(self, config=None):
        super().__init__(
            "LoggerManager",
            buffer_strategy=BatchBuffer(flush_fn=self._flush_batch),
            dispatcher_key_field="level",
        )
        self._buffer = BatchBuffer(...)

    def info(self, msg, module="main"):
        self.log(LogScope.BUSINESS, LogLevel.INFO, msg, module)

    def log(self, scope, level, message, module, **extra):
        record_dict = LogRecord(...).to_dict()
        channels = scope_config.channels
        for ch_name in channels:
            self._buffer.enqueue(ch_name, record_dict)
```

### ErrorManager — _level_to_channel + level routing

```python
class ErrorManager(LoggerManager):
    def initialize(self) -> bool:
        result = super().initialize()
        self._setup_level_routes()
        return result

    def _setup_level_routes(self) -> None:
        # Прямой маппинг: O(1) lookup вместо scope-based routing
        self._level_to_channel = {
            "CRITICAL": "critical_file",
            "ERROR":    "errors_file",
            "WARNING":  "warnings_file",
        }

    def log(self, scope, level, message, module, **extra):
        channel_name = self._level_to_channel.get(level.value)
        if channel_name:
            # КРИТИЧЕСКИ ВАЖНО: level routing РЕАЛЬНО вызывается
            self._buffer.enqueue(channel_name, record_dict)
        else:
            LoggerManager.log(self, ...)  # DEBUG/INFO → scope-based
```

### RouterManager — channel_dispatcher + message_dispatcher

```python
class RouterManager(ChannelRoutingManager):
    def __init__(self, ...):
        super().__init__("RouterManager", ...)
        self._sender = AsyncSender(...)      # Полный pipeline с middleware
        self.channel_dispatcher = self._dispatcher  # alias из CRM
        self.message_dispatcher = Dispatcher(...)   # для ВХОДЯЩИХ

    def register_channel(self, channel):
        # Override: inject _attach_logger, NO auto-dispatcher registration
        channel._attach_logger(self._log_warning, self._log_error)
        return self._channel_registry.register(channel)

    def register_route(self, key, channel_name):
        # Name-returning handler (не write-handler как в CRM)
        return self.channel_dispatcher.register_handler(
            key, handler=lambda msg: channel_name
        )
```

---

## Структура модуля

```
channel_routing_module/
├── interfaces.py             — IChannel, IBufferStrategy, IChannelRoutingManager
├── __init__.py               — публичный API
├── README.md                 — этот файл
├── STATUS.md                 — карточка здоровья
├── DECISIONS.md              — ADR-013…016, ADR-108
│
├── core/
│   ├── channel_routing_manager.py  — ChannelRoutingManager (BaseManager + ObservableMixin)
│   ├── channel_registry.py         — ChannelRegistry (thread-safe, generic IChannel)
│   ├── config.py                   — ChannelRoutingConfig(RegisterBase)
│   └── config_normalizer.py        — normalize_config(None|dict|RegisterBase → dict)
│
├── buffers/
│   ├── direct_buffer.py            — DirectBuffer (прямой вызов, для тестов)
│   ├── async_sender_buffer.py      — AsyncSenderBuffer (PriorityQueue + worker thread)
│   └── batch_buffer.py             — BatchBuffer (deque + lock + timer flush)
│
└── tests/
    ├── test_channel_routing_manager.py  — 18 тестов
    ├── test_channel_registry.py         — 17 тестов
    └── test_buffers.py                  — 23 теста
```

---

## Зависимости

```
channel_routing_module
    ← base_manager     (BaseManager, ObservableMixin, IBaseManager)
    ← dispatch_module  (Dispatcher, DispatchStrategy)
    ← data_schema_module (RegisterBase, FieldMeta, register_schema)

Зависит от:       base_manager, dispatch_module, data_schema_module
НЕ зависит от:    router_module, logger_module, error_module
Используется в:   logger_module, error_module, router_module
```

**Нет циклов**: `channel_routing_module → dispatch_module → base_manager`

---

## Запуск тестов

```bash
cd multiprocess_framework/refactored

# Только channel_routing_module (58 тестов)
pytest modules/channel_routing_module/tests/ -v

# Вся иерархия (155 тестов)
pytest modules/channel_routing_module/tests/ \
       modules/logger_module/tests/ \
       modules/error_module/tests/ \
       modules/router_module/tests/ -v
```

Ожидаемый результат: **155 passed** — все тесты зелёные.

---

## Что было унифицировано (итог)

| До | После | Выигрыш |
|---|---|---|
| 3 разных `ChannelRegistry` | Один в CRM | thread-safety везде |
| 2 разных буфера (`AsyncSender`, `BatchManager`) | 3 стратегии в CRM | выбор стратегии без дублирования кода |
| `LogConfig` (dataclass), `ErrorManagerConfig(RegisterBase)`, RouterManager без конфига | `ChannelRoutingConfig(RegisterBase)` как база | единый путь в ConfigManager |
| `_setup_level_routes()` регистрировал маршруты которые никогда не вызывались | `ErrorManager.log()` переопределён, level routing РЕАЛЬНО работает | исправлена скрытая архитектурная ошибка |
| `channels: Dict` без lock в LoggerManager | `_channel_registry` (RLock) из CRM | thread-safe |
| `IMessageChannel` и `ILogChannel` — изолированные иерархии | `IMessageChannel(IChannel)`, `ILogChannel(IChannel)` | единый тип для ChannelRegistry |
| Новый менеджер = копирование кода из 3 мест | Новый менеджер = наследование CRM | 10 минут вместо дня |
