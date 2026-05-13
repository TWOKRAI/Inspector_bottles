# Plan 08: message_module — Message as SchemaBase

> **Статус:** ВЫПОЛНЕН (код + тесты + ADR-152; README и `00_overview` синхронизированы)  
> **Автор плана:** Claude (Opus 4.6), 2026-04-09  
> **Исполнитель:** Cursor Composer Agent v2  
> **Зависит от:** Plan 07 (завершён)  
> **Ссылки:** [07_message_module.md](../../plans/refactoring/07_message_module.md) · [00_overview.md](../../plans/refactoring/00_overview.md) · [ARCHITECTURE.md](../../multiprocess_framework/ARCHITECTURE.md)

---

## 0. Контекст и решение

### Проблемы после плана 07

1. **3 источника истины:** `VALID_MESSAGE_FIELDS`, `MESSAGE_FIELD_DEFAULTS`, `BaseMessageSchema` — дублируют список полей
2. **Баг мутабельных дефолтов:** shared `{}` / `[]` между экземплярами Message
3. **3 яруса в `__init__`:** 5 полей явно + 27 циклом + safety catch
4. **Double unpack в create(schema=):** dict → Pydantic → model_dump() → dict → init
5. **~310 LOC** инфраструктуры (MessageConverter + MessageValidator) которую Pydantic даёт из коробки

### Решение: Message наследует SchemaBase

Фреймворк в активном рефакторинге (планы 08-19). Все модули будут тронуты. Сейчас — лучший момент для фундаментальных изменений.

**Message = SchemaBase** даёт:
- `model_dump()` заменяет MessageConverter.to_dict()
- Pydantic валидация заменяет MessageValidator
- Поля = единственный источник истины
- FieldMeta аннотации для отладки
- `@model_validator` заменяет apply_type_defaults()
- `validate_assignment=False` — без overhead на setattr

**Публичный API сохраняется:** `Message.create()`, `to_dict()`, `from_dict()`, `MessageAdapter`, `msg.type`, `msg.sender`, `msg['command']`, `msg.get()` — всё обёрнуто поверх Pydantic.

### Что удаляется

| Убирается | LOC | Замена |
|-----------|-----|--------|
| `converters/message_converter.py` | 231 | `model_dump()` / `model_validate()` |
| `validators/message_validator.py` | 79 | Pydantic `@model_validator` |
| `MESSAGE_FIELD_DEFAULTS` dict | 30 | Поля Pydantic = дефолты |
| `VALID_MESSAGE_FIELDS` set | 10 | `Message.model_fields.keys()` |
| `apply_type_defaults()` в utils.py | 25 | `@model_validator(mode='after')` |
| `schemas/base.py` (отдельный класс) | 88 | Message IS the schema |
| **Итого** | **~463** | |

### Что сохраняется

- `Message.create(type, sender, schema=None, **kwargs)` — без изменений сигнатуры
- `msg.to_dict(exclude_none=True, ...)` — обёртка над model_dump()
- `Message.from_dict(data, schema=None)` — обёртка над model_validate()
- `MessageAdapter(sender=name)` — все методы (.command(), .log(), .event(), ...)
- `msg.type`, `msg.sender`, `msg.targets` — Pydantic поля = атрибуты
- `msg['command']`, `msg.get('x')`, `msg.keys()`, `msg.items()` — custom dunder-методы
- `msg.set_priority()`, `.set_targets()`, `.add_target()` — fluent setters
- `msg.validate()`, `msg.is_valid()` — обёртка над Pydantic
- `msg.clone()` — через model_dump + model_validate
- `msg.to_json()`, `msg.to_yaml()`, `msg.to_text()` — через model_dump
- `MessageType`, `Priority`, `LogLevel` enums
- `CommandMessageSchema`, `LogMessageSchema` — для strict валидации

---

## 1. Архитектура ПОСЛЕ

```
message_module/
├── core/
│   └── message.py              # Message(SchemaBase) — главный класс (~250 LOC)
├── adapters/
│   └── message_adapter.py      # Без изменений API
├── types/
│   ├── message_types.py        # Enums + MESSAGE_TYPE_DEFAULTS (без FIELD_DEFAULTS/VALID_FIELDS)
│   └── exceptions.py           # MessageValidationError
├── schemas/
│   ├── command.py              # CommandMessageSchema (для strict валидации)
│   └── log.py                  # LogMessageSchema (для strict валидации)
├── utils/
│   └── utils.py                # generate_message_id() (без apply_type_defaults)
├── interfaces.py               # IMessage как Protocol (не ABC)
├── factories/
│   └── message_factory.py      # create_message(), parse_message()
├── tests/
│   ├── test_message.py
│   ├── test_schemas.py
│   └── test_adapter.py
├── __init__.py
├── README.md
├── STATUS.md
└── DECISIONS.md
```

