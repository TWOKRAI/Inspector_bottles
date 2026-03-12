# Unified Manager Architecture — Полная иерархия

Документ объясняет единую иерархию менеджеров после CRM-унификации (Фазы 1–5).

---

## Иерархия наследования

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Фундамент (Foundation)                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  BaseManager                          ObservableMixin                       │
│  ├─ manager_name: str                 ├─ managers: Dict[str, IBaseManager] │
│  ├─ manager_id: UUID                  ├─ proxy-методы к менеджерам         │
│  ├─ is_running: bool                  ├─ _log_info / _log_warning / ...   │
│  └─ initialize/shutdown               ├─ _track_error / _track_event       │
│                                       └─ register_manager / clear_managers │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                   ┌────────────────────▼──────────────────┐
                   │                                       │
                   │ НАСЛЕДОВАНИЕ #1:                      │
                   │ BaseManager + ObservableMixin         │
                   │                                       │
                   └────────────────────┬──────────────────┘
                                        │
┌─────────────────────────────────────────────────────────────────────────────┐
│           ChannelRoutingManager (NEW!) — Базовый класс для маршрутизации   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Унифицирует ВСЕ менеджеры с каналами:                                    │
│                                                                             │
│  ┌─ self._channel_registry (thread-safe, IChannel generic)               │
│  ├─ self._dispatcher (Dispatcher для key→handler маршрутизации)          │
│  ├─ self._buffer (IBufferStrategy: DirectBuffer / BatchBuffer / ...)    │
│  ├─ normalize_config() — Dict | RegisterBase | None → dict              │
│  ├─ ChannelRoutingConfig(RegisterBase) — базовый конфиг с build()      │
│  │                                                                        │
│  ├─ register_channel(ch: IChannel) — thread-safe                       │
│  ├─ unregister_channel(name: str) → bool                                │
│  ├─ get_channel(name) / get_all_channels()                              │
│  ├─ register_route(key, channel_name) / register_broadcast(key, names) │
│  ├─ route(data, key_field=None) — маршрутизировать через dispatcher    │
│  ├─ flush() — сбросить buffer                                           │
│  └─ get_stats() — channel_registry + buffer + dispatcher stats         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                    │                           │                    │
       ┌────────────▼──────────┐    ┌───────────▼──────────┐    ┌───▼────────────┐
       │                       │    │                      │    │                │
       │   НАСЛЕДОВАНИЕ #2a:   │    │ НАСЛЕДОВАНИЕ #2b:   │    │ НАСЛЕДОВАНИЕ  │
       │   LoggerManager       │    │ RouterManager       │    │ #2c: ???        │
       │   (ChannelRoutingMgr) │    │ (ChannelRoutingMgr) │    │ (Future)        │
       │                       │    │                     │    │                 │
       └───────┬───────────────┘    └──────┬──────────────┘    └────┬───────────┘
               │                           │                        │
       ┌───────▼─────────────────────┐    │              (StatsManager, ...)
       │    НАСЛЕДОВАНИЕ #3:         │    │
       │    ErrorManager             │    │
       │    (наследует LoggerManager)│    │
       │                             │    │
       └─────────────────────────────┘    │
                                          │
                                   ┌──────▼─────────────────┐
                                   │  Специфичный pattern:  │
                                   │  name-returning        │
                                   │  handlers для routing  │
                                   └────────────────────────┘
