# -*- coding: utf-8 -*-
"""
Services/auth — модуль аутентификации и RBAC.

Фасадный экспорт публичного API.

На данном этапе (Группа A, PR1) экспортируются только инфраструктурные
компоненты без AuthManager (Группа B).

Импортируйте через этот модуль:
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

# --- Политики ---
from .policies import LockoutPolicy, PasswordPolicy

# --- Модели ---
from .models import AuthConfig, Role, User

# --- Hasher ---
from .hasher import BcryptHasher

# --- Lockout ---
from .lockout_tracker import LockoutTracker

# --- Storage ---
from .storage_users import YamlUserStorage

# --- Permissions ---
from .permissions_registry import PermissionDescriptor, PermissionsRegistry

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
    # Политики
    "PasswordPolicy",
    "LockoutPolicy",
    # Модели
    "User",
    "Role",
    "AuthConfig",
    # Hasher
    "BcryptHasher",
    # Lockout
    "LockoutTracker",
    # Storage
    "YamlUserStorage",
    # Permissions
    "PermissionsRegistry",
    "PermissionDescriptor",
    # Interfaces
    "IAuthManager",
    "IUserStorage",
    "IPasswordHasher",
]
