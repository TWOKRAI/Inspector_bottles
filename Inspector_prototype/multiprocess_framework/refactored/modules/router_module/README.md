# router_module

Единая точка маршрутизации сообщений. Каждый процесс создаёт **один по дефолту** `RouterManager` и общается с внешним миром только через него.

---

## Структура модуля

```
router_module/
├── interfaces.py            ← ЕДИНСТВЕННЫЙ публичный контракт (IRouterManager, IMessageChannel)
├── __init__.py              ← Публичный API (RouterManager, QueueChannel, RouterAdapter, ...)
│
├── core/
│   ├── router_manager.py    ← Фасад (BaseManager + ObservableMixin)
│   ├── _sender.py           ← AsyncSender — PriorityQueue + фоновый поток отправки
│   ├── _receiver.py         ← AsyncReceiver — фоновый поток приёма + callbacks
│   ├── _channel_registry.py ← ChannelRegistry — потокобезопасный реестр каналов
│   └── _middleware.py       ← MiddlewarePipeline — fn(msg)->dict|None конвейер
│
├── channels/
│   ├── base_channel.py      ← MessageChannel — базовый класс с инъекцией логирования
│   └── queue_channel.py     ← QueueChannel — queue.Queue / multiprocessing.Queue
│
├── adapters/
│   └── router_adapter.py    ← RouterAdapter — тонкая обёртка для ProcessModule
│
└── tests/
    ├── test_router_manager.py
    └── test_channels.py
```

---

## Архитектура потоков данных

```
ИСХОДЯЩЕЕ:
  send_async(msg, priority) ──► AsyncSender._queue (PriorityQueue)
                                      │ фоновый поток
  send(msg)                 ──────────┤
                                      ▼
                              MiddlewarePipeline (send)
                                      │
                              _resolve_channels(msg):
                                1. msg["channel"] задан  → O(1) lookup
                                2. channel_dispatcher     → exact/pattern/broadcast
                                      │
                              IMessageChannel.send(msg)

ВХОДЯЩЕЕ:
  AsyncReceiver (фоновый поток)
      └─ receive()
            └─ ChannelRegistry.poll_all()      ← все каналы опрашиваются
                  └─ MiddlewarePipeline (recv)
                        └─ message_dispatcher  ← fire-and-forget по command/type
                              └─ callbacks     ← зарегистрированы через add_message_callback
```

---

## Быстрый старт

```python
from multiprocessing import Queue
from multiprocess_framework.refactored.modules.router_module import (
    RouterManager, QueueChannel
)

router = RouterManager("my_router")

ctrl_q = Queue()
router.register_channel(QueueChannel("control", ctrl_q))

router.register_route("set_fps", "control")
router.register_message_handler("ack", lambda msg: print("ACK:", msg["data"]))

router.initialize()
router.start_listening(poll_interval=0.01)

# Отправка (sync)
result = router.send({"channel": "control", "command": "ping"})

# Отправка (async, non-blocking, для UI-потока)
router.send_async({"command": "set_fps", "data": {"fps": 30}}, priority="high")

router.shutdown()
```

---

## API RouterManager

### Жизненный цикл

| Метод | Описание |
|-------|----------|
| `initialize()` | Запустить AsyncSender. Вернуть `True` при успехе. |
| `shutdown()` | Остановить все потоки, очистить каналы и dispatcher'ы. |
| `cleanup()` | Alias для `shutdown()`. |

### Каналы

| Метод | Описание |
|-------|----------|
| `register_channel(channel)` | Зарегистрировать канал; автоматически инжектирует логирование. |
| `unregister_channel(name)` | Удалить канал по имени. |
| `get_channel(name)` | Получить канал по имени или `None`. |
| `get_all_channels()` | Список всех каналов. |

### Отправка

| Метод | Описание |
|-------|----------|
| `send(msg)` | Синхронная отправка. Блокирует поток. Возвращает `{"status": ...}`. |
| `send_async(msg, priority)` | Non-blocking. Кладёт в PriorityQueue AsyncSender'а. |

**Приоритеты `send_async`:** `"urgent"` → `"high"` → `"normal"` → `"low"`

**Разрешение канала** (по порядку):
1. `msg["channel"]` задан → прямой O(1) lookup
2. `channel_dispatcher.dispatch(msg)` → exact / pattern / broadcast

### Маршруты (channel_dispatcher)

