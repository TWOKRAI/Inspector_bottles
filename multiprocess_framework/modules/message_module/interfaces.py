# -*- coding: utf-8 -*-
"""
Публичные контракты message_module.

IMessage — контракт любого сообщения (Protocol, structural typing).

Правило: внешние модули импортируют только из interfaces.py, не из core/.
Создавать сообщения через Message.create() или MessageAdapter.

Правило Dict at Boundary (ADR-008):
    При передаче через границу процессов:  msg.to_dict()
    При получении из очереди:              Message.from_dict(raw_dict)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Union

try:
    from typing import Protocol, runtime_checkable
except ImportError:
    from typing_extensions import Protocol, runtime_checkable  # type: ignore[misc]


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

    def to_dict(
        self,
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None,
    ) -> Dict[str, Any]: ...

    def to_json(
        self,
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None,
        indent: Optional[int] = None,
    ) -> str: ...

    def get(self, key: str, default: Any = None) -> Any: ...

    def clone(self) -> "IMessage": ...

    def get_schema_info(self) -> Optional[Dict[str, str]]: ...
