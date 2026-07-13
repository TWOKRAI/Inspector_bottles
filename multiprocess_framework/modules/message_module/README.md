# message_module

Универсальный транспортный протокол системы — единый **язык общения** между
всеми менеджерами и процессами фреймворка.

---

## Роль в архитектуре

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Любой Process/Manager                        │
│                                                                       │
│   msg = MessageAdapter(sender="my_proc")                             │
│   msg.command(targets=["other_proc"], command="start")               │
│         │                                                             │
│   router.send(msg)   ──→  msg.to_dict()  ──→  Queue / Channel        │
│                                                                       │
│   raw = queue.get()  ──→  Message.from_dict(raw)  ──→  msg объект    │
└─────────────────────────────────────────────────────────────────────┘
```

**Правило Dict at Boundary (ADR-008):**

| Действие | Формат |
|---|---|
| Передача через границу процессов | `msg.to_dict()` → `dict` |
| Восстановление после получения | `Message.from_dict(raw)` |
| Внутри процесса | Объект `Message` |

---

## Структура модуля

Ядро — **`Message(SchemaBase)`** (`data_schema_module`): все поля объявлены в одном классе с `FieldMeta`, сериализация через `model_dump()` / `to_dict()`, без отдельных конвертеров и валидаторов (план `plans/refactoring/08_message_schema_base.md`).

```
message_module/
├── interfaces.py          ← IMessage (Protocol), IMessageFactory (ABC)
├── __init__.py            ← Публичный API
│
├── core/
│   └── message.py         ← Message(SchemaBase) — создание, валидация, to_dict/from_dict
│
├── types/
│   ├── message_types.py   ← MessageType, Priority, LogLevel, MESSAGE_TYPE_*
│   └── exceptions.py      ← MessageValidationError
│
├── schemas/               ← Строгие схемы (extra='forbid'); BaseMessageSchema = алиас на Message
│   ├── command.py         ← CommandMessageSchema
│   └── log.py             ← LogMessageSchema
│
├── adapters/
│   └── message_adapter.py ← MessageAdapter (рекомендуемый способ создания)
│
├── factories/
│   └── message_factory.py ← create_message(), parse_message()
│
├── utils/
│   └── utils.py           ← generate_message_id()
│
└── tests/
    ├── test_message.py
    ├── test_schemas.py
    └── test_adapter.py
```

---

## Типы сообщений

| Тип | Константа | Обязательные поля | Назначение |
|---|---|---|---|
| `general` | `MessageType.GENERAL` | `content` | Произвольное сообщение |
| `command` | `MessageType.COMMAND` | `command` | Команда процессу/менеджеру |
| `log` | `MessageType.LOG` | `level`, `message` | Запись в лог |
| `system` | `MessageType.SYSTEM` | `action` | Управление жизненным циклом |
| `broadcast` | `MessageType.BROADCAST` | `content` | Рассылка всем процессам |
| `data` | `MessageType.DATA` | `data_type` | Передача больших данных |
| `request` | `MessageType.REQUEST` | `request_type` | Запрос с ожиданием ответа |
| `response` | `MessageType.RESPONSE` | `request_id` | Ответ на REQUEST |
| `event` | `MessageType.EVENT` | `event_type` | Событие pub/sub |

---

## Поля сообщения

### Базовые (у всех типов)

| Поле | Тип | Описание | Авто |
|---|---|---|---|
| `id` | `str` | Уникальный идентификатор | ✓ |
| `type` | `str` | Тип из MessageType | — |
| `sender` | `str` | Имя отправителя | — |
| `targets` | `List[str]` | Список получателей | — |
| `timestamp` | `float` | Unix-timestamp создания | ✓ |
| `priority` | `str` | `normal` | `low\|normal\|high\|urgent` |
| `channel` | `str\|None` | Канал доставки | ✓ по типу |
| `metadata` | `dict` | Произвольные метаданные | — |

### Специфичные по типу

| Поле | Тип | Для типа |
|---|---|---|
| `content` | `Any` | GENERAL |
| `command` | `str` | COMMAND |
| `args` | `dict` | COMMAND (legacy, см. ниже) |
| `need_ack` | `bool` | COMMAND |
| `level` | `str` | LOG |
| `message` | `str` | LOG |
| `module` | `str` | LOG |
| `action` | `str` | SYSTEM |
| `data` | `Any` | SYSTEM, DATA, **COMMAND** (payload команды, ADR-MSG-010) |
| `exclude` | `List[str]` | BROADCAST |
| `data_type` | `str` | DATA |
| `use_shared_memory` | `bool` | DATA |
| `memory_key` | `str` | DATA |
| `request_type` | `str` | REQUEST |
| `query` | `Any` | REQUEST |
| `timeout` | `float` | REQUEST |
| `request_id` | `str` | RESPONSE |
| `success` | `bool` | RESPONSE |
| `result` | `Any` | RESPONSE |
| `error` | `str` | RESPONSE |
| `event_type` | `str` | EVENT |
| `event_data` | `Any` | EVENT |

**Единый конверт команд (ADR-MSG-010, Ф7 G.2):** payload команды едет под ключ
`data` (+ `data_type` = имя команды) — единственная форма, которую строит билдер
`build_command_message`. Поле `args` сохранено как legacy: `Message` его объявляет,
но команды его больше не заполняют (`data` — единственный источник payload).

---

## API: MessageAdapter (рекомендуется)

`MessageAdapter` — основной способ создания сообщений в процессах и менеджерах.
Фиксирует `sender` один раз при создании.

```python
from message_module import MessageAdapter

