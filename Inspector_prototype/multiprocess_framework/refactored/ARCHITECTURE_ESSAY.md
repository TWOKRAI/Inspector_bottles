# Multiprocess Framework — Архитектурное эссе

**Автор:** AI Assistant  
**Дата:** March 2026  
**Тема:** Почему эта архитектура работает и на что она опирается

---

## Введение: Проблема сложных многопроцессных приложений

Когда вы пишете приложение для обработки видео, IoT или компьютерного зрения, вы быстро понимаете, что `threading` недостаточно. Python GIL (Global Interpreter Lock) блокирует параллельное выполнение байт-кода, поэтому истинный параллелизм достигается только через `multiprocessing`.

Но `multiprocessing` в сыром виде — это боль:

```python
# Сырой multiprocessing — кошмар
def worker(queue_in, queue_out, logger_queue, error_queue, config_dict, ...):
    """30+ параметров, трудно отслеживать"""
    while True:
        try:
            msg = queue_in.get(timeout=1)
            result = process(msg)
            queue_out.put(result)
        except Exception as e:
            error_queue.put(str(e))  # как логировать?
            logger_queue.put(f"ERROR: {e}")  # есть ли структура?
        finally:
            # cleanup что?
```

Проблемы:
1. **Нет единого протокола** — каждый процесс использует свои очереди
2. **Нет структуры логирования** — логи идут в разные места, без контекста
3. **Нет управления жизненным циклом** — как gracefully остановить?
4. **Нет типизации** — что передавать в queue? dict? Pydantic? Pickle-able?
5. **Нет масштабируемости** — добавить процесс = дублировать код из других процессов

### Решение: Архитектурный фреймворк

**Multiprocess Framework** — это набор **15 модулей**, которые предоставляют:

✅ Единый протокол сообщений (Message, 9 типов)  
✅ Единую систему логирования (через ObservableMixin)  
✅ Управление жизненным циклом (graceful shutdown, signal handling)  
✅ Типизацию через Pydantic (SchemaBase, FieldMeta)  
✅ Масштабируемость (наследование, композиция, явные зависимости)

---

## Часть 1: Фундамент — BaseManager и ObservableMixin

### Почему нужен BaseManager?

В сложном приложении каждый компонент должен иметь:

1. **Жизненный цикл:** инициализация, работа, завершение
2. **Состояние:** инициализирован ли? работает ли?
3. **Адаптеры:** возможность подключить различные реализации

**BaseManager** — это ABC (Abstract Base Class), который гарантирует все это:

```python
class BaseManager(ABC):
    def initialize(self) -> bool: ...  # MUST implement
    def shutdown(self) -> bool: ...    # MUST implement
    
    # Управление адаптерами
    def attach_adapter(self, adapter, name=None) -> bool: ...
    def get_adapter(self, name) -> Optional[Any]: ...
    
    # События
    def on_event(self, event_type, callback): ...
    def emit_event(self, event_type, data): ...
```

**Результат:** Все 12 менеджеров (LoggerManager, RouterManager, CommandManager, ...) наследуют этот паттерн. Когда вы видите `manager.initialize()`, вы знаете, что это работает одинаково везде.

### Почему нужен ObservableMixin?

Логирование — это кросс-сечение (cross-cutting concern). Каждый менеджер должен логировать ошибки, но не должен знать КАК.

**ObservableMixin** решает это через **прокси-методы**:

```python
class MyManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None):
        ObservableMixin.__init__(self, managers={'logger': logger})
    
    def process(self):
        self._log_debug("Starting processing")      # ← автоматически
        try:
            result = do_work()
            self._log_info("Success")
            self._record_metric("ops.count", 1)     # ← автоматически
            return result
        except Exception as e:
            self._log_error("Failed")               # ← автоматически
            self._track_error(e, context=...)       # ← автоматически
            raise
```