**Удалены:**
- `converters/message_converter.py` — заменён model_dump/model_validate
- `validators/message_validator.py` — заменён Pydantic валидацией
- `schemas/base.py` — Message IS the base schema

---

## 2. Атомарные шаги

### Шаг 1: Переписать `core/message.py` — Message наследует SchemaBase

**Файл:** `multiprocess_framework/modules/message_module/core/message.py`

**Полная замена** файла. Новый код:

```python
# -*- coding: utf-8 -*-
"""
Message — IPC value object на базе SchemaBase (Pydantic v2).

Единственный класс для создания, валидации и сериализации сообщений.
Публичный API: Message.create(), to_dict(), from_dict(), MessageAdapter.
"""

import json
import time
from typing import (
    Annotated, Any, Dict, List, Optional, Set, Type, Union, TYPE_CHECKING,
)

from pydantic import Field, ConfigDict, model_validator

from ...data_schema_module import SchemaBase, FieldMeta
from ..types import (
    MessageType,
    Priority,
    LogLevel,
    MessageValidationError,
    MESSAGE_TYPE_DEFAULTS,
    MESSAGE_TYPE_EXCLUDE_FIELDS,
)
from ..utils import generate_message_id

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

if TYPE_CHECKING:
    from pydantic import BaseModel


class Message(SchemaBase):
    """IPC value object: все поля через Pydantic, FieldMeta для документации."""

    model_config = ConfigDict(
        extra='allow',               # доп. поля для обратной совместимости
        validate_assignment=False,    # без overhead на setattr (fluent API)
        populate_by_name=True,
    )

    # === Core fields ===
    id: Annotated[str, FieldMeta("Уникальный ID сообщения")] = ""
    type: Annotated[str, FieldMeta("Тип сообщения (MessageType enum value)")] = "general"
    sender: Annotated[str, FieldMeta("Имя процесса-отправителя")] = ""
    targets: Annotated[List[str], FieldMeta("Список процессов-получателей")] = Field(
        default_factory=list
    )
    timestamp: Annotated[float, FieldMeta("Unix-timestamp создания")] = 0.0

    # === Routing ===
    priority: Annotated[str, FieldMeta("Приоритет: urgent|high|normal|low")] = "normal"
    routers: Annotated[List[str], FieldMeta("RouterManager'ы внутри процесса")] = Field(
        default_factory=lambda: ["internal"]
    )
    channel: Annotated[Optional[str], FieldMeta("Канал доставки в RouterManager")] = None
    metadata: Annotated[Dict[str, Any], FieldMeta("Произвольные метаданные")] = Field(
        default_factory=dict
    )

    # === GENERAL ===
    content: Annotated[Optional[Any], FieldMeta("Произвольное содержимое")] = None

    # === COMMAND ===
    command: Annotated[Optional[str], FieldMeta("Имя команды")] = None
    args: Annotated[Dict[str, Any], FieldMeta("Аргументы команды")] = Field(
        default_factory=dict
    )
    need_ack: Annotated[bool, FieldMeta("Требуется подтверждение")] = False

    # === LOG ===
    level: Annotated[Optional[str], FieldMeta("Уровень лога")] = None
    message: Annotated[Optional[str], FieldMeta("Текст лог-сообщения")] = None
    module: Annotated[str, FieldMeta("Имя модуля-источника лога")] = "main"

    # === SYSTEM ===
    action: Annotated[Optional[str], FieldMeta("Системное действие")] = None
    data: Annotated[Optional[Any], FieldMeta("Данные системного действия")] = None

    # === BROADCAST ===
    exclude: Annotated[List[str], FieldMeta("Процессы для исключения")] = Field(
        default_factory=list
    )

    # === DATA ===
    data_type: Annotated[Optional[str], FieldMeta("Тип передаваемых данных")] = None
    use_shared_memory: Annotated[bool, FieldMeta("Использовать shared memory")] = False
    memory_key: Annotated[Optional[str], FieldMeta("Ключ в shared memory")] = None

    # === REQUEST ===
    request_type: Annotated[Optional[str], FieldMeta("Тип запроса")] = None
    query: Annotated[Optional[Any], FieldMeta("Тело запроса")] = None
    timeout: Annotated[float, FieldMeta("Таймаут ответа, сек", min=0.1, max=300.0)] = 5.0

    # === RESPONSE ===
    request_id: Annotated[Optional[str], FieldMeta("ID запроса (correlation)")] = None
    success: Annotated[bool, FieldMeta("Успешность ответа")] = True
    result: Annotated[Optional[Any], FieldMeta("Результат запроса")] = None
    error: Annotated[Optional[str], FieldMeta("Текст ошибки")] = None

    # === EVENT ===
    event_type: Annotated[Optional[str], FieldMeta("Тип события")] = None
    event_data: Annotated[Optional[Any], FieldMeta("Данные события")] = None

    # === Private (not in model_fields) ===
    # _schema и _schema_info хранятся через model_config extra или __dict__
    # Используем PrivateAttr если нужно, или просто __dict__

    # -------------------------------------------------------------------------
    # Model validator: автозаполнение id, timestamp, type-specific defaults
    # -------------------------------------------------------------------------
    @model_validator(mode='after')
    def _auto_fill_and_type_defaults(self) -> 'Message':
        """Автозаполнение id, timestamp. Применение type-specific defaults."""
        # Нормализовать type
        if isinstance(self.type, MessageType):
            object.__setattr__(self, 'type', self.type.value)

        # Авто-генерация id
        if not self.id:
            object.__setattr__(self, 'id', generate_message_id(self.type))

        # Авто-timestamp
        if not self.timestamp:
            object.__setattr__(self, 'timestamp', time.time())

        # Type-specific defaults (channel, targets, routers)
        try:
            msg_type = MessageType(self.type)
            defaults = MESSAGE_TYPE_DEFAULTS.get(msg_type, {})
            if 'channel' in defaults and self.channel is None:
                object.__setattr__(self, 'channel', defaults['channel'])
            if 'targets' in defaults and not self.targets:
                object.__setattr__(self, 'targets', defaults['targets'])
            if 'routers' in defaults:
                object.__setattr__(self, 'routers', defaults['routers'])
        except ValueError:
            pass

        return self

    # -------------------------------------------------------------------------
    # Factory methods (публичный API)
    # -------------------------------------------------------------------------
    @classmethod
    def create(
        cls,
        type: Union[MessageType, str],
        sender: str,
        schema: Optional[Type['BaseModel']] = None,
        **kwargs
    ) -> 'Message':
        """Создать сообщение; при schema — Pydantic валидация через внешнюю схему."""
        if isinstance(type, MessageType):
            type = type.value

        if schema is not None:
            schema_data = {'type': type, 'sender': sender, **kwargs}
            if 'id' not in schema_data:
                schema_data['id'] = generate_message_id(type)
            try:
                validated = schema(**schema_data)
            except Exception as e:
                raise MessageValidationError(f"Schema validation failed: {e}") from e

            schema_info = (
                validated.get_schema_info()
                if hasattr(validated, 'get_schema_info')
                else {
                    'schema_name': schema.__name__,
                    'schema_module': schema.__module__,
                    'schema_path': f"{schema.__module__}.{schema.__name__}",
                }
            )
            instance = cls(**validated.model_dump())
            # Сохраняем schema info через __dict__ (не Pydantic поле)
            instance.__dict__['_msg_schema'] = schema
            instance.__dict__['_msg_schema_info'] = schema_info
            instance.__dict__['_msg_schema_validated'] = True
        else:
            instance = cls(type=type, sender=sender, **kwargs)
            instance.__dict__['_msg_schema'] = None
            instance.__dict__['_msg_schema_info'] = None
            instance.__dict__['_msg_schema_validated'] = False

        return instance

    # -------------------------------------------------------------------------
    # Fluent API (chainable setters)
    # -------------------------------------------------------------------------
    def set_priority(self, priority: Union[Priority, str]) -> 'Message':
        """Устанавливает приоритет."""
        self.priority = priority.value if isinstance(priority, Priority) else priority
        return self

    def set_targets(self, targets: List[str]) -> 'Message':
        """Устанавливает список получателей."""
        self.targets = targets
        return self

    def add_target(self, target: str) -> 'Message':
        """Добавляет получателя."""
        if target not in self.targets:
            self.targets.append(target)
        return self

    def set_channel(self, channel: str) -> 'Message':
        """Устанавливает канал доставки."""
        self.channel = channel
        return self

    def set_content(self, content: Any) -> 'Message':
        """Устанавливает содержимое (GENERAL)."""
        self.content = content
        return self

    def set_command(self, command: str, args: Dict[str, Any] = None) -> 'Message':
        """Устанавливает команду и аргументы (COMMAND)."""
        self.command = command
        if args:
            self.args = args
        return self

    def set_log(self, level: Union[LogLevel, str], message: str, module: str = None) -> 'Message':
        """Устанавливает параметры лога (LOG)."""
        self.level = level.value if isinstance(level, LogLevel) else level
        self.message = message
        if module:
            self.module = module
        return self

    def add_metadata(self, key: str, value: Any) -> 'Message':
        """Добавляет метаданные."""
        self.metadata[key] = value
        return self

    # -------------------------------------------------------------------------
    # Валидация
    # -------------------------------------------------------------------------
    def validate(self) -> bool:
        """Проверить сообщение. MessageValidationError при ошибке."""
        # Если использовалась внешняя схема — валидируем через неё
        ext_schema = self.__dict__.get('_msg_schema')
        if ext_schema is not None:
            try:
                data = self.to_dict(exclude_none=False)
                schema_fields = set(ext_schema.model_fields.keys())
                filtered = {k: v for k, v in data.items() if k in schema_fields}
                ext_schema(**filtered)
                return True
            except Exception as e:
                raise MessageValidationError(f"Schema validation failed: {e}") from e

        # Базовая валидация
        if not self.sender:
            raise MessageValidationError("Sender cannot be empty")
        if not self.targets:
            raise MessageValidationError("Targets cannot be empty")

        # Required fields по типу
        try:
            msg_type = MessageType(self.type)
            defaults = MESSAGE_TYPE_DEFAULTS.get(msg_type, {})
            for field_name in defaults.get('required_fields', []):
                value = getattr(self, field_name, None)
                if value is None or (isinstance(value, str) and not value):
                    raise MessageValidationError(
                        f"Required field '{field_name}' is empty for type '{self.type}'"
                    )
        except ValueError:
            raise MessageValidationError(f"Unknown message type: {self.type}")

        return True

    def is_valid(self) -> bool:
        """Как validate(), но без исключения — только bool."""
        try:
            self.validate()
            return True
        except MessageValidationError:
            return False

    # -------------------------------------------------------------------------
    # Сериализация (Dict at Boundary)
    # -------------------------------------------------------------------------
    def to_dict(
        self,
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """Конвертирует в dict (ADR-008 Dict at Boundary)."""
        data = self.model_dump()

        # Type-specific exclude
        try:
            msg_type = MessageType(self.type)
            type_exclude = MESSAGE_TYPE_EXCLUDE_FIELDS.get(msg_type, set())
            if exclude_fields:
                exclude_fields = exclude_fields | type_exclude
            else:
                exclude_fields = type_exclude
        except ValueError:
            pass

        if exclude_none:
            data = {k: v for k, v in data.items() if v is not None}

        # Исключаем пустые списки и словари
        data = {
            k: v for k, v in data.items()
            if not (isinstance(v, (list, dict)) and not v)
        }

        if exclude_fields:
            data = {k: v for k, v in data.items() if k not in exclude_fields}

        if include_fields:
            data = {k: v for k, v in data.items() if k in include_fields}

        return data

    def to_json(
        self,
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None,
        indent: Optional[int] = None,
    ) -> str:
        """Конвертирует в JSON."""
        data = self.to_dict(exclude_none, exclude_fields, include_fields)
        return json.dumps(data, indent=indent, ensure_ascii=False)

    def to_yaml(
        self,
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None,
    ) -> str:
        """Конвертирует в YAML."""
        if not YAML_AVAILABLE:
            raise ImportError("PyYAML not installed")
        data = self.to_dict(exclude_none, exclude_fields, include_fields)
        return yaml.dump(data, allow_unicode=True, default_flow_style=False)

    def to_text(
        self,
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None,
    ) -> str:
        """Конвертирует в текст."""
        data = self.to_dict(exclude_none, exclude_fields, include_fields)
        lines = []
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: Dict[str, Any], schema: Optional[Type['BaseModel']] = None) -> 'Message':
        """Собрать из dict; при schema — через внешнюю Pydantic схему."""
        if schema is not None:
            schema_fields = set(schema.model_fields.keys())
            filtered = {k: v for k, v in data.items() if k in schema_fields}
            validated = schema(**filtered)
            schema_info = (
                validated.get_schema_info()
                if hasattr(validated, 'get_schema_info')
                else {
                    'schema_name': schema.__name__,
                    'schema_module': schema.__module__,
                    'schema_path': f"{schema.__module__}.{schema.__name__}",
                }
            )
            instance = cls.model_validate(validated.model_dump())
            instance.__dict__['_msg_schema'] = schema
            instance.__dict__['_msg_schema_info'] = schema_info
            instance.__dict__['_msg_schema_validated'] = True
            return instance

        return cls.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str) -> 'Message':
        """Из JSON."""
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_yaml(cls, yaml_str: str) -> 'Message':
        """Из YAML."""
        if not YAML_AVAILABLE:
            raise ImportError("PyYAML not installed")
        return cls.from_dict(yaml.safe_load(yaml_str))

    # -------------------------------------------------------------------------
    # Enum helpers
    # -------------------------------------------------------------------------
    def get_type(self) -> Optional[MessageType]:
        """Тип как enum."""
        try:
            return MessageType(self.type)
        except ValueError:
            return None

    def get_priority(self) -> Priority:
        """Приоритет как enum."""
        try:
            return Priority(self.priority)
        except ValueError:
            return Priority.NORMAL

    # -------------------------------------------------------------------------
    # Clone
    # -------------------------------------------------------------------------
    def clone(self) -> 'Message':
        """Копия с новым ID и timestamp."""
        data = self.model_dump()
        data['id'] = generate_message_id(self.type)
        data['timestamp'] = time.time()
        cloned = Message.model_validate(data)
        # Копируем schema info
        if self.__dict__.get('_msg_schema_info'):
            cloned.__dict__['_msg_schema'] = self.__dict__.get('_msg_schema')
            cloned.__dict__['_msg_schema_info'] = self.__dict__['_msg_schema_info'].copy()
            cloned.__dict__['_msg_schema_validated'] = True
        return cloned

    # -------------------------------------------------------------------------
    # Dict-like interface (обратная совместимость)
    # -------------------------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        """msg['command']"""
        if key not in self.model_fields:
            raise KeyError(key)
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any):
        """msg['command'] = 'start'"""
        if key not in self.model_fields:
            raise KeyError(
                f"Field '{key}' is not a valid message field. "
                f"Valid fields: {sorted(self.model_fields.keys())}"
            )
        setattr(self, key, value)

    def __contains__(self, key: str) -> bool:
        """'command' in msg"""
        return key in self.model_fields

    def get(self, key: str, default: Any = None) -> Any:
        """dict.get()"""
        return getattr(self, key, default)

    def keys(self):
        """Ключи сообщения."""
        return list(self.model_fields.keys())

    def values(self):
        """Значения полей."""
        return [getattr(self, f) for f in self.model_fields]

    def items(self):
        """Пары (ключ, значение)."""
        return [(f, getattr(self, f)) for f in self.model_fields]

    # -------------------------------------------------------------------------
    # Schema info (обратная совместимость)
    # -------------------------------------------------------------------------
    def get_schema_info(self) -> Optional[Dict[str, str]]:
        """Метаданные внешней Pydantic-схемы или None."""
        return self.__dict__.get('_msg_schema_info')

    def get_schema(self) -> Optional[Type['BaseModel']]:
        """Класс внешней Pydantic-схемы или None."""
        return self.__dict__.get('_msg_schema')

    # -------------------------------------------------------------------------
    # Repr
    # -------------------------------------------------------------------------
    def __repr__(self) -> str:
        parts = [f"type={self.type!r}", f"id={self.id!r}",
                 f"sender={self.sender!r}", f"targets={self.targets!r}"]
        schema_info = self.__dict__.get('_msg_schema_info')
        if schema_info:
            parts.append(f"schema={schema_info['schema_name']}")
        return f"Message({', '.join(parts)})"

    def __str__(self) -> str:
        return self.to_text()
```

