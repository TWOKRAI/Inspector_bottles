# router_module

Единая точка маршрутизации сообщений между процессами. Каждый процесс создаёт **один по дефолту**
`RouterManager` (наследует `ChannelRoutingManager`) и общается с внешним миром только через него.

---

## Архитектура и наследование

```
BaseManager + ObservableMixin
        │
        ▼
ChannelRoutingManager  ← базовый класс для менеджеров с каналами
        │
        ▼
RouterManager  (AsyncSender, channel+message dispatchers, IMessageChannel)
        │
        Специфичное для RouterManager:
        ├─ AsyncSender — сохранён для полного pipeline (middleware перед буферизацией)
        ├─ channel_dispatcher — для исходящих (из CRM._dispatcher)
        ├─ message_dispatcher — для входящих
        └─ _resolve_channels() — name-returning handler паттерн
```

**Что дал RouterManager от ChannelRoutingManager:**
- `_channel_registry` (thread-safe из CRM) вместо локального ChannelRegistry
- `_dispatcher` — встроенный dispatcher из CRM для channel-routing
- Интеграция через ObservableMixin (LoggerManager, ErrorManager)
- Единая иерархия `IMessageChannel(IChannel)`

**Что остаётся специфичным RouterManager:**
- AsyncSender — полный pipeline с middleware (применяется ПЕРЕД буферизацией)
- message_dispatcher — для входящих сообщений (отдельно от channel_dispatcher)
- _attach_logger() — инъекция логирования в каналы
- name-returning handler паттерн (handler возвращает str → имя канала)

---

## Роль в архитектуре

```
ИСХОДЯЩИЕ СООБЩЕНИЯ:
┌─────────────────────────────────────────────────────────────┐
│ RouterManager (наследует ChannelRoutingManager)             │
│                                                             │
│  send_async(msg, priority)  ──→ AsyncSender._queue        │
│                               (PriorityQueue)              │
│  send(msg)  ─────────────────┐                            │
│                              ▼                            │
│                 MiddlewarePipeline (send)                  │
│                      ↓                                     │
│         _resolve_channels(msg):                           │
│         1. msg["channel"] задан → O(1) lookup             │
│         2. channel_dispatcher → exact/pattern/broadcast   │
│                      ↓                                     │
│           IMessageChannel.send(msg)                        │
│           ├─ QueueChannel → queue.put()                   │
│           └─ кастомные: SocketChannel, DbChannel, ...    │
└─────────────────────────────────────────────────────────────┘

ВХОДЯЩИЕ СООБЩЕНИЯ:
┌─────────────────────────────────────────────────────────────┐
│ AsyncReceiver (фоновый поток)                              │
│    └─ receive()                                            │
│         └─ ChannelRegistry.poll_all() (из CRM)             │
│              ├─ MiddlewarePipeline (recv)                 │
│              └─ message_dispatcher ← fire-and-forget      │
│                   └─ callbacks ← зарегистрированы         │
│                      через add_message_callback           │
└─────────────────────────────────────────────────────────────┘
```

---

## Структура модуля

```
router_module/
├── interfaces.py            ← ЕДИНСТВЕННЫЙ публичный контракт
│                              (IRouterManager, IMessageChannel)
├── __init__.py              ← Публичный API
│
├── core/
│   ├── router_manager.py    ← RouterManager(ChannelRoutingManager)
│   ├── _sender.py           ← AsyncSender — PriorityQueue + фоновый поток
│   ├── _receiver.py         ← AsyncReceiver — фоновый поток приёма
│   └── _middleware.py       ← MiddlewarePipeline — fn(msg)->dict|None
│
├── channels/
│   ├── base_channel.py      ← MessageChannel(IMessageChannel) — базовый класс
│   └── queue_channel.py     ← QueueChannel — queue.Queue / mp.Queue
│
├── adapters/
│   └── router_adapter.py    ← RouterAdapter — тонкая обёртка для ProcessModule
│
└── tests/
    ├── test_router_manager.py
    └── test_channels.py
```

---

## Быстрый старт

