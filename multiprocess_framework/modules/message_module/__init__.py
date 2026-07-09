# -*- coding: utf-8 -*-
"""
message_module — универсальный транспортный протокол системы.

Единый «язык» общения между менеджерами и процессами.
Все модули системы создают и получают сообщения через этот модуль.

Публичный API — импортируйте отсюда:

    from multiprocess_framework.modules.message_module import Message, MessageType, MessageAdapter
    from multiprocess_framework.modules.message_module import IMessage
    from multiprocess_framework.modules.message_module.interfaces import IMessage          # для type hints
"""

# --- Основной класс ---
from .core import Message

# --- Фабрики (удалён класс MessageFactory, оставлены функции для удобства) ---
from .factories import create_message, parse_message

# --- Типы и перечисления ---
from .types import (
    MessageType,
    Priority,
    LogLevel,
    MessageValidationError,
    AddressValidationError,
)

# --- Иерархическая адресация (dotted targets, P0.2 transport-router-hub) ---
from .addressing import (
    is_broadcast,
    normalize_targets,
    process_of,
    split_address,
    validate_address,
    worker_of,
)

# --- Pydantic-схемы (опционально, для валидации) ---
from .schemas import BaseMessageSchema, CommandMessageSchema, LogMessageSchema

# --- Адаптер (для использования в процессах/менеджерах) ---
from .adapters import MessageAdapter

# --- Билдеры протокола (один источник правды формы команд: GUI + driver) ---
from .builders import build_command_message, build_system_command_message

# --- Публичные интерфейсы (для type hints и моков) ---
from .interfaces import IMessage

# --- Реестр контрактов сообщений (Ф4.2) ---
from .contracts import (
    ContractCheck,
    MessageContract,
    MessageContractRegistry,
    contract_key_of,
    make_contract_check_middleware,
)

# --- Fencing-token: штамп конверта + drop stale на приёме (Ф4.2) ---
from .fencing import (
    FENCE_KEY,
    make_fence_filter_middleware,
    make_fence_stamp_middleware,
    read_fence,
)

__all__ = [
    # Основной класс
    "Message",
    # Адаптер
    "MessageAdapter",
    # Билдеры протокола (GUI + driver, один источник правды)
    "build_command_message",
    "build_system_command_message",
    # Фабричные функции
    "create_message",
    "parse_message",
    # Типы
    "MessageType",
    "Priority",
    "LogLevel",
    "MessageValidationError",
    "AddressValidationError",
    # Иерархическая адресация (dotted targets)
    "is_broadcast",
    "validate_address",
    "split_address",
    "process_of",
    "worker_of",
    "normalize_targets",
    # Pydantic-схемы
    "BaseMessageSchema",
    "CommandMessageSchema",
    "LogMessageSchema",
    # Интерфейсы (публичный контракт)
    "IMessage",
    # Реестр контрактов (Ф4.2)
    "MessageContract",
    "ContractCheck",
    "MessageContractRegistry",
    "make_contract_check_middleware",
    "contract_key_of",
    # Fencing-token (Ф4.2)
    "FENCE_KEY",
    "make_fence_stamp_middleware",
    "make_fence_filter_middleware",
    "read_fence",
]