**Важные решения в коде:**

1. **`validate_assignment=False`** — без overhead на fluent setters. SchemaBase default — True, мы переопределяем.
2. **`extra='allow'`** — обратная совместимость (как было в BaseMessageSchema).
3. **`_msg_schema*` через `__dict__`** — не Pydantic поля, не попадают в model_dump().
4. **`object.__setattr__`** в model_validator — потому что в validator контексте Pydantic может перехватывать setattr.
5. **`id: str = ""`** и **`timestamp: float = 0.0`** — дефолты для Pydantic, model_validator заполняет реальными значениями.

### Шаг 2: Обновить `types/message_types.py`

**Файл:** `multiprocess_framework/modules/message_module/types/message_types.py`

**Удалить:**
- `VALID_MESSAGE_FIELDS` set (строки 92-102)
- `MESSAGE_FIELD_DEFAULTS` dict (строки 104-132)
- `Mapping` из import typing

**Оставить:**
- `MessageType`, `Priority`, `LogLevel` enums — без изменений
- `MESSAGE_TYPE_DEFAULTS` dict — без изменений (бизнес-логика роутинга)
- `MESSAGE_TYPE_EXCLUDE_FIELDS` dict — без изменений

### Шаг 3: Обновить `types/__init__.py`

**Файл:** `multiprocess_framework/modules/message_module/types/__init__.py`

