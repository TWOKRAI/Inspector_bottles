# frontend_module/managers/access_context.py
"""Контекст доступа для таблиц рецептов (уровень + опциональный обход readonly/hidden).

PR1-Group-C: расширен полями permissions (frozenset[str]) и role_name (str).
Старые поля level/bypass_readonly/show_hidden остаются на тех же позициях — позиционные
вызовы AccessContext(5, True, True) продолжают работать без изменений.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class AccessContext:
    """
    Контекст текущих прав пользователя.

    Поля (порядок сохранён для backward-compat с позиционными вызовами):
    - level          — числовой уровень (legacy fallback)
    - bypass_readonly — доверенная сессия: пропустить readonly-ограничения
    - show_hidden    — показывать скрытые поля
    - permissions    — именованные permissions (frozenset, неизменяемый)
    - role_name      — имя роли текущего пользователя
    """

    level: int = 0
    bypass_readonly: bool = False
    show_hidden: bool = False
    # Новые поля ПОСЛЕ старых — позиционные AccessContext(5, True, True) не ломаются
    permissions: frozenset[str] = frozenset()
    role_name: str = ""

    def has_permission(self, name: str) -> bool:
        """Проверить наличие именованного права."""
        return name in self.permissions

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AccessContext":
        """
        Создать AccessContext из словаря.

        Новые ключи permissions/role_name опциональны — backward compat:
        если отсутствуют, подставляются дефолты.
        """
        if not data:
            return cls()
        raw_permissions = data.get("permissions", [])
        permissions: frozenset
        if isinstance(raw_permissions, (list, tuple, set, frozenset)):
            permissions = frozenset(str(p) for p in raw_permissions)
        else:
            permissions = frozenset()
        return cls(
            level=int(data.get("level", 0)),
            bypass_readonly=bool(data.get("bypass_readonly", False)),
            show_hidden=bool(data.get("show_hidden", False)),
            permissions=permissions,
            role_name=str(data.get("role_name", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Сериализовать в dict.

        permissions сериализуется как sorted list[str] для детерминизма.
        """
        return {
            "level": self.level,
            "bypass_readonly": self.bypass_readonly,
            "show_hidden": self.show_hidden,
            "permissions": sorted(self.permissions),
            "role_name": self.role_name,
        }