```python
from multiprocessing import Queue
from router_module import RouterManager, QueueChannel

router = RouterManager("my_router")

ctrl_q = Queue()
router.register_channel(QueueChannel("control", ctrl_q))

router.register_route("set_fps", "control")
router.register_message_handler("ack", lambda msg: print("ACK:", msg["data"]))

router.initialize()
router.start_listening(poll_interval=0.01)

# Отправка (sync)
result = router.send({"channel": "control", "command": "ping"})

# Отправка (async, non-blocking)
router.send_async({"command": "set_fps", "data": {"fps": 30}}, priority="high")

router.shutdown()
```

---

## API: RouterManager

### Жизненный цикл

| Метод | Описание |
|---|---|
| `initialize()` | Запустить AsyncSender, инициализировать каналы из CRM. Возвращает `True`. |
| `shutdown()` | Остановить AsyncSender/AsyncReceiver, очистить каналы и dispatchers. |
| `cleanup()` | Alias для `shutdown()`. |

### Каналы (IMessageChannel из CRM)

| Метод | Описание |
|---|---|
| `register_channel(channel)` | Зарегистрировать канал; автоматически инжектирует логирование. |
| `unregister_channel(name)` | Удалить канал по имени. |
| `get_channel(name)` | Получить канал по имени или `None`. |
| `get_all_channels()` | Список всех каналов. |

### Отправка

| Метод | Описание |
|---|---|
| `send(msg)` | Синхронная отправка. Блокирует поток. Возвращает `{"status": ...}`. |
| `send_async(msg, priority)` | Non-blocking. Кладёт в PriorityQueue AsyncSender'а. |

**Приоритеты `send_async`:** `"urgent"` → `"high"` → `"normal"` → `"low"`

**Разрешение канала** (по порядку):
1. `msg["channel"]` задан → прямой O(1) lookup в `_channel_registry`
2. `channel_dispatcher.dispatch(msg)` → exact / pattern / broadcast (из CRM)

### Маршруты (channel_dispatcher из CRM)

| Метод | Описание |
|---|---|
| `register_route(key, channel_name, strategy, ...)` | Привязать ключ команды/типа к каналу. `channel_name=None` → берётся из `msg["channel"]`. |
| `register_broadcast_route(key, channel_names)` | Fan-out в несколько каналов. |
| `register_channel_handler(key, handler)` | Произвольный routing-handler `fn(msg) -> str\|List[str]`. |

### Получение

| Метод | Описание |
|---|---|
| `receive(timeout, return_messages)` | Sync poll всех каналов. `timeout=0` → non-blocking. |
| `start_listening(poll_interval)` | Запустить фоновый поток-приёмник (AsyncReceiver). |
| `stop_listening()` | Остановить поток-приёмник. |
| `add_message_callback(cb)` | Зарегистрировать `cb(msg)` для async receive. |
| `remove_message_callback(cb)` | Удалить callback. |

### Обработчики входящих (message_dispatcher)

| Метод | Описание |
|---|---|
| `register_message_handler(key, handler, ...)` | Вызывается автоматически при `receive()` по ключу `command`/`type`. |
| `register_message_scenario(name)` | Создать chain-сценарий. |
| `add_handler_to_message_scenario(name, key, handler, stage)` | Добавить шаг. |

### Middleware

```python
# Обогатить исходящие меткой времени
router.add_send_middleware(lambda msg: {**msg, "_ts": time.time()})

# Отфильтровать входящие без авторизации
router.add_receive_middleware(lambda msg: msg if msg.get("auth") else None)

router.clear_middleware()
```

### Мониторинг

```python
stats = router.get_stats()
# Счётчики: sent_attempted, sent_ok, received, errors, ...
# Состояние: sender_alive, listener_alive, send_queue_size, channels_count

info = router.get_dispatcher_info()
# → channel_dispatcher / message_dispatcher: handlers, scenarios, counts
```

---

## Каналы (IMessageChannel)

Все каналы наследуют `IMessageChannel(IChannel)` из `channel_routing_module`:

```python
class IMessageChannel(IChannel):
    @property
    def name(self) -> str: ...
    @property
    def channel_type(self) -> str: return "message"
    def write(self, data: Dict[str, Any]) -> Dict[str, Any]: ...  # → send(data)
    def send(self, message: dict) -> dict: ...
    def poll(self, timeout: float = 0.0) -> List[dict]: ...
    def start_listening(self, callback: Callable) -> None: ...
    def stop_listening(self) -> None: ...
    def close(self) -> None: ...
    def get_info(self) -> Dict[str, Any]: ...
```