Убрать `VALID_MESSAGE_FIELDS` и `MESSAGE_FIELD_DEFAULTS` из импорта и `__all__`. Добавить `MESSAGE_TYPE_EXCLUDE_FIELDS` если не экспортировался.

### Шаг 4: Удалить `converters/message_converter.py`

**Файл:** `multiprocess_framework/modules/message_module/converters/message_converter.py`

Удалить файл. Вся логика теперь в `Message.to_dict()` / `Message.from_dict()`.

Если есть `converters/__init__.py` — удалить тоже (или оставить пустым если другие файлы).

### Шаг 5: Удалить `validators/message_validator.py`

**Файл:** `multiprocess_framework/modules/message_module/validators/message_validator.py`

Удалить файл. Валидация в `Message.validate()`.

Если есть `validators/__init__.py` — удалить тоже.

### Шаг 6: Обновить `utils/utils.py`

**Файл:** `multiprocess_framework/modules/message_module/utils/utils.py`

Удалить `apply_type_defaults()` (заменена model_validator). Оставить `generate_message_id()`.

### Шаг 7: Удалить `schemas/base.py`

**Файл:** `multiprocess_framework/modules/message_module/schemas/base.py`

Удалить. Message IS the base schema. `BaseMessageSchema` больше не нужен как отдельный класс.