**Магия:** `self._log_info()` на самом деле вызывает `logger_manager.info()`, но:
- Если логгера нет → методы ничего не делают (graceful fallback)
- Если нужно отключить логирование для всей системы → `manager.disable('logger')`
- Если нужно перенаправить логи в БД → просто передай другой logger_manager

Это **Dependency Injection** без явного прокидывания параметров везде.

---

## Часть 2: Коммуникация — Message и Dict at Boundary

### Почему нужно унифицировать сообщения?

Без единого протокола каждый процесс придумает свой:

```python
# Процесс A: отправляет tuple
queue.put((process_name, data, timestamp))

# Процесс B: ожидает dict
msg = queue.get()  # получает tuple! crash!

# Процесс C: использует Pydantic
class MyMsg(BaseModel): ...
queue.put(MyMsg(field=value))  # на Windows spawn не сериализуется!
```

**Message** — это типизированная обёртка с 9 типами:

```
GENERAL    — произвольные данные
COMMAND    — команда (с обработчиком в CommandManager)
LOG        — логирование (идёт в LoggerManager)
SYSTEM     — управление жизненным циклом
BROADCAST  — рассылка всем
DATA       — большие данные
REQUEST    — синхронный запрос
RESPONSE   — ответ на REQUEST
EVENT      — pub/sub событие
```

**Каждый тип имеет свой набор полей:**

```python
class Message:
    # Базовые (все типы)
    id: str
    type: str  # из MessageType
    sender: str
    targets: List[str]
    timestamp: float
    priority: str
    
    # Специфичные по типу
    if type == "command":
        command: str          # имя команды
        args: dict            # аргументы
        need_ack: bool
    
    elif type == "log":
        level: str            # DEBUG, INFO, ERROR, ...
        message: str
        module: str
    
    # и т.д.
```

### Почему Dict at Boundary?

Pydantic модели содержат методы, которые не сериализуются в pickle. На Windows (spawn mode) это ломается:

```python
# ❌ Неправильно (ломается на Windows)
msg = Message(type="command", ...)
queue.put(msg)  # ошибка pickle при распаковке в дочернем процессе

# ✅ Правильно (Dict at Boundary)
msg = Message(type="command", ...)
queue.put(msg.to_dict())  # → dict (pickle-safe)

# На другой стороне
raw_dict = queue.get()
msg = Message.from_dict(raw_dict)  # восстановлен объект
```

**Принцип:** На границе процессов передаются только примитивы (dict, list, str, int, bytes). Внутри процесса — типизированные объекты.

### Request-Response паттерн

Часто нужен синхронный запрос между процессами:

```python
# Процесс A (отправитель)
req = adapter.request(
    targets=["detector"],
    request_type="get_status",
    timeout=5.0
)
correlation_id = req.id
router.send(req)

# Ждём ответа в callback
def on_response(msg):
    if msg.get("request_id") == correlation_id:
        print(msg.get("result"))

# Процесс B (получатель)
def handle_request(msg):
    status = get_detector_status()
    reply = adapter.response(
        targets=[msg.sender],
        request_id=msg.id,  # ← correlation_id!
        result=status,
    )
    router.send(reply)
```

**Это просто:** correlation_id = message.id. Это надёжно, потому что каждое сообщение получает уникальный ID.

---

## Часть 3: Маршрутизация — ChannelRoutingManager

### Проблема: Three Similar Patterns

RouterManager, LoggerManager, ErrorManager первоначально реализовывались независимо:

```python
# RouterManager (v1)
class RouterManager:
    def __init__(self):
        self.channels = {}
    
    def register_channel(self, name, channel):
        self.channels[name] = channel
    
    def send(self, msg):
        for channel in self.channels.values():
            channel.write(msg)

# LoggerManager (v1)
class LoggerManager:
    def __init__(self):
        self.channels = {}
    
    def register_channel(self, name, channel):
        self.channels[name] = channel
    
    def log(self, level, message):
        for channel in self.channels.values():
            channel.write({"level": level, "message": message})

# ErrorManager (v1)
# ... копипаста того же кода
```