### QueueChannel

```python
# С существующей очередью
ch = QueueChannel("ctrl", mp_queue)

# Создаёт внутренний queue.Queue
ch = QueueChannel("local")

# Методы
ch.send(msg, timeout=1.0)   # → {"status": "success"|"error", ...}
ch.poll(timeout=0.0)        # → List[dict]
ch.start_listening(callback)
ch.stop_listening()
ch.get_info()               # → {"name", "type", "queue_size", "listening"}
```

**Инъекция логирования:** `RouterManager.register_channel(ch)` автоматически подключает
log-колбэки роутера к каналу через `_attach_logger()`. Ошибки из очереди попадают в `LoggerManager`.

### Кастомный канал

```python
from router_module import MessageChannel

class DbChannel(MessageChannel):
    def __init__(self, name: str, connection):
        super().__init__()      # log callbacks будут инжектированы роутером
        self._name = name
        self._conn = connection

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "db"

    def send(self, message):
        try:
            self._conn.insert(message)
            return {"status": "success", "channel": self._name}
        except Exception as e:
            self._log_error(f"[DbChannel] insert failed: {e}")  # ← идёт в LoggerManager
            return {"status": "error", "reason": str(e)}

    def poll(self, timeout=0.0):
        return []   # push-канал, polling не нужен
```

---

## RouterAdapter (для ProcessModule)

`RouterAdapter` — тонкая обёртка над `RouterManager` с контекстом процесса.

```python
adapter = RouterAdapter(router_manager, process=self)
adapter.setup()

# Отправить в именованный канал
adapter.send_to_channel("process_2_worker_in", {"command": "ping", "data": {}})

# Получить входящие
for msg in adapter.receive():
    ...

# Callback-режим
adapter.add_callback(my_handler)
adapter.start_listening()
```

---

## Интеграция с LoggerManager и ErrorManager

`RouterManager` наследует `ChannelRoutingManager`, который наследует `ObservableMixin`.
Подключение через конструктор:

```python
from logger_module import LoggerManager
from error_module import ErrorManager

logger = LoggerManager()
errors = ErrorManager()

router = RouterManager(
    "my_router",
    config=None,
    observable_config={
        "logger": logger,
        "errors": errors,
    }
)
```

После этого все `_log_info / _log_warning / _log_error` внутри роутера и каналов идут
через `LoggerManager` (и затем через `ErrorManager` для ERROR/CRITICAL).

**Текущее состояние интеграции:**
- `LoggerManager` — подключается через `ObservableMixin` ✅
- `ErrorManager` — подключается через `ObservableMixin` (наследует от LoggerManager) ✅
- `StatsManager` — не реализован, планируется в будущем

---

## Ключевой паттерн RouterManager — name-returning handlers

`RouterManager` имеет **уникальный паттерн**, отличающий его от обычного использования CRM:

```
register_route("order", "queue_channel")
    ↓ регистрирует: lambda msg → "queue_channel" (строка!)
    ↓ НЕ: lambda msg → channel.write(msg)   ← это путь обычного CRM
    ↓ ПОЧЕМУ: router сначала применяет middleware, ПОТОМ резолвит канал
```

`_resolve_channels(message)` → вызывает handler → получает str → `_channel_registry.get(str)` → `IMessageChannel.send(msg)`

**Это необходимо потому, что:**
1. Middleware должно применяться ПЕРЕД резолюцией канала
2. Handler может трансформировать данные, но решение о канале остаётся независимым
3. AsyncSender буферизует ПОЛНЫЙ pipeline (middleware + resolve), а не просто данные

---

## AsyncSender — почему остался, а не заменён на AsyncSenderBuffer

`ChannelRoutingManager` предоставляет `AsyncSenderBuffer(IBufferStrategy)` для простой буферизации.
RouterManager **не использует** его, сохраняя собственный `AsyncSender`. Причина (ADR-015):

- `AsyncSenderBuffer.enqueue(channel_name, data)` работает с **уже resolved** каналом
- `AsyncSender` буферизует **ВЕСЬ pipeline**: `enqueue(msg) → middleware → resolve → send`
- Middleware-трансформации должны происходить **ДО** резолюции канала