**Для обратной совместимости** — добавить alias в `schemas/__init__.py`:
```python
# schemas/__init__.py
from ..core.message import Message as BaseMessageSchema  # backward compat alias
from .command import CommandMessageSchema
from .log import LogMessageSchema
```

### Шаг 8: Обновить `schemas/command.py` и `schemas/log.py`

Эти схемы остаются **отдельными** (для strict валидации с `extra='forbid'`). Они НЕ наследуют Message — это валидационные схемы, не сообщения.

**Единственное изменение:** добавить FieldMeta аннотации к обязательным полям. Импорт из `data_schema_module` вместо голого `pydantic.BaseModel`.

**schemas/command.py:**
```python
from pydantic import Field, ConfigDict
from typing import Any, Dict, List, Optional
import time
from ...data_schema_module import SchemaBase, FieldMeta

class CommandMessageSchema(SchemaBase):
    model_config = ConfigDict(extra='forbid', validate_assignment=True)
    
    id: str
    type: str = "command"
    sender: str
    targets: List[str]
    timestamp: float = Field(default_factory=time.time)
    priority: str = "normal"
    routers: List[str] = Field(default_factory=lambda: ["internal"])
    channel: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    command: str  # Обязательное
    args: Dict[str, Any] = Field(default_factory=dict)
    need_ack: bool = False

    def get_schema_info(self) -> Dict[str, str]:
        return {
            'schema_name': self.__class__.__name__,
            'schema_module': self.__class__.__module__,
            'schema_path': f"{self.__class__.__module__}.{self.__class__.__name__}",
        }
```