| Метод | Описание |
|-------|----------|
| `register_route(key, channel_name, strategy, ...)` | Привязать ключ команды/типа к каналу. `channel_name=None` → берётся из `msg["channel"]`. |
| `register_broadcast_route(key, channel_names)` | Fan-out в несколько каналов. |
| `register_channel_handler(key, handler)` | Произвольный routing-handler `fn(msg) -> str\|List[str]`. |

### Получение

| Метод | Описание |
|-------|----------|
| `receive(timeout, return_messages)` | Sync poll всех каналов. `timeout=0` → non-blocking. |
| `start_listening(poll_interval)` | Запустить фоновый поток-приёмник. |
| `stop_listening()` | Остановить поток-приёмник. |
| `add_message_callback(cb)` | Зарегистрировать `cb(msg)` для async receive. |
| `remove_message_callback(cb)` | Удалить callback. |

### Обработчики входящих (message_dispatcher)

| Метод | Описание |
|-------|----------|
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
stats = router.get_stats()["router"]
# Счётчики: sent_attempted, sent_ok, received, errors, middleware_dropped,
#           queued_async, dropped, processed
# Состояние: sender_alive, listener_alive, send_queue_size, channels_count

info = router.get_dispatcher_info()
# → channel_dispatcher / message_dispatcher: handlers, scenarios, counts
```

---

## RouterAdapter (для ProcessModule)

`RouterAdapter` — тонкая обёртка над `RouterManager` с контекстом процесса.

```python
adapter = RouterAdapter(router_manager, process=self)
adapter.setup()

# Отправить в именованный канал (sender заполняется автоматически)
adapter.send_to_channel("process_2_worker_in", {"command": "ping", "data": {}})

# Получить входящие
for msg in adapter.receive():
    ...

# Callback-режим
adapter.add_callback(my_handler)
adapter.start_listening()
```

---

## Каналы

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

**Инъекция логирования:** `RouterManager.register_channel(ch)` автоматически подключает log-колбэки роутера к каналу через `_attach_logger()`. Ошибки из очереди попадают в `LoggerManager`.

### Создание кастомного канала

```python
from multiprocess_framework.refactored.modules.router_module import MessageChannel

class DbChannel(MessageChannel):
    def __init__(self, name: str, connection):
        super().__init__()      # log callbacks будут инжектированы роутером
        self._name = name
        self._conn = connection

    @property
    def name(self) -> str: return self._name

    @property
    def channel_type(self) -> str: return "db"

    def send(self, message):
        try:
            self._conn.insert(message)
            return {"status": "success", "channel": self._name}
        except Exception as e:
            self._log_error(f"[DbChannel] insert failed: {e}")   # ← идёт в LoggerManager
            return {"status": "error", "reason": str(e)}

    def poll(self, timeout=0.0):
        return []   # push-канал, polling не нужен
```

---

## Интеграция с LoggerManager и ErrorManager

`RouterManager` наследует `BaseManager + ObservableMixin`. Подключение через конструктор:

```python
router = RouterManager("my_router", managers={"logger": logger_manager})
```

После этого все `_log_info / _log_warning / _log_error` внутри роутера и каналов идут через `LoggerManager`.

**Текущее состояние интеграции:**
- `LoggerManager` — подключается через `ObservableMixin` ✅
- `ErrorManager` — не подключён, планируется через `ObservableMixin` в будущем
- `StatsManager` — не реализован, планируется

---

## Тесты

```bash
python -m pytest multiprocess_framework/refactored/modules/router_module/tests/ -v
```

Покрытие (~797 строк):
- Жизненный цикл: `initialize` / `shutdown` / `cleanup`
- Каналы: register / unregister / get / invalid object
- `send()`: explicit channel, registered route, no route → error
- `send_async()`: non-blocking, все приоритеты, доставка
- Broadcast: fan-out, results contain channel names
- `receive()`: Message objects, dict mode, source_channel tag, counters
- `message_dispatcher`: handlers при receive
- Middleware: обогащение, drop → None
- Async listener + callback
- Thread safety
- `get_stats()` / `get_dispatcher_info()`

---

## Roadmap / Что не хватает

| Задача | Приоритет | Этап |
|--------|-----------|------|
| `correlation_id` для request-response паттерна | Высокий | 5 |
| Интеграция `ErrorManager` через ObservableMixin | Средний | 4 |
| `StatsManager` — структурированная статистика | Средний | 6 |
| Config-driven channels (объявление каналов через конфиг процесса) | Высокий | 3 |
| `SocketChannel` — TCP/UDP между процессами | Низкий | 7 |
| `DbChannel`, `LogChannel`, `TelegramChannel` | Низкий | 8 |
