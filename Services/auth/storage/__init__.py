# -*- coding: utf-8 -*-
"""
Services/auth/storage — хранилище пользователей и ролей.

Публичные экспорты:
    YamlUserStorage — хранилище пользователей/ролей в YAML-файле
                      с атомарными записями (tempfile + os.replace)

Импортируйте через фасад:
    from Services.auth import YamlUserStorage
"""
from __future__ import annotations

from .yaml_users import YamlUserStorage

__all__ = [
    "YamlUserStorage",
]
