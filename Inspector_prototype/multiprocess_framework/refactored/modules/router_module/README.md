# router_module

Единая точка маршрутизации сообщений в многопроцессной системе.  
Каждый процесс, поток или сервис создаёт **один** `RouterManager` — и общается с внешним миром только через него.

---

## Концепция

```
┌─────────────────────────────────────────────────────────┐
│  Ваш процесс                                            │
│                                                         │
│  UI / бизнес-логика                                     │
│       │ send_async() / send()                           │
│       ▼                                                 │
│  RouterManager                                          │
│    ├─ channel_dispatcher  → выбирает канал              │
│    │     EXACT   "set_register"  → "control_queue"      │
│    │     PATTERN r"cam_.*"       → из msg["channel"]    │
│    │     FALLBACK                → приоритетный канал   │
│    │     BROADCAST "alert"       → [ch1, ch2, ch3]      │
│    │                                                     │
│    ├─ MessageChannel (send)                              │
│    │     QueueChannel  — mp.Queue / queue.Queue          │
│    │     SocketChannel — (будущее)                       │
│    │     HttpChannel   — (будущее)                       │
│    │     DbChannel     — (будущее)                       │
│    │                                                     │
│    └─ message_dispatcher  ← входящие сообщения          │
│          exact / pattern / fallback / scenario          │
└─────────────────────────────────────────────────────────┘
```

Роутер **не содержит** бизнес-логику — только маршрутизацию.  
Все правила прописываются снаружи через `register_route()` / `register_message_handler()`.

---

## Быстрый старт

```python
from multiprocessing import Queue
from multiprocess_framework.refactored.modules.router_module import RouterManager, QueueChannel
from multiprocess_framework.refactored.modules.message_module import Message

# 1. Создаём роутер
router = RouterManager("ui_router")

# 2. Подключаем каналы
ctrl_q = Queue()
router.register_channel(QueueChannel("control", ctrl_q))
router.register_channel(QueueChannel("logging", Queue()))

# 3. Регистрируем маршруты исходящих
router.register_route("set_register", "control")         # exact
router.register_route("cam_.*", None,                    # pattern → из msg["channel"]
    strategy=DispatchStrategy.PATTERN_MATCH)
router.register_broadcast_route("alert", ["control", "logging"])

# 4. Регистрируем обработчики входящих
router.register_message_handler("ack", lambda msg: print("ACK:", msg))

# 5. Запускаем
router.initialize()
router.start_listening(poll_interval=0.01)

# 6. Отправка из UI-потока — НЕ блокирует
router.send_async(
    Message.create("command", sender="ui", command="set_register", data={"fps": 30}),
    priority="high"
)

# 7. Синхронная отправка (тесты, фоновые потоки)
result = router.send({"channel": "control", "command": "ping"})

# 8. Завершение
router.shutdown()
```

---

## API

### Жизненный цикл

| Метод | Описание |
|-------|----------|
| `initialize()` | Запускает фоновый поток-отправщик |
| `shutdown()` | Останавливает потоки, очищает каналы и dispatcher'ы |
| `cleanup()` | Alias для `shutdown()` |

### Каналы

| Метод | Описание |
|-------|----------|
| `register_channel(ch)` | Зарегистрировать канал (`QueueChannel`, ...) |
| `unregister_channel(name)` | Удалить канал |
| `get_channel(name)` | Получить канал по имени |
| `get_all_channels()` | Список всех каналов |

### Отправка (исходящие)

| Метод | Описание |
|-------|----------|
| `send(msg)` | Синхронная отправка — блокирует поток |
| `send_async(msg, priority)` | **Non-blocking** — безопасна для UI-потока |

**Приоритеты `send_async`:** `"urgent"` → `"high"` → `"normal"` → `"low"`

**Разрешение канала** (по приоритету):
1. `msg["channel"]` задан → прямой O(1) lookup
2. `channel_dispatcher.dispatch(msg)` → exact / pattern / fallback / broadcast

### Маршруты (channel_dispatcher)

