# -*- coding: utf-8 -*-
"""
Services/auth — модуль аутентификации и RBAC.

Фасадный экспорт публичного API (единственный канал публичного API).

Импортируйте ТОЛЬКО через этот модуль:
    from Services.auth import (
        AuthError, InvalidCredentials, WeakPassword,
        User, Role, AuthConfig,
        PasswordPolicy, LockoutPolicy,
        BcryptHasher,
        LockoutTracker,
        YamlUserStorage,
        PermissionsRegistry, PermissionDescriptor,
        IAuthManager, IUserStorage, IPasswordHasher,
    )

Внутренние пути sub-package (crypto/, storage/, security/) — приватные.
"""
from __future__ import annotations

# --- Исключения ---
from .exceptions import (
    AccountLocked,
    AuditImmutableError,
    AuthError,
    DevPasswordRequired,
    InvalidCredentials,
    LastAdminError,
    PermissionDenied,
    RoleNotFound,
    SessionExpired,
    StorageCorrupted,
    UserAlreadyExists,
    UserNotFound,
    WeakPassword,
)

# --- Модели ---
from .models import AuthConfig, Role, User

# --- Crypto: hasher + политики ---
from .crypto import BcryptHasher, LockoutPolicy, PasswordPolicy

# --- Storage ---
from .storage import YamlUserStorage

# --- Security: lockout + permissions ---
from .security import LockoutTracker, PermissionDescriptor, PermissionsRegistry

# --- Interfaces (Protocol) ---
from .interfaces import IAuthManager, IPasswordHasher, IUserStorage

__all__ = [
    # Исключения
    "AuthError",
    "InvalidCredentials",
    "UserNotFound",
    "UserAlreadyExists",
    "RoleNotFound",
    "PermissionDenied",
    "WeakPassword",
    "AuditImmutableError",
    "DevPasswordRequired",
    "StorageCorrupted",
    "SessionExpired",
    "LastAdminError",
    "AccountLocked",
    # Модели
    "User",
    "Role",
    "AuthConfig",
    # Crypto
    "BcryptHasher",
    "PasswordPolicy",
    "LockoutPolicy",
    # Storage
    "YamlUserStorage",
    # Security
    "LockoutTracker",
    "PermissionsRegistry",
    "PermissionDescriptor",
    # Interfaces
    "IAuthManager",
    "IUserStorage",
    "IPasswordHasher",
]