**schemas/log.py:** аналогично, с `level: str` и `message: str` обязательными.

### Шаг 9: Обновить `interfaces.py` — IMessage как Protocol

**Файл:** `multiprocess_framework/modules/message_module/interfaces.py`

Заменить `ABC` / `abstractmethod` на `Protocol` (structural typing). Убрать `@property @abstractmethod` — Pydantic поля удовлетворяют Protocol через attribute access.

```python
from typing import Any, Dict, List, Optional, Set, Union, Protocol, runtime_checkable

@runtime_checkable
class IMessage(Protocol):
    """Контракт сообщения (structural typing)."""
    id: str
    type: str
    sender: str
    targets: List[str]
    timestamp: float
    priority: str
    channel: Optional[str]

    def set_priority(self, priority: Union[str, Any]) -> "IMessage": ...
    def set_targets(self, targets: List[str]) -> "IMessage": ...
    def add_target(self, target: str) -> "IMessage": ...
    def set_channel(self, channel: str) -> "IMessage": ...
    def add_metadata(self, key: str, value: Any) -> "IMessage": ...
    def validate(self) -> bool: ...
    def is_valid(self) -> bool: ...
    def to_dict(self, exclude_none: bool = True, ...) -> Dict[str, Any]: ...
    def to_json(self, exclude_none: bool = True, ...) -> str: ...
    def get(self, key: str, default: Any = None) -> Any: ...
    def clone(self) -> "IMessage": ...
    def get_schema_info(self) -> Optional[Dict[str, str]]: ...
```

IMessageFactory — оставить как ABC (фабрика не меняется).

### Шаг 10: Обновить `__init__.py`

**Файл:** `multiprocess_framework/modules/message_module/__init__.py`

Обновить импорты:
```python
from .core import Message
from .factories import create_message, parse_message
from .types import MessageType, Priority, LogLevel, MessageValidationError
from .schemas import BaseMessageSchema, CommandMessageSchema, LogMessageSchema  # BaseMessageSchema = alias
from .adapters import MessageAdapter
from .interfaces import IMessage, IMessageFactory
```

### Шаг 11: Обновить `factories/message_factory.py`

