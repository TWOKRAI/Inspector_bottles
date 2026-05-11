# -*- coding: utf-8 -*-
"""
Services/auth/crypto — хеширование паролей и политики безопасности.

Публичные экспорты:
    BcryptHasher  — хеширование и верификация паролей через bcrypt
    PasswordPolicy — правила валидации паролей
    LockoutPolicy  — правила блокировки при неудачных попытках

Импортируйте через фасад:
    from Services.auth import BcryptHasher, PasswordPolicy, LockoutPolicy
"""
from __future__ import annotations

from .hasher import BcryptHasher
from .policies import LockoutPolicy, PasswordPolicy

__all__ = [
    "BcryptHasher",
    "PasswordPolicy",
    "LockoutPolicy",
]
