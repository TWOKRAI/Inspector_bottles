# -*- coding: utf-8 -*-
"""
Message — IPC value object на базе SchemaBase (Pydantic v2).

Единственный класс для создания, валидации и сериализации сообщений.
Публичный API: Message.create(), to_dict(), from_dict(), MessageAdapter.
"""

import json
import time
from typing import (
    Annotated,
    Any,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    Union,
    TYPE_CHECKING,
)

from pydantic import ConfigDict, Field, model_validator

from ...data_schema_module import FieldMeta, SchemaBase
from ..types import (
    MESSAGE_TYPE_DEFAULTS,
    MESSAGE_TYPE_EXCLUDE_FIELDS,
    LogLevel,
    MessageType,
    MessageValidationError,
    Priority,
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
        extra="allow",
        validate_assignment=False,
        populate_by_name=True,
    )

    # === Core fields ===
    id: Annotated[str, FieldMeta("Уникальный ID сообщения")] = ""
    type: Annotated[str, FieldMeta("Тип сообщения (MessageType enum value)")] = "general"
    sender: Annotated[str, FieldMeta("Имя процесса-отправителя")] = ""
    targets: Annotated[List[str], FieldMeta("Список процессов-получателей")] = Field(default_factory=list)
    timestamp: Annotated[float, FieldMeta("Unix-timestamp создания")] = 0.0

    # === Routing ===
    priority: Annotated[str, FieldMeta("Приоритет: urgent|high|normal|low")] = "normal"
    channel: Annotated[Optional[str], FieldMeta("Канал доставки в RouterManager")] = None
    metadata: Annotated[Dict[str, Any], FieldMeta("Произвольные метаданные")] = Field(default_factory=dict)

    # === GENERAL ===
    content: Annotated[Optional[Any], FieldMeta("Произвольное содержимое")] = None

    # === COMMAND ===
    command: Annotated[Optional[str], FieldMeta("Имя команды")] = None
    # legacy: единый конверт команд (Ф7 G.2) кладёт payload под `data`, НЕ под
    # `args`. Поле сохранено для обратной совместимости (G0/G4-дисциплина —
    # не удаляем), но исходящими командами не заполняется.
    args: Annotated[Dict[str, Any], FieldMeta("Аргументы команды (legacy; payload → data)")] = Field(
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
    exclude: Annotated[List[str], FieldMeta("Процессы для исключения")] = Field(default_factory=list)

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

    @model_validator(mode="after")
    def _auto_fill_and_type_defaults(self) -> "Message":
        """Автозаполнение id, timestamp. Применение type-specific defaults."""
        if isinstance(self.type, MessageType):
            object.__setattr__(self, "type", self.type.value)

        if not self.id:
            object.__setattr__(self, "id", generate_message_id(self.type))

        if not self.timestamp:
            object.__setattr__(self, "timestamp", time.time())

        try:
            msg_type = MessageType(self.type)
            defaults = MESSAGE_TYPE_DEFAULTS.get(msg_type, {})
            if "channel" in defaults and self.channel is None:
                object.__setattr__(self, "channel", defaults["channel"])
            if "targets" in defaults and not self.targets:
                object.__setattr__(self, "targets", defaults["targets"])
        except ValueError:
            pass

        return self

    @classmethod
    def create(
        cls,
        type: Union[MessageType, str],
        sender: str,
        schema: Optional[Type["BaseModel"]] = None,
        **kwargs: Any,
    ) -> "Message":
        """Создать сообщение; при schema — Pydantic валидация через внешнюю схему."""
        if isinstance(type, MessageType):
            type = type.value

        if schema is not None:
            schema_data = {"type": type, "sender": sender, **kwargs}
            if "id" not in schema_data:
                schema_data["id"] = generate_message_id(type)
            try:
                validated = schema(**schema_data)
            except Exception as e:
                raise MessageValidationError(f"Schema validation failed: {e}") from e

            schema_info = (
                validated.get_schema_info()
                if hasattr(validated, "get_schema_info")
                else {
                    "schema_name": schema.__name__,
                    "schema_module": schema.__module__,
                    "schema_path": f"{schema.__module__}.{schema.__name__}",
                }
            )
            instance = cls(**validated.model_dump())
            instance.__dict__["_msg_schema"] = schema
            instance.__dict__["_msg_schema_info"] = schema_info
            instance.__dict__["_msg_schema_validated"] = True
        else:
            instance = cls(type=type, sender=sender, **kwargs)
            instance.__dict__["_msg_schema"] = None
            instance.__dict__["_msg_schema_info"] = None
            instance.__dict__["_msg_schema_validated"] = False

        return instance

    def set_priority(self, priority: Union[Priority, str]) -> "Message":
        """Устанавливает приоритет."""
        self.priority = priority.value if isinstance(priority, Priority) else priority
        return self

    def set_targets(self, targets: List[str]) -> "Message":
        """Устанавливает список получателей."""
        self.targets = targets
        return self

    def add_target(self, target: str) -> "Message":
        """Добавляет получателя."""
        if target not in self.targets:
            self.targets.append(target)
        return self

    def set_channel(self, channel: str) -> "Message":
        """Устанавливает канал доставки."""
        self.channel = channel
        return self

    def set_content(self, content: Any) -> "Message":
        """Устанавливает содержимое (GENERAL)."""
        self.content = content
        return self

    def set_command(self, command: str, args: Optional[Dict[str, Any]] = None) -> "Message":
        """Устанавливает команду; payload кладётся под ``data`` (единый конверт, Ф7 G.2).

        .. deprecated::
            Собирай COMMAND через ``MessageAdapter.command`` /
            ``command_envelopes.build_command_message`` — единый билдер конверта.
            Метод оставлен для совместимости и приведён к data-конверту (payload
            под ``data``, НЕ под legacy ``args``).
        """
        import warnings

        warnings.warn(
            "Message.set_command устарел: используй MessageAdapter.command / "
            "build_command_message (единый конверт, payload под data)",
            DeprecationWarning,
            stacklevel=2,
        )
        self.command = command
        self.data_type = command
        if args:
            self.data = args
        return self

    def set_log(
        self,
        level: Union[LogLevel, str],
        message: str,
        module: Optional[str] = None,
    ) -> "Message":
        """Устанавливает параметры лога (LOG)."""
        self.level = level.value if isinstance(level, LogLevel) else level
        self.message = message
        if module:
            self.module = module
        return self

    def add_metadata(self, key: str, value: Any) -> "Message":
        """Добавляет метаданные."""
        self.metadata[key] = value
        return self

    def validate(self) -> bool:
        """Проверить сообщение. MessageValidationError при ошибке."""
        ext_schema = self.__dict__.get("_msg_schema")
        if ext_schema is not None:
            try:
                data = self.to_dict(exclude_none=False)
                schema_fields = set(ext_schema.model_fields.keys())
                filtered = {k: v for k, v in data.items() if k in schema_fields}
                ext_schema(**filtered)
                return True
            except Exception as e:
                raise MessageValidationError(f"Schema validation failed: {e}") from e

        if not self.sender:
            raise MessageValidationError("Sender cannot be empty")
        if not self.targets:
            raise MessageValidationError("Targets cannot be empty")

        try:
            msg_type = MessageType(self.type)
            defaults = MESSAGE_TYPE_DEFAULTS.get(msg_type, {})
            for field_name in defaults.get("required_fields", []):
                value = getattr(self, field_name, None)
                if value is None or (isinstance(value, str) and not value):
                    raise MessageValidationError(f"Required field '{field_name}' is empty for type '{self.type}'")
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

    def to_dict(
        self,
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """Конвертирует в dict (ADR-008 Dict at Boundary)."""
        data = self.model_dump()

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

        data = {k: v for k, v in data.items() if not (isinstance(v, (list, dict)) and not v)}

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
    def from_dict(
        cls,
        data: Dict[str, Any],
        schema: Optional[Type["BaseModel"]] = None,
    ) -> "Message":
        """Собрать из dict; при schema — через внешнюю Pydantic схему."""
        if schema is not None:
            schema_fields = set(schema.model_fields.keys())
            filtered = {k: v for k, v in data.items() if k in schema_fields}
            validated = schema(**filtered)
            schema_info = (
                validated.get_schema_info()
                if hasattr(validated, "get_schema_info")
                else {
                    "schema_name": schema.__name__,
                    "schema_module": schema.__module__,
                    "schema_path": f"{schema.__module__}.{schema.__name__}",
                }
            )
            instance = cls.model_validate(validated.model_dump())
            instance.__dict__["_msg_schema"] = schema
            instance.__dict__["_msg_schema_info"] = schema_info
            instance.__dict__["_msg_schema_validated"] = True
            return instance

        return cls.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str) -> "Message":
        """Из JSON."""
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "Message":
        """Из YAML."""
        if not YAML_AVAILABLE:
            raise ImportError("PyYAML not installed")
        return cls.from_dict(yaml.safe_load(yaml_str))

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

    def clone(self) -> "Message":
        """Копия с новым ID и timestamp."""
        data = self.model_dump()
        data["id"] = generate_message_id(self.type)
        data["timestamp"] = time.time()
        cloned = Message.model_validate(data)
        if self.__dict__.get("_msg_schema") is not None:
            cloned.__dict__["_msg_schema"] = self.__dict__.get("_msg_schema")
            info = self.__dict__.get("_msg_schema_info")
            if isinstance(info, dict):
                cloned.__dict__["_msg_schema_info"] = info.copy()
            else:
                cloned.__dict__["_msg_schema_info"] = info
            cloned.__dict__["_msg_schema_validated"] = True
        return cloned

    def __getitem__(self, key: str) -> Any:
        """msg['command']"""
        if key not in type(self).model_fields:
            raise KeyError(key)
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        """msg['command'] = 'start'"""
        names = type(self).model_fields
        if key not in names:
            raise KeyError(f"Field '{key}' is not a valid message field. Valid fields: {sorted(names.keys())}")
        setattr(self, key, value)

    def __contains__(self, key: str) -> bool:
        """'command' in msg"""
        return key in type(self).model_fields

    def get(self, key: str, default: Any = None) -> Any:
        """dict.get()"""
        return getattr(self, key, default)

    def keys(self) -> List[str]:
        """Ключи сообщения."""
        return list(type(self).model_fields.keys())

    def values(self) -> List[Any]:
        """Значения полей."""
        return [getattr(self, f) for f in type(self).model_fields]

    def items(self) -> List[Tuple[str, Any]]:
        """Пары (ключ, значение)."""
        return [(f, getattr(self, f)) for f in type(self).model_fields]

    def get_schema_info(self) -> Optional[Dict[str, str]]:
        """Метаданные внешней Pydantic-схемы или None."""
        return self.__dict__.get("_msg_schema_info")

    def get_schema(self) -> Optional[Type["BaseModel"]]:
        """Класс внешней Pydantic-схемы или None."""
        return self.__dict__.get("_msg_schema")

    def __repr__(self) -> str:
        parts = [
            f"type={self.type!r}",
            f"id={self.id!r}",
            f"sender={self.sender!r}",
            f"targets={self.targets!r}",
        ]
        schema_info = self.__dict__.get("_msg_schema_info")
        if schema_info:
            parts.append(f"schema={schema_info['schema_name']}")
        return f"Message({', '.join(parts)})"

    def __str__(self) -> str:
        return self.to_text()