Проверить что `create_message()` и `parse_message()` работают с новым Message. Скорее всего изменения минимальны — они используют `Message.create()` и `Message.from_dict()`.

### Шаг 12: Обновить `adapters/message_adapter.py`

Проверить что `MessageAdapter` работает с новым Message. Внешний API не меняется. Внутренне — вызывает `Message.create()`, который работает.

### Шаг 13: Обновить тесты

**Файл:** `multiprocess_framework/modules/message_module/tests/test_message.py`

Основные изменения:
- Убрать тесты которые тестировали internal MessageConverter/MessageValidator напрямую
- Добавить тесты SchemaBase интеграции:

```python
class TestSchemaBaseIntegration:
    def test_message_is_schema_base(self):
        from ...data_schema_module import SchemaBase
        assert issubclass(Message, SchemaBase)

    def test_field_meta_available(self):
        meta = Message.get_field_meta("sender")
        assert meta is not None

    def test_model_dump_equals_to_dict_no_filter(self):
        msg = Message.create('general', 'a', targets=['b'], content='x')
        dump = msg.model_dump()
        assert 'type' in dump
        assert dump['sender'] == 'a'

    def test_no_shared_mutable_defaults(self):
        msg1 = Message.create('general', 'a', targets=['b'])
        msg2 = Message.create('general', 'c', targets=['d'])
        msg1.metadata['key'] = 'value'
        assert 'key' not in msg2.metadata

    def test_timeout_constraints(self):
        """SchemaBase проверяет min/max timeout."""
        meta = Message.get_field_meta("timeout")
        assert meta.min == 0.1
        assert meta.max == 300.0

    def test_model_validate_from_dict(self):
        data = {'type': 'command', 'sender': 'a', 'targets': ['b'], 'command': 'go'}
        msg = Message.model_validate(data)
        assert msg.command == 'go'

    def test_isinstance_check(self):
        from ..interfaces import IMessage
        msg = Message.create('general', 'a', targets=['b'])
        assert isinstance(msg, IMessage)
```

**Файл:** `test_schemas.py` — обновить для SchemaBase наследования.
**Файл:** `test_adapter.py` — скорее всего без изменений.

### Шаг 14: Полная валидация

```bash
# message_module
 && python -m pytest multiprocess_framework/modules/message_module/tests -v --cov

# Зависимые модули
python -m pytest multiprocess_framework/modules/router_module/tests -v
python -m pytest multiprocess_framework/modules/logger_module/tests -v

# Весь фреймворк
python scripts/run_framework_tests.py
python scripts/validate.py
```

### Шаг 15: Документация

#### ADR-152 в message_module/DECISIONS.md

```markdown
## ADR-152: Message наследует SchemaBase (Pydantic v2)

**Статус:** принято
**Дата:** 2026-04-09
**Контекст:** Message был plain class с ручным MessageConverter, MessageValidator, тремя dict'ами для полей. BaseMessageSchema дублировала определения полей.

**Решение:**
- Message наследует SchemaBase (data_schema_module).
- Все 32 поля определены как Pydantic fields с FieldMeta.
- model_dump() заменяет MessageConverter.to_dict().
- model_validate() заменяет MessageConverter.from_dict().
- @model_validator заменяет apply_type_defaults().
- validate_assignment=False для производительности fluent API.
- IMessage → Protocol (structural typing) вместо ABC.

**Удалено:**
- MessageConverter (231 LOC)
- MessageValidator (79 LOC)
- BaseMessageSchema (88 LOC) → Message IS the schema
- MESSAGE_FIELD_DEFAULTS, VALID_MESSAGE_FIELDS
- apply_type_defaults()

**Последствия:**
- Единственный источник истины: Message.model_fields
- FieldMeta для интроспекции
- Публичный API сохранён (create, to_dict, from_dict, MessageAdapter)
```

#### Обновить plans/refactoring/00_overview.md (метрики)
#### Обновить message_module/STATUS.md

### Шаг 16: Коммит