**Проблемы:**
- 3 копии одного кода = 3 источника ошибок
- Если найдём баг в registry, нужно исправить в 3 местах
- Добавить новый менеджер = копировать код снова

### Решение: ChannelRoutingManager

**ChannelRoutingManager** — базовый класс, который инкапсулирует паттерн:

```python
class ChannelRoutingManager(BaseManager, ObservableMixin):
    def __init__(self):
        self._channel_registry = ChannelRegistry()  # thread-safe
        self._dispatcher = Dispatcher()              # маршрутизация
        self._buffer = BufferStrategy()              # батчинг/async
    
    def register_channel(self, name, channel):
        self._channel_registry.register(name, channel)
    
    def send(self, key, data):
        # маршрутизация через dispatcher
        channels = self._dispatcher.dispatch(key)
        # буферизация через buffer
        for channel in channels:
            self._buffer.enqueue(channel, data)
```

**Результат:**

```python
# RouterManager (v2) — теперь просто наследует
class RouterManager(ChannelRoutingManager):
    def send(self, msg):
        channels = self._dispatcher.dispatch(msg["type"])
        for channel in channels:
            channel.write(msg)

# LoggerManager (v2) — теперь просто наследует
class LoggerManager(ChannelRoutingManager):
    def log(self, level, message):
        channels = self._dispatcher.dispatch(level)
        for channel in channels:
            channel.write({"level": level, "message": message})

# ErrorManager (v2) — теперь просто наследует
class ErrorManager(LoggerManager):  # даже не нужно переопределять!
    pass
```