class MyProcess:
    def __init__(self, name: str):
        self.msg = MessageAdapter(sender=name)

    def on_start(self):
        # Команда
        self.router.send(self.msg.command(
            targets=["orchestrator"],
            command="ready",
            args={"pid": os.getpid()},
        ))

    def on_event(self, data):
        # Событие
        self.router.send(self.msg.event("frame_ready", event_data=data))

    def on_error(self, err):
        # Лог
        self.router.send(self.msg.log("error", str(err)))

    def ask_status(self, target):
        # Запрос с correlation_id
        req = self.msg.request(targets=[target], request_type="get_status")
        self.router.send(req)
        return req.id   # сохранить для сопоставления ответа

    def reply(self, request_id, requester, result):
        # Ответ
        self.router.send(self.msg.response(
            targets=[requester],
            request_id=request_id,
            result=result,
        ))
```

### Методы MessageAdapter

| Метод | Аргументы | Создаёт тип |
|---|---|---|
| `create(msg_type, targets, **kw)` | любой тип | любой |
| `command(targets, command, args, data, need_ack, priority)` | payload → `data` (явный `data` приоритетнее `args`, ADR-MSG-010) | COMMAND |
| `log(level, message, module)` | — | LOG |
| `system(targets, action, data, priority)` | — | SYSTEM |
| `broadcast(content, exclude, priority)` | — | BROADCAST |
| `data(targets, data_type, data, use_shared_memory, memory_key)` | — | DATA |
| `request(targets, request_type, query, timeout)` | — | REQUEST |
| `response(targets, request_id, result, success, error)` | — | RESPONSE |
| `event(event_type, targets, event_data)` | — | EVENT |

---

## API: Message (класс объекта)

### Создание

```python
from message_module import Message, MessageType

# Через фабричный метод (без адаптера)
msg = Message.create(MessageType.COMMAND, sender="proc_1",
                     targets=["proc_2"], command="start")

# С Pydantic-валидацией
from message_module import CommandMessageSchema
msg = Message.create(MessageType.COMMAND, sender="proc_1",
                     targets=["proc_2"], command="start",
                     schema=CommandMessageSchema)

# Восстановление из dict (на принимающей стороне)
msg = Message.from_dict(raw_dict)
msg = Message.from_json(json_str)
```

### Fluent API

```python
msg = (
    Message.create(MessageType.GENERAL, sender="proc_1")
    .set_targets(["proc_2", "proc_3"])
    .set_priority("high")
    .set_channel("custom_channel")
    .set_content({"result": 42})
    .add_metadata("trace_id", "abc123")
)
```

### Сериализация (Dict at Boundary)

```python
# Перед отправкой через очередь между процессами
raw = msg.to_dict()          # только непустые поля
raw = msg.to_dict(exclude_none=False)  # все поля
json_str = msg.to_json(indent=2)

# После получения из очереди
msg = Message.from_dict(raw)
```

### Словарный доступ

```python
msg.get("command")           # None если нет
msg["command"]               # KeyError если нет
"command" in msg             # проверка
msg["priority"] = "high"     # установка (валидируется)
```

### Валидация

```python
try:
    msg.validate()   # raises MessageValidationError
except MessageValidationError as e:
    ...

if msg.is_valid():   # без исключения
    ...
```

---

## API: MessageFactory (низкоуровневый)

```python
from message_module import MessageFactory, create_message, parse_message

factory = MessageFactory()
msg = factory.create(MessageType.LOG, "proc_1", level="info", message="hello")

# Функции-алиасы
msg = create_message(MessageType.COMMAND, "proc_1", targets=["proc_2"], command="ping")
msg = parse_message(raw_dict_or_json_string)
```

---

## Иерархическая адресация в `targets` (P0.2 transport-router-hub)

Каждый элемент `Message.targets` — **dotted-адрес** получателя `process[.worker[.…]]`
(почтовый принцип: Страна → Город → … → Человек). Новые поля `kind`/`address` **не вводятся** —
иерархия живёт внутри существующего `targets: list[str]`.

```python
from multiprocess_framework.modules.message_module import (
    split_address, process_of, worker_of, normalize_targets,
)