| Метод | Описание |
|-------|----------|
| `register_route(key, channel_name, strategy, efficiency, tags)` | Привязать ключ к каналу |
| `register_broadcast_route(key, channel_names)` | Fan-out в несколько каналов |
| `register_channel_scenario(name, channel_names)` | Chain-broadcast через scenario |
| `register_channel_handler(key, handler)` | Произвольный routing-handler |

### Получение (входящие)

| Метод | Описание |
|-------|----------|
| `receive(timeout, return_messages)` | Sync poll всех каналов |
| `start_listening(poll_interval)` | Запустить фоновый поток-приёмник |
| `stop_listening()` | Остановить поток-приёмник |
| `add_message_callback(cb)` | Callback для async receive |
| `remove_message_callback(cb)` | Удалить callback |

### Обработчики входящих (message_dispatcher)

| Метод | Описание |
|-------|----------|
| `register_message_handler(key, handler, ...)` | Exact/pattern/fallback обработчик |
| `register_message_scenario(name)` | Создать chain-сценарий обработки |
| `add_handler_to_message_scenario(name, key, handler, stage)` | Добавить шаг |

### Middleware

```python
# Исходящие: обогащение, подпись, фильтрация, шифрование
router.add_send_middleware(lambda msg: {**msg, "_ts": time.time()})

# Входящие: валидация, авторизация, декодирование
router.add_receive_middleware(lambda msg: msg if msg.get("auth") else None)

router.clear_middleware()  # сбросить всё
```

### Мониторинг

```python
# Полная статистика
stats = router.get_stats()["router"]
# → sent, sent_async, received, errors, middleware_dropped
# → channels_count, channel_handlers, message_handlers
# → sender_alive, listener_alive, send_queue_size

# Состояние dispatcher'ов
info = router.get_dispatcher_info()
# → channel_dispatcher.handlers / scenarios / handler_count
# → message_dispatcher.handlers / scenarios / handler_count
```

---

## Каналы

### Уже реализовано

| Класс | Тип | Назначение |
|-------|-----|------------|
| `QueueChannel` | `queue` | `queue.Queue` / `multiprocessing.Queue` |

### Roadmap (расширение без изменения роутера)

| Класс | Тип | Назначение |
|-------|-----|------------|
| `SocketChannel` | `socket` | TCP/UDP между процессами / машинами |
| `HttpChannel` | `http` | REST API / webhooks |
| `DbChannel` | `db` | Запись в БД (PostgreSQL, Redis, ...) |
| `LogChannel` | `log` | Структурированное логирование |
| `TelegramChannel` | `telegram` | Уведомления |

Добавление нового канала = реализовать `MessageChannel.send()` и `MessageChannel.poll()`.

---

## Интеграция с dispatch_module

`RouterManager` использует два `Dispatcher` из `dispatch_module`:

```
channel_dispatcher   — для исходящих → возвращает str | List[str] (имена каналов)
message_dispatcher   — для входящих  → вызывает зарегистрированные handler'ы
```

Поддерживаемые стратегии:
- `EXACT_MATCH` — точное совпадение ключа O(1)
- `PATTERN_MATCH` — regex-паттерн
- `FALLBACK_MATCH` — приоритетный выбор по efficiency
- `CHAIN_MATCH` — цепочка шагов (scenario)

---

## Тесты

```bash
# Из корня Inspector_prototype
python -m pytest multiprocess_framework/refactored/modules/router_module/tests/ -v
```

Покрытие тестов:
- Жизненный цикл (initialize / shutdown / cleanup)
- Управление каналами (register / unregister / get)
- `send()` — explicit channel, registered route, error on missing route
- `send_async()` — non-blocking, доставка, все приоритеты
- Broadcast маршрутизация
- `receive()` — sync poll, dict-интерфейс Message, source_channel
- `message_dispatcher` — обработчики при receive
- Middleware send / receive (обогащение, drop)
- `register_channel_handler()` backward compat
- `get_dispatcher_info()` / `get_stats()`
- Async listener с callback