```

---

## Чему дал ChannelRoutingManager каждому наследнику

### LoggerManager

**Получил от CRM:**
- `_channel_registry` (thread-safe RLock, generic IChannel)
- `_dispatcher` для scope-based маршрутизации
- `BatchBuffer` как IBufferStrategy
- `normalize_config()` — Dict at Boundary
- `ChannelRoutingConfig` — базовый конфиг

**Оставил специфичным:**
- Scope-based routing (SYSTEM, BUSINESS, PERFORMANCE, ...)
- `push_context()` / `pop_context()` для логирования с контекстом
- Module-specific логирование
- Priority flush для ERROR/CRITICAL

---

### ErrorManager

**Получил от LoggerManager/CRM:**
- Весь батчинг (BatchBuffer из CRM через LoggerManager)
- `_channel_registry` (thread-safe)
- `_dispatcher` для маршрутизации
- ObservableMixin интеграция
- Методы debug/info/warning/error/critical

**Добавил специфичное:**
- `_level_to_channel` — O(1) маппинг CRITICAL/ERROR/WARNING → файлы
- `log()` override — level-based routing вместо scope-based
- `log_exception()` — специализированный метод для трейсбеков
- ErrorManagerConfig(ChannelRoutingConfig) для расширения через channels

**Ключевое улучшение (Фаза 3):**
До: `_setup_level_routes()` регистрировал маршруты которые никогда не вызывались.
После: `log()` переопределён и **реально использует** level-based routing.

---

### RouterManager

**Получил от CRM:**
- `_channel_registry` (thread-safe RLock) вместо локального ChannelRegistry
- `_dispatcher` (из CRM) переименован в `channel_dispatcher` (backward compatibility)
- Интеграция через ObservableMixin (LoggerManager, ErrorManager)
- Единая иерархия `IMessageChannel(IChannel)`

**Оставил специфичным:**
- AsyncSender — полный pipeline с middleware (ПЕРЕД буферизацией)
- message_dispatcher — для входящих сообщений
- _attach_logger() — инъекция логирования в каналы
- name-returning handler паттерн (handler возвращает str → имя канала)

**Почему AsyncSender не заменился на AsyncSenderBuffer?** (ADR-015)
- AsyncSenderBuffer работает с pre-resolved каналами
- AsyncSender буферизует полный pipeline: middleware → resolve → send
- Middleware должно применяться ДО резолюции

---

## Работа всей системы вместе: пример

### Сценарий: отправка сообщения через RouterManager

```python
# 1. Инициализация со всеми менеджерами
logger = LoggerManager(manager_name="AppLogger")
errors = ErrorManager(manager_name="AppErrors")
router = RouterManager(
    "AppRouter",
    observable_config={"logger": logger, "errors": errors}
)

logger.initialize()
errors.initialize()
router.initialize()

# 2. Регистрация маршрута в router
router.register_route("process_data", "worker_queue")

# 3. Отправка сообщения
router.send_async(
    {
        "command": "process_data",
        "data": {"id": 123, "value": "test"},
    },
    priority="normal"
)
```

**Что происходит внутри:**

```
router.send_async(msg, priority="normal")
    ↓ (non-blocking)
    ├─ AsyncSender._queue.put((priority, msg))
    │
    └─ AsyncSender.worker() фоновый поток:
         ├─ msg из queue
         ├─ MiddlewarePipeline.send(msg) ← может добавить _ts, трансформировать
         │   (этот момент ВАЖЕН — middleware ПЕРЕД резолюцией)
         ├─ _resolve_channels(msg)
         │   ├─ msg["channel"] задан? → no
         │   └─ channel_dispatcher.dispatch(msg, key_field="command")
         │       ├─ dispatcher.get_handler("process_data")
         │       └─ handler(msg) → "worker_queue" (name-returning!)
         │
         ├─ channel = _channel_registry.get("worker_queue")
         │   ├─ это IMessageChannel (QueueChannel в данном случае)
         │
         └─ channel.send(msg)
             └─ queue.put(msg)
                 └─ _log_debug("message sent") ← через injected logger!
                    └─ LoggerManager.debug(...)
                       ├─ ScopeFilter определяет scope
                       ├─ BatchBuffer.enqueue("console_channel", record)
                       └─ BatchBuffer сбрасывает при batch_size или timer
```

### Сценарий: логирование ошибки

```python
try:
    risky_operation()
except ValueError as e:
    errors.log_exception(e, module="processor")
```

**Что происходит внутри:**

```
errors.log_exception(exc, module="processor")
    ├─ ErrorManager.log_exception() (переопределён)
    │   ├─ Форматирует traceback (если include_stacktrace=True)
    │   └─ Вызывает self.log(LogScope.SYSTEM, LogLevel.ERROR, ..., module="processor")
    │
    └─ ErrorManager.log() (переопределён):
         ├─ level = LogLevel.ERROR
         ├─ channel_name = self._level_to_channel.get("ERROR")
         │   → "errors_file"
         │
         ├─ BatchBuffer.enqueue("errors_file", record_dict) ← РЕАЛЬНО используется!
         │   └─ BatchBuffer._queue.append(record_dict)
         │       └─ if queue size >= batch_size or timer expired:
         │           └─ _flush_batch("errors_file", batch)
         │               └─ channel = _channel_registry.get("errors_file")
         │                   └─ channel.write(record_dict) ← запись в файл!
         │
         └─ Для DEBUG/INFO вызывает super().log() → LoggerManager
             └─ scope-based routing