split_address("camera.worker_in")   # → ["camera", "worker_in"]  (address[1:] — нижние уровни)
process_of("camera.worker_in")       # → "camera"   (address[0] — cross-process очередь)
worker_of("camera.worker_in")        # → "worker_in" (резолвится ВНУТРИ процесса, P2)
split_address("ProcessManager")      # → ["ProcessManager"]  (backward-compat: плоское имя)
```

Правила:
- **Prefix-правило:** первый сегмент всегда процесс и обязателен. Воркер без процесса
  (`".worker"`, висячие точки `"proc."`/`"a..b"`) → `AddressValidationError`.
- **Нижние уровни опциональны.** Плоское `"proc"` == `["proc"]` (как сегодня — `targets`
  ещё нигде не dotted).
- **`normalize_targets(target=, targets=)`** сводит сосуществующие скаляр `target` и список
  `targets` к единому `list[str]` (миграционный shim до P4).
- Спец-адреса `all`/`broadcast` (`is_broadcast`) — не иерархические, отдельный fan-out путь.

Транспортная семантика (доставка по `address[0]`, intra-process резолв воркера) реализуется
в P1/P2 плана; здесь — только парсинг/валидация (чистые JSON-safe функции, Dict-at-Boundary).

---

## Интеграция с router_module

```
MessageAdapter.command(...)
       │
       ▼  msg.to_dict()
  RouterManager.send(msg)
       │
       ├─→ _send_middleware → msg_dict
       │
       ├─→ channel_dispatcher → resolve channel
       │
       └─→ channel.send(msg_dict)   ← QueueChannel / SocketChannel / ...
```

На принимающей стороне:

```
channel.poll()
    │
    ▼  raw_dict
RouterManager.receive()
    │
    ├─→ _recv_middleware → msg_dict
    │
    ├─→ message_dispatcher.dispatch(msg_dict)   ← fire-and-forget handlers
    │
    └─→ Message.from_dict(msg_dict)   ← возвращается вызывающему
```

---

## Pydantic-схемы (опциональная строгая валидация)

Схемы используются когда нужна строгая типизация и запрет лишних полей.

```python
from message_module import Message, CommandMessageSchema, LogMessageSchema

# COMMAND — запрещает лишние поля (extra='forbid')
msg = Message.create(
    "command", sender="proc_1",
    targets=["proc_2"], command="start",
    schema=CommandMessageSchema,
)

# LOG — запрещает лишние поля, задаёт targets=['logger']
msg = Message.create(
    "log", sender="proc_1",
    level="error", message="Something went wrong",
    schema=LogMessageSchema,
)

# BaseMessageSchema — алиас на тот же класс Message (обратная совместимость импорта;
# расширяемые поля задаются через model_config Message: extra='allow')
from message_module import BaseMessageSchema

assert BaseMessageSchema is Message
```

### Создание своей схемы

```python
from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, Any, List

class MySchema(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=False)
    id: str
    type: str = "custom"
    sender: str
    targets: List[str]
    timestamp: float
    my_field: str         # обязательное поле

    def get_schema_info(self):
        return {
            'schema_name': self.__class__.__name__,
            'schema_module': self.__class__.__module__,
            'schema_path': f"{self.__class__.__module__}.{self.__class__.__name__}",
        }

msg = Message.create("custom", "proc_1", targets=["proc_2"],
                      my_field="value", schema=MySchema)
```

---

## Приоритеты

| Значение | Константа | Описание |
|---|---|---|
| `"urgent"` | `Priority.URGENT` | Максимальный (обработка немедленно) |
| `"high"` | `Priority.HIGH` | Высокий |
| `"normal"` | `Priority.NORMAL` | Обычный (по умолчанию) |
| `"low"` | `Priority.LOW` | Низкий (фоновые задачи) |

Приоритет используется `AsyncSender` в `RouterManager`
для сортировки в `PriorityQueue`.

---

## Идентификаторы (correlation_id)

Для паттерна REQUEST-RESPONSE используйте `msg.id` как `correlation_id`:

```python
# Отправитель
req = adapter.request(targets=["service"], request_type="get_data")
correlation_id = req.id
router.send(req)

# Получатель (handler)
def handle_request(msg):
    result = process(msg.get("query"))
    router.send(adapter.response(
        targets=[msg.sender],
        request_id=msg.id,   # correlation_id
        result=result,
    ))

# Отправитель (обработка ответа)
def handle_response(msg):
    if msg.get("request_id") == correlation_id:
        process_result(msg.get("result"))
```

---

## Публичный контракт (interfaces.py)

`IMessage` — **`Protocol`** (`@runtime_checkable`): структурная типизация, `isinstance(msg, IMessage)` работает для `Message`.

Внешние модули, которые принимают сообщения, должны type-hint через `IMessage`:

```python
from message_module.interfaces import IMessage

def process_incoming(msg: IMessage) -> None:
    sender = msg.sender
    data = msg.get("data")
    reply = msg.clone()
    ...
```

Для создания сообщений используйте `Message.create()` или `MessageAdapter(sender)`
(см. примеры выше). Отдельной фабрики-абстракции нет (`IMessageFactory` удалён —
0 реализаций; план comm-system §11.4).
