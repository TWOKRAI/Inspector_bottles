# Message Module - Транспорт

## Описание

Message Module - это универсальный транспорт для всех сообщений в системе. Это основа коммуникации, которая используется Router Manager для маршрутизации сообщений между компонентами.

## Структура модуля

Модуль следует стандарту структуры (см. MODULE_STRUCTURE.md):

```
message/
├── __init__.py              # Публичный API модуля
├── interfaces.py            # Интерфейсы модуля (если нужны)
├── core/                    # Основные классы
│   ├── __init__.py
│   └── message.py           # Класс Message (публичные и внутренние методы разделены)
├── schemas/                 # Схемы валидации (Pydantic v2) ⭐ НОВОЕ
│   ├── __init__.py
│   ├── base.py              # BaseMessageSchema
│   ├── command.py           # CommandMessageSchema
│   └── log.py               # LogMessageSchema
├── validators/              # Валидаторы (внутренние)
│   ├── __init__.py
│   └── message_validator.py # MessageValidator
├── converters/             # Конвертеры (внутренние)
│   ├── __init__.py
│   └── message_converter.py # MessageConverter
├── factories/               # Фабрики (публичные)
│   ├── __init__.py
│   └── message_factory.py  # MessageFactory, create_message, parse_message
├── types/                   # Типы, константы, исключения
│   ├── __init__.py
│   ├── message_types.py    # MessageType, Priority, LogLevel, MessageSchema
│   └── exceptions.py       # MessageValidationError
├── utils.py                 # Утилиты (generate_message_id, apply_type_defaults)
├── README.md
└── tests/
    ├── test_message.py
    └── test_schemas.py      # Тесты схем ⭐ НОВОЕ
```

## Роль в архитектуре

Message Module является **транспортом** (аналогия с кровью/сигналами в организме):
- Все компоненты используют Message для коммуникации
- Router Manager использует Message для маршрутизации
- Поддерживает все типы сообщений через единый интерфейс
- **Система схем (Pydantic v2)** для валидации и производительности ⭐

## Система схем (Pydantic v2) ⭐

### Что такое схемы?

Схемы - это классы Pydantic v2 для валидации сообщений. Они позволяют:
- ✅ Определять разные схемы для разных типов сообщений
- ✅ Убирать ненужные поля из базовой схемы
- ✅ Автоматическую валидацию через Pydantic
- ✅ Высокую производительность (кеширование валидации)
- ✅ Хранение информации о схеме в сообщении (путь, название, ссылка)

### Использование схем

#### Со схемой (рекомендуется для новых проектов)

```python
from multiprocess_framework.refactored.modules.message import (
    Message, MessageType, CommandMessageSchema
)

# Создание с валидацией через схему
msg = Message.create(
    MessageType.COMMAND,
    sender="ProcessA",
    schema=CommandMessageSchema,  # ← Схема для валидации
    targets=["ProcessB"],
    command="process_data",
    args={"param": "value"}
)

# Информация о схеме хранится в сообщении
print(msg.get_schema_info())
# {'schema_name': 'CommandMessageSchema', 'schema_module': '...', 'schema_path': '...'}

print(msg.get_schema())
# <class 'multiprocess_framework.refactored.modules.message.schemas.command.CommandMessageSchema'>
```

#### Без схемы (обратная совместимость)

```python
# Старый код работает как раньше
msg = Message.create(
    MessageType.COMMAND,
    sender="ProcessA",
    targets=["ProcessB"],
    command="process_data"
)
```

### Доступные схемы

- `BaseMessageSchema` - базовая схема со всеми полями
- `CommandMessageSchema` - схема для COMMAND сообщений
- `LogMessageSchema` - схема для LOG сообщений

### Создание кастомной схемы

```python
from pydantic import BaseModel, Field
from typing import List, Optional
import time

class VisionMessageSchema(BaseModel):
    """Кастомная схема для VisionProcess."""
    
    # Обязательные поля
    id: str
    type: str = "data"
    sender: str
    targets: List[str]
    timestamp: float = Field(default_factory=time.time)
    
    # Специфичные поля
    image_data: bytes
    bbox: List[float]
    confidence: float
    model_version: Optional[str] = None
    
    class Config:
        extra = "forbid"  # Запрещаем дополнительные поля

# Использование
msg = Message.create(
    MessageType.DATA,
    sender="VisionProcess",
    schema=VisionMessageSchema,
    targets=["AIProcess"],
    image_data=image_bytes,
    bbox=[10, 20, 100, 200],
    confidence=0.95
)
```

### Производительность