**DRY (Don't Repeat Yourself) победил!** Один баг в ChannelRoutingManager исправляется для всех трёх.

---

## Часть 4: Типизация данных — SchemaBase и Dict at Boundary

### Проблема: Как описать структуру данных процесса?

Каждый процесс имеет состояние (velocity, fps, rotation, ...). Без описания структуры трудно:
- Проверить границы (fps не должна быть отрицательной)
- Синхронизировать между процессами
- Генерировать UI
- Сохранять конфиги

### Решение: SchemaBase (на основе Pydantic)

```python
from data_schema_module import SchemaBase, FieldMeta, FieldRouting
from typing import Annotated

class CameraConfig(SchemaBase):
    """Конфиг камеры с метаданными."""
    
    fps: Annotated[int, FieldMeta(
        "Частота кадров",
        info="FPS для захвата видео",
        min=1, max=120,
        unit="кадр/сек",
        routing=FieldRouting(channel="control_camera", priority=1),
    )] = 30
    
    resolution: Annotated[str, FieldMeta(
        "Разрешение",
        description="Разрешение видео",
        examples=["720p", "1080p"],
    )] = "720p"
    
    enabled: Annotated[bool, FieldMeta(
        "Включено",
    )] = True
```

**Магия:**
- `min=1, max=120` → автоматическая валидация при `update_field()`
- `unit="кадр/сек"` → UI может показать единицу
- `routing=...` → поле автоматически маршрутизируется по каналу
- `examples=...` → для UI

**Использование:**

```python
config = CameraConfig()
config.update_field("fps", 60)  # ✓ OK
config.update_field("fps", 200)  # ✗ Error: max=120

# Получить метаданные
meta = CameraConfig.get_field_meta("fps")
print(meta.description)  # "Частота кадров"
print(meta.unit)         # "кадр/сек"
```

### Где хранятся эти схемы?

**data_schema_module** — независимый модуль с нулевыми зависимостями:

```
Никаких импортов из:
  ✗ process_module
  ✗ router_module
  ✗ logger_module
  ✗ config_module

Только Pydantic v2!
```

**Результат:** Другие модули могут использовать SchemaBase без циклических зависимостей.

---

## Часть 5: Жизненный цикл — ProcessModule и Graceful Shutdown

### Проблема: Как управлять процессом?

Процесс должен:
1. Инициализироваться (создать ресурсы)
2. Работать (основной цикл)
3. Завершаться (освободить ресурсы, логировать статус)

И всё это при получении сигнала (SIGTERM, Ctrl+C, etc).

### Решение: ProcessModule + Signal Handler

```python
class ProcessModule(BaseManager, ObservableMixin):
    def initialize(self) -> bool:
        """Инициализация. Если вернуть False — процесс не запустится."""
        self.log_info("ProcessModule initializing")
        self._initialize_managers()  # router, logger, command, worker
        self.is_initialized = True
        return True
    
    def run(self):
        """Основной цикл. Проверяет should_stop()."""
        while not self.should_stop():
            # работа
            pass
    
    def shutdown(self) -> bool:
        """Завершение. Должен быть идемпотентным."""
        self.log_info("ProcessModule shutting down")
        self.worker_manager.stop_all()
        self.router_manager.shutdown()
        return True

# В дочернем процессе
try:
    if process.initialize():
        process.run()
finally:
    process.shutdown()
```

### Signal Handling

```python
# В ProcessSpawner
def _signal_handler(signum, frame):
    self.log_info(f"Received signal {signum}")
    orchestrator_stop_event.set()
    # ← НЕ sys.exit()! Просто устанавливаем флаг

# Каждый процесс проверяет should_stop()
def should_stop(self) -> bool:
    return self.stop_event.is_set()

# В ProcessManagerProcess
ProcessRegistry.stop_all(timeout=5):
    for process in processes:
        process.stop_event.set()
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()  # SIGTERM
            process.join(timeout=5)
        if process.is_alive():
            process.kill()  # SIGKILL
```

**Результат:** Graceful shutdown. Даже если процесс зависает, система закроется за 5-10 сек.

---

## Часть 6: Масштабируемость — Явные зависимости и OCP

### Принцип: Open/Closed Principle

> Класс должен быть открыт для расширения, но закрыт для модификации.

**Плохо:**
```python
class ProcessManager:
    def __init__(self):
        self.router_manager = RouterManager()
        self.logger_manager = LoggerManager()
        self.error_manager = ErrorManager()
        self.command_manager = CommandManager()
        # 20 more lines...
        # При добавлении нового менеджера нужно править этот класс!
```

**Хорошо:**
```python
class ProcessModule(BaseManager, ObservableMixin):
    def __init__(self, name, router_manager, logger_manager, ...):
        # ← все зависимости явно переданы
        self.router_manager = router_manager
        self.logger_manager = logger_manager
        # ...
        
        # Даже добавить новый менеджер просто:
        ObservableMixin.__init__(
            self,
            managers={
                'logger': logger_manager,
                'errors': error_manager,
                # добавить новый менеджер — одна строка!
                'stats': stats_manager,
            }
        )
```

### Почему явные зависимости?

1. **Видно, что от чего зависит** — не нужно искать глобальные переменные
2. **Легче тестировать** — подменить менеджер в тесте одна строка
3. **Легче расширять** — добавить новый менеджер = добавить параметр
4. **Нет скрытых багов** — если менеджер не передан, выбросится Exception, а не молчаливо свалится

---

## Часть 7: Надежность — Pickle-Safe и reinitialize_in_child()

### Проблема: Pickle в multiprocessing

При `spawn()` (используется на Windows):

```python
# Родитель
srm = SharedResourcesManager()
srm.queue = multiprocessing.Queue()
process = Process(target=worker, args=(srm,))
process.start()

# Pickle: srm → bytes → передать в дочерний процесс
# Распаковка: bytes → srm (в дочернем процессе)
# Но: multiprocessing.Queue использует внутренний socket!
#     Socket не может быть pickled как обычно
```

**Решение:** `multiprocessing.Queue` и `Event` **нативно pickle-safe**:

```python
# Это работает!
import multiprocessing
q = multiprocessing.Queue()
pickled = pickle.dumps(q)
restored_q = pickle.loads(pickled)
restored_q.put("hello")  # ✓ работает!
```

**Но объекты внутри SRM (EventManager, MemoryManager) могут быть не pickle-safe.**

### Решение: reinitialize_in_child()

```python
class SharedResourcesManager:
    def reinitialize_in_child(self):
        """Вызвать в дочернем процессе после unpickle."""
        self.event_manager.reinitialize()  # восстановить internal Queue
        self.memory_manager.reinitialize() # переоткрыть SharedMemory по имени
        # ... остальное
```

**Использование:**

```python
# В дочернем процессе (run_process_function)
def run_process_function(name, srm, config):
    srm.reinitialize_in_child()  # ← вызвать явно после unpickle
    
    # Теперь всё работает
    process_data = srm.get_process_data(name)
    queue = process_data.queues["system"]
    queue.get(timeout=1)  # ✓ работает
```

**Почему не автоматически в __setstate__?**

Потому что `__setstate__` вызывается в неопределённом контексте (может быть до инициализации логгера, конфига, etc). Явный вызов даёт контроль над порядком инициализации.

---

## Часть 8: Паттерны проектирования, используемые в фреймворке

### 1. Factory Pattern (в message_module)

```python
# MessageFactory создаёт сообщения разных типов
factory = MessageFactory()
cmd_msg = factory.create(MessageType.COMMAND, sender="proc", targets=[...])
log_msg = factory.create(MessageType.LOG, sender="proc", level="info", message="...")
```

### 2. Strategy Pattern (в dispatch_module)

```python
# 4 стратегии диспетчеризации
strategies = [
    ExactMatchStrategy(),      # O(1)
    FallbackMatchStrategy(),   # несколько обработчиков
    PatternMatchStrategy(),    # regex
    ChainMatchStrategy(),      # сценарии
]

# Диспетчер выбирает стратегию
dispatcher.dispatch(key, data, strategy=...)
```

### 3. Adapter Pattern (everywhere)

```python
# MessageAdapter — адаптер для удобного создания сообщений
adapter = MessageAdapter(sender="process_a")
msg = adapter.command(targets=[...], command="ping")

# RouterAdapter — адаптер для удобного отправления сообщений
router_adapter = RouterAdapter(router_manager)
router_adapter.send_command(targets=[...], command="ping")
```

### 4. Observer Pattern (в ObservableMixin)

```python
# ObservableMixin уведомляет менеджеров о событиях
manager.on_event("process_started", lambda data: log(data))
manager.emit_event("process_started", {"process_id": 42})
```

### 5. Template Method Pattern (в ProcessModule)

```python
class ProcessModule(ABC):
    def initialize(self) -> bool: ...        # MUST override
    def run(self): ...                        # MUST override
    def shutdown(self) -> bool: ...           # MUST override
    
    # Но есть helper методы
    def should_stop(self) -> bool:
        return self.stop_event.is_set()
```

### 6. Proxy Pattern (в ObservableMixin)

```python
# ObservableMixin создаёт прокси-методы
self._log_info("message")
# ↓ внутренно вызывает ↓
logger_manager.info("message")
```

### 7. Dependency Injection (везде)

```python
# Все зависимости передаются в конструктор
manager = MyManager(
    name="my_manager",
    logger=logger_manager,
    router=router_manager,
    error_handler=error_manager,
)
```

---

## Часть 9: Преимущества архитектуры

### ✅ 1. Модульность

Каждый модуль независим. Если один сломается, остальные продолжают работать.

```
Хорошо:    base_manager → {logger, router, config, ...}
           (звезда: все зависят от base, но не друг от друга)

Плохо:     logger → router → command → ... → config
           (цепочка: если router сломается, всё затронуто)
```

### ✅ 2. Type Safety

Все данные описаны типами (Pydantic, Protocol). IDE подскажет ошибку.

```python
msg: IMessage = router.receive()  # type hint
msg.sender  # IDE подскажет: sender: str
msg.invalid_field  # IDE ошибка: no attribute
```

### ✅ 3. Testability

Каждый модуль можно тестировать изолировано. Менеджеры подменяются в тестах.

```python
# Тест
mock_logger = MagicMock()
manager = MyManager(logger=mock_logger)
manager.do_work()
mock_logger.info.assert_called_once()
```

### ✅ 4. Observability

Все операции залогированы через ObservableMixin.

```python
self._log_debug("resolving channels")
self._record_metric("messages.sent", 1)
self._track_error(exc, context={"method": "send"})
```

### ✅ 5. Graceful Degradation

Если менеджер отсутствует, методы вернут None вместо crash.

```python
# Если нет логгера
ObservableMixin.__init__(self, managers={})  # logger absent
self._log_info("message")  # не упадёт, просто ничего не сделает
```

### ✅ 6. Scalability

Добавить новый процесс = наследовать ProcessModule и переопределить 3 метода.

```python
class MyNewProcess(ProcessModule):
    def initialize(self) -> bool: ...
    def run(self): ...
    def shutdown(self) -> bool: ...
```

---

## Часть 10: Когда использовать этот фреймворк

### ✅ Идеальные случаи

1. **Обработка видео/компьютерное зрение**
   - Несколько процессов: камера, детектор, трекер, UI
   - Нужна синхронизация между процессами
   - Нужна структурированная обработка ошибок

2. **IoT приложения**
   - Несколько процессов: сенсоры, обработка, отправка
   - Нужно управлять конфигурацией
   - Нужна надёжность (graceful shutdown)

3. **Микросервисы на одной машине**
   - Вместо Docker + Kubernetes
   - Вместо RabbitMQ + Redis
   - Для прототипирования или небольших систем

4. **Системы мониторинга**
   - Несколько источников данных
   - Централизованное логирование
   - Контролируемое завершение

### ❌ Когда НЕ использовать

1. **Простые скрипты**
   - Нужна просто `multiprocessing` + стандартный `logging`
   - Фреймворк — overkill

2. **Распределённые системы**
   - Для них используй Docker + Kubernetes
   - Для них используй gRPC / HTTP API
   - Фреймворк работает на одной машине

3. **Когда нужна асинхронность (async/await)**
   - Фреймворк использует multiprocessing (не asyncio)
   - Для async используй asyncio напрямую

4. **Простое скрипт-обёртка**
   - Нужно просто запустить несколько команд
   - Используй subprocess + threading

---

## Заключение: Фундаментальные принципы

Эта архитектура держится на **трёх китах**:

### 1. Explicit is Better Than Implicit (Дзен Питона)

```python
# Плохо (скрытая логика)
self.log_info("message")  # где логирует? в файл? консоль? БД?

# Хорошо (явно)
ObservableMixin.__init__(self, managers={'logger': logger_manager})
self._log_info("message")  # ясно, что логирует в logger_manager
```

### 2. Separation of Concerns (SRP)

```
Каждый модуль отвечает за одно:
  base_manager      → жизненный цикл
  data_schema       → типизация данных
  message_module    → протокол сообщений
  router_module     → маршрутизация
  logger_module     → логирование
  error_module      → обработка ошибок
  ... и т.д.
```

### 3. Graceful Everything

```
Graceful initialization:  если что-то не инициализировалось,
                         последующие модули знают об этом

Graceful shutdown:       даже если процесс зависает,
                         система закроется за 5-10 сек

Graceful degradation:    если менеджер отсутствует,
                         методы вернут None вместо crash

Graceful error handling: все ошибки логируются и отслеживаются
```

---

**Эта архитектура результат опыта разработки реальных систем обработки видео. Она работает, потому что основана на простых, проверенных принципах — модульности, явности, надёжности.**