```bash
git add -A && git commit -m "refactor(message_module): Message inherits SchemaBase (Plan 08)

Major architectural change: Message is now a SchemaBase (Pydantic v2) subclass.

Changes:
- Message inherits SchemaBase with FieldMeta annotations for all 32 fields
- model_dump() replaces MessageConverter.to_dict()
- model_validate() replaces MessageConverter.from_dict()
- @model_validator replaces apply_type_defaults()
- validate_assignment=False for fluent API performance
- IMessage changed from ABC to Protocol (structural typing)

Removed:
- MessageConverter class (231 LOC)
- MessageValidator class (79 LOC)
- BaseMessageSchema (merged into Message)
- MESSAGE_FIELD_DEFAULTS, VALID_MESSAGE_FIELDS dicts
- apply_type_defaults() function

Fixed:
- Mutable defaults bug (shared {} between instances)

Public API preserved:
- Message.create(), to_dict(), from_dict()
- MessageAdapter (all methods)
- Dict-like interface (msg['command'], msg.get(), etc.)

ADR-152 documented.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## 3. Что НЕ менять

- `MessageAdapter` — внешний API без изменений
- `MessageType`, `Priority`, `LogLevel` enums — без изменений
- `MESSAGE_TYPE_DEFAULTS` — бизнес-логика роутинга
- `generate_message_id()` — утилита
- `create_message()`, `parse_message()` — фабричные функции (обёрнуты)
- Поведение `to_dict(exclude_none=True)` — фильтрация None, empty, type-exclude

## 4. Риски и митигации

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| SchemaBase._check_field_constraints на каждом Message | Средняя | Только timeout имеет min/max. Проверка одного числа — O(1). Если bottleneck — убрать min/max из FieldMeta timeout |
| model_validator порядок с SchemaBase validator | Средняя | Наш validator ПОСЛЕ SchemaBase._check_field_constraints. Порядок: base first, child second. Проверить тестами |
| Pydantic extra fields в model_dump() | Средняя | `extra='allow'` + model_dump() включает extra поля. Проверить что to_dict() фильтрует корректно |
| `_msg_schema*` через __dict__ | Низкая | Не попадают в model_dump(). Тест: model_dump() не содержит _msg_* ключей |
| Pickle safety dict form | Низкая | model_dump() возвращает plain dict — pickle-safe по определению |
| router_module / logger_module imports | Средняя | Они импортируют Message, MessageType — не меняются. Внутренние классы не импортируют |

## 5. Итоговая оценка

| Аспект | До (план 07) | После (план 08) |
|--------|-------------|-----------------|
| Источники истины | 3 | **1** (Message.model_fields) |
| __init__ ярусы | 3 | **0** (Pydantic native) |
| LOC message.py | 343 | **~250** |
| LOC module total | 1636 | **~1100** (-33%) |
| Удалённые файлы | 0 | **4** (converter, validator, base schema, apply_type_defaults) |
| Мутабельные дефолты | Баг | **Исправлен** (Field default_factory) |
| FieldMeta | Нет | **32 поля** аннотированы |
| Консистентность | BaseModel | **SchemaBase** (как data_schema_module) |
| Публичный API | — | **Сохранён** |
| Тесты | 103 | **100+** (некоторые internal тесты удалены, новые добавлены) |

## Верификация

```python
from multiprocess_framework.modules.message_module import Message, MessageType, MessageAdapter
from multiprocess_framework.modules.data_schema_module import SchemaBase

# 1. Message IS SchemaBase
assert issubclass(Message, SchemaBase)

# 2. FieldMeta работает
meta = Message.get_field_meta("timeout")
print(meta.description, meta.min, meta.max)

# 3. Мутабельные дефолты fix
msg1 = Message.create('general', 'a', targets=['b'])
msg2 = Message.create('general', 'c', targets=['d'])
msg1.metadata['x'] = 1
assert 'x' not in msg2.metadata

# 4. to_dict = pickle-safe dict
d = msg1.to_dict()
import pickle; pickle.dumps(d)  # OK

# 5. MessageAdapter работает
adapter = MessageAdapter(sender="test_proc")
msg = adapter.command(targets=["ctrl"], command="start")
assert msg.type == "command"
assert msg.sender == "test_proc"
```

## Критические файлы

| Файл | Действие |
|------|----------|
| `core/message.py` | **ПЕРЕПИСАТЬ** — Message(SchemaBase) |
| `types/message_types.py` | Удалить FIELD_DEFAULTS, VALID_FIELDS |
| `types/__init__.py` | Обновить экспорт |
| `converters/message_converter.py` | **УДАЛИТЬ** |
| `validators/message_validator.py` | **УДАЛИТЬ** |
| `utils/utils.py` | Удалить apply_type_defaults |
| `schemas/base.py` | **УДАЛИТЬ** (alias в __init__) |
| `schemas/command.py` | SchemaBase наследование |
| `schemas/log.py` | SchemaBase наследование |
| `schemas/__init__.py` | Обновить импорт BaseMessageSchema alias |
| `interfaces.py` | IMessage → Protocol |
| `__init__.py` | Обновить импорты |
| `factories/message_factory.py` | Проверить совместимость |
| `adapters/message_adapter.py` | Проверить совместимость |
| `tests/test_message.py` | Обновить + новые тесты |
| `tests/test_schemas.py` | Обновить для SchemaBase |
| `DECISIONS.md` | ADR-152 |
