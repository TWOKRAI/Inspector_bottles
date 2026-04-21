# multiprocess_prototype/managers/access_context.py
"""Контекст доступа для таблиц рецептов (уровень + опциональный обход readonly/hidden)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class AccessContext:
    """level — числовой уровень; bypass_readonly/show_hidden — только для доверенной сессии."""

    level: int = 0
    bypass_readonly: bool = False
    show_hidden: bool = False

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AccessContext":
        if not data:
            return cls()
        return cls(
            level=int(data.get("level", 0)),
            bypass_readonly=bool(data.get("bypass_readonly", False)),
            show_hidden=bool(data.get("show_hidden", False)),
        )