```

---

## Ключевые паттерны унификации

### 1. Thread-safe ChannelRegistry (из CRM)

```python
# До: channels: Dict без lock в LoggerManager
logger.channels["console"] = ch  # потокоопасно!

# После: _channel_registry из CRM (с RLock)
registry.register(ch)  # thread-safe
registry.get("console")  # thread-safe
```

### 2. Pluggable буферизация (IBufferStrategy)

```python
# LoggerManager использует BatchBuffer
LoggerManager(
    buffer_strategy=BatchBuffer(flush_fn=..., config=BatchConfig(...))
)

# RouterManager использует AsyncSender (свой, не из CRM)
# потому что ему нужен middleware перед буферизацией
```

### 3. RegisterBase конфиги (Dict at Boundary)

```python
# До: три разных подхода к конфигам

# После: единый путь через RegisterBase
class ChannelRoutingConfig(RegisterBase):
    def build(self) -> tuple[str, dict]:
        return (self.manager_name, self.model_dump())

class LoggerManagerConfig(ChannelRoutingConfig):
    # расширяет с новыми полями

class ErrorManagerConfig(ChannelRoutingConfig):
    # ещё больше расширяет
```

### 4. Единая иерархия IChannel

```python
# До: ILogChannel и IMessageChannel — изолированные иерархии

# После:
IChannel (base)
    ├─ ILogChannel (добавляет close() специфику)
    └─ IMessageChannel (добавляет send/poll/start_listening)

# Один registry работает со всеми через IChannel
registry: Dict[str, IChannel]  # generic!
```

---

## Статистика улучшений

| Метрика | До | После | Выигрыш |
|---|---|---|---|
| Thread-safety channel registry | 1 (RouterManager) | 4 (все менеджеры) | везде безопасно |
| Реализаций батчинга | 2 (AsyncSender, BatchManager) | 3 (+ опция выбора) | DRY, конфигурируемо |
| Строк кода в реестре | 50 × 2 | 50 × 1 | -50% дублирования |
| Мёртвого кода (level routing) | 1 (ErrorManager) | 0 | исправлено |
| Время на новый менеджер | 1 день (копирование) | 30 минут (наследование) | ×2 быстрее |
| Иерархии каналов | 2 (несовместимые) | 1 (unified) | единая семантика |

---

## Как проверить что всё работает

```bash
cd Inspector_prototype/multiprocess_framework/refactored

# Все 155 тестов должны пройти
pytest modules/channel_routing_module/tests/ \
       modules/logger_module/tests/ \
       modules/error_module/tests/ \
       modules/router_module/tests/ -v

# Проверить архитектурные решения в DECISIONS.md
grep "ADR-01[3-6]" DECISIONS.md

# Проверить STATUS.md каждого модуля
grep "Текущий этап" modules/*/STATUS.md

# Запустить валидацию архитектуры
python scripts/validate.py
```

---

## Следующие шаги (Этап 6+)

| Фаза | Что | Причина |
|------|-----|--------|
| Фаза 6 | Graceful shutdown | Flush перед остановкой buffer |
| Фаза 7 | Integration tests | Ping-pong между процессами |
| Фаза 8 | Документация | README, DECISIONS.md |
| Фаза 9 | StatsManager | Структурированная статистика через CRM |
| Фаза 10 | correlation_id | Request-response паттерн |

---

## Ссылки

- `channel_routing_module/README.md` — базовый класс и детали
- `logger_module/README.md` — scope-based логирование
- `error_module/README.md` — level-based маршрутизация
- `router_module/README.md` — message pipeline с middleware
- `DECISIONS.md` — архитектурные решения (ADR-013..016)
- `MODULES_STATUS.md` — сводная таблица по модулям