Пример: если middleware добавляет `_ts`, то это должно произойти перед отправкой в канал,
не после. `AsyncSenderBuffer` не поддерживает этот usecase.

---

## Dict at Boundary

| Формат | Пример |
|---|---|
| `None` | `RouterManager()` — дефолтный конфиг |
| `dict` | `{"manager_name": "router", "channels": {...}}` |
| Объект с `build()` | `build()` возвращает `(manager_name: str, config: dict)` |

---

## Тесты

```bash
cd multiprocess_framework/refactored
pytest modules/router_module/tests/ -v
```

Покрытие (~37 тестов, ~797 строк):
- Жизненный цикл: `initialize()` / `shutdown()` / `cleanup()`
- Каналы: register / unregister / get / invalid object
- `send()`: explicit channel, registered route, no route → error
- `send_async()`: non-blocking, все приоритеты, доставка
- Broadcast: fan-out, results contain channel names
- `receive()`: Message objects, dict mode, source_channel tag
- `message_dispatcher`: handlers при receive
- Middleware: обогащение, drop → None
- Async listener + callback
- Thread safety
- `get_stats()` / `get_dispatcher_info()`
- Logger injection в каналы

---

## Контракт хаба: routing-таблица + address-aware канал (P0.2 transport-router-hub)

Подмодуль `router_module.routing` — **декларация** целевого контракта хаба (проводка
в рантайм — P1, здесь без смены поведения). Замысел: `send` выбирает **один** канал по
типу груза, имя канала склеивается с адресом получателя.

**Две ортогональные оси билета:** `address` = *куда* (иерархия `process[.worker]`),
`kind` = *что за груз* (канал). Имя канала = `f"{process}_{kind}"` — совпадает с
существующими очередями `{proc}_system` / `{proc}_data`.

```python
from multiprocess_framework.modules.router_module import (
    MESSAGE_TYPE_TO_CHANNEL, resolve_channel_kind, channel_name, resolve_routes,
)

resolve_channel_kind({"type": "command", "command": "worker.create"})  # → "system"
resolve_channel_kind({"type": "event", "command": "state.changed"})     # → "state"  ← см. ниже
channel_name("camera", "data")                                          # → "camera_data"
resolve_routes({"type": "data", "target": "display"})  # → [RouteDecision(process="display", kind="data", channel="display_data", subpath=[])]
```

**Нормализация `command`/`type` → kind (находка recon #1):** на живых билетах поле `type`
не всегда соответствует целевому каналу (диспатч исторически идёт по `command`). Резолвер
сперва проверяет префикс `command` (`state.*` → `state`-канал), затем таблицу по
`MessageType`. Поэтому **STATE — это channel-kind, выводимый из `command`, а не член enum
`MessageType`** (новый `kind` план запрещает). Неизвестный `type` без покрытия префиксом →
`UnknownMessageTypeError` (громкий отказ вместо тихого drop, требование P1.2).

| Что | Символ | Статус P0.2 |
|---|---|---|
| Таблица `MessageType → kind` | `MESSAGE_TYPE_TO_CHANNEL` | объявлена; проводка через `register_route` — P1 |
| Нормализатор kind | `resolve_channel_kind(msg)` | реализован (чистый), используется в `_resolve_channels` — P1 |
| Имя канала | `channel_name(process, kind)` | реализован |
| Резолвер маршрута (ядро `send` address-aware канала) | `resolve_route` / `resolve_routes` → `RouteDecision` | реализован (чистый); сам канал-подкласс — P1.1 |

Контракт address-aware канала (подкласс `MessageChannel`, **без нового Protocol**) и решения
по находкам recon #2/#3/#4/#6 — в docstring `routing/address_aware_channel.py`.

---

## Roadmap / Что не хватает

| Задача | Приоритет | Этап |
|--------|-----------|------|
| `correlation_id` для request-response паттерна | Высокий | 5 |
| Config-driven channels (объявление через конфиг процесса) | Высокий | 3 |
| `StatsManager` — структурированная статистика | Средний | 6 |
| `SocketChannel` — TCP/UDP между процессами | Низкий | 7 |
| `DbChannel`, `TelegramChannel` примеры | Низкий | 8 |
