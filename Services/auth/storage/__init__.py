# -*- coding: utf-8 -*-
"""
Services/auth/storage — хранилище пользователей, ролей и аудита.

Публичные экспорты:
    YamlUserStorage    — хранилище пользователей/ролей в YAML-файле
                         с атомарными записями (tempfile + os.replace)
    SqliteAuditStorage — хранилище сессий и аудит-лога на SQLite
                         (append-only для AuditEntry)

Импортируйте через фасад:
    from Services.auth import YamlUserStorage, SqliteAuditStorage
"""
from __future__ import annotations

from .audit_storage import SqliteAuditStorage
from .yaml_users import YamlUserStorage

__all__ = [
    "YamlUserStorage",
    "SqliteAuditStorage",
]