- ✅ Валидация кешируется при создании сообщения
- ✅ Повторная валидация пропускается если уже валидировано через схему
- ✅ Pydantic v2 обеспечивает высокую скорость валидации

## Публичный API

### Импорт

```python
from multiprocess_framework.refactored.modules.message import (
    Message,
    MessageType,
    Priority,
    LogLevel,
    create_message,
    parse_message
)
```

### Message

Универсальный класс для всех типов сообщений:

```python
# Создание сообщения
msg = Message.create(
    type=MessageType.COMMAND,
    sender="ProcessA",
    targets=["ProcessB"],
    command="process_data",
    args={"data_id": 123}
)

# Fluent API
msg.set_priority(Priority.HIGH)
msg.add_metadata("user_id", "12345")

# Конвертация
data = msg.to_dict()
json_str = msg.to_json()
```

### Фабрика сообщений

```python
from multiprocess_framework.refactored.modules.message import create_message, parse_message

# Создание через функцию
msg = create_message(MessageType.COMMAND, sender="ProcessA", ...)

# Парсинг из различных форматов
msg = parse_message(json_str)  # Автоматически определяет формат
```

### MessageType

Типы сообщений:
- `GENERAL` - обычное сообщение
- `COMMAND` - команда для выполнения
- `LOG` - лог-сообщение
- `SYSTEM` - системное сообщение
- `BROADCAST` - широковещательное сообщение
- `DATA` - сообщение с данными
- `REQUEST` - запрос
- `RESPONSE` - ответ
- `EVENT` - событие

### Priority

Приоритеты сообщений:
- `LOW` - низкий
- `NORMAL` - обычный
- `HIGH` - высокий
- `URGENT` - срочный

## Использование

### Создание сообщений

```python
# Через фабричный метод
msg = Message.create(
    type=MessageType.COMMAND,
    sender="GUI",
    targets=["Worker"],
    command="process"
)

# Из словаря
msg = Message.from_dict({
    "type": "command",
    "sender": "GUI",
    "targets": ["Worker"],
    "command": "process"
})

# Из JSON
msg = Message.from_json(json_str)
```

### Fluent API

```python
msg = Message.create(MessageType.LOG, sender="ProcessA")
msg.set_log(LogLevel.INFO, "Message text", module="worker")
msg.set_priority(Priority.HIGH)
msg.add_metadata("key", "value")
```

### Валидация

```python
# Валидация с исключением
try:
    msg.validate()
except MessageValidationError as e:
    print(f"Invalid message: {e}")

# Проверка без исключения
if msg.is_valid():
    router.send(msg)
```

## Интеграция с Router

Message используется Router Manager для маршрутизации:

```python
# Router автоматически определяет канал по типу сообщения
msg = Message.create(MessageType.LOG, sender="ProcessA", ...)
router.send(msg)  # Автоматически выберет LoggerChannel

# Явное указание канала
msg.channel = "process_queue"
router.send(msg)  # Отправит в QueueChannel
```

## Публичный API

### Message.create()

Фабричный метод для создания сообщений.

### Message.to_dict()

Конвертация в словарь.

### Message.to_json()

Конвертация в JSON.

### Message.from_dict()

Создание из словаря.

### Message.from_json()

Создание из JSON.

### Message.validate()

Валидация сообщения.

## Структура компонентов

### Публичные компоненты (экспортируются из __init__.py)

- **Message** (`core/message.py`) - основной класс сообщений
  - Публичные методы: `create()`, `validate()`, `to_dict()`, `to_json()`, и т.д.
  - Внутренние методы: `_sync_to_dict()` (с префиксом `_`)
- **MessageFactory** (`factories/message_factory.py`) - фабрика для создания сообщений
- **create_message()** - функция для создания сообщений
- **parse_message()** - функция для парсинга сообщений
- **MessageType, Priority, LogLevel** (`types/`) - типы и перечисления
- **MessageValidationError** (`types/exceptions.py`) - исключения

### Внутренние компоненты (не экспортируются)

- **MessageValidator** (`validators/message_validator.py`) - валидация сообщений
- **MessageConverter** (`converters/message_converter.py`) - конвертация сообщений
- **utils.py** - утилиты (generate_message_id, apply_type_defaults)

## Принципы использования

1. **Используйте только публичный API** - импортируйте из `__init__.py`
2. **Не используйте внутренние классы напрямую** - они могут измениться
3. **Используйте типы из types/** - они стабильны и документированы
4. **Публичные методы** - без префикса `_`
5. **Внутренние методы** - с префиксом `_` (не используйте извне)

## Тесты

Тесты находятся в `tests/` директории модуля и тестируют только публичный API.

