# -*- coding: utf-8 -*-
"""
Services/auth/security — трекер блокировок и реестр permissions.

Публичные экспорты:
    LockoutTracker       — in-memory трекер блокировок (thread-safe)
    PermissionsRegistry  — декларативный каталог permissions (thread-safe)
    PermissionDescriptor — описание отдельного permission

Импортируйте через фасад:
    from Services.auth import LockoutTracker, PermissionsRegistry, PermissionDescriptor
"""
from __future__ import annotations

from .lockout import LockoutTracker
from .permissions import PermissionDescriptor, PermissionsRegistry

__all__ = [
    "LockoutTracker",
    "PermissionsRegistry",
    "PermissionDescriptor",
]
