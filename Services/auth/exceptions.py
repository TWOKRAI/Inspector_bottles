# -*- coding: utf-8 -*-
"""
Исключения модуля Services/auth.

Коды ошибок AUTH-001..AUTH-012 соответствуют таблице в Appendix B метаплана.
Все исключения наследуют от AuthError — базового класса для auth-домена.

Использование:
    from Services.auth.exceptions import InvalidCredentials, WeakPassword

    raise InvalidCredentials("Неверный логин или пароль")
"""
from __future__ import annotations


class AuthError(Exception):
    """Базовый класс для всех ошибок аутентификации и авторизации."""

    # Код ошибки для ErrorManager (AUTH-XXX)
    code: str = "AUTH-000"

    def __init__(self, message: str = "", **context: object) -> None:
        super().__init__(message)
        self.message = message
        # Дополнительный контекст для логирования (без паролей)
        self.context: dict[str, object] = context

    def __str__(self) -> str:
        return self.message or self.__class__.__name__


# =============================================================================
# AUTH-001..AUTH-012 — конкретные исключения
# =============================================================================


class InvalidCredentials(AuthError):
    """AUTH-001 — Неверный логин или пароль."""

    code = "AUTH-001"


class UserNotFound(AuthError):
    """AUTH-002 — Пользователь не найден."""

    code = "AUTH-002"


class UserAlreadyExists(AuthError):
    """AUTH-003 — Пользователь уже существует."""

    code = "AUTH-003"


class RoleNotFound(AuthError):
    """AUTH-004 — Роль не найдена."""

    code = "AUTH-004"


class PermissionDenied(AuthError):
    """AUTH-005 — Недостаточно прав для этого действия."""

    code = "AUTH-005"


class WeakPassword(AuthError):
    """AUTH-006 — Пароль не соответствует требованиям безопасности."""

    code = "AUTH-006"


class AuditImmutableError(AuthError):
    """AUTH-007 — Audit log защищён от изменений (UPDATE/DELETE запрещены)."""

    code = "AUTH-007"


class DevPasswordRequired(AuthError):
    """AUTH-008 — Не задан INSPECTOR_DEV_PASSWORD (setup-режим)."""

    code = "AUTH-008"


class StorageCorrupted(AuthError):
    """AUTH-009 — Ошибка чтения хранилища пользователей."""

    code = "AUTH-009"


class SessionExpired(AuthError):
    """AUTH-010 — Сессия истекла, войдите снова."""

    code = "AUTH-010"


class LastAdminError(AuthError):
    """AUTH-011 — Нельзя удалить/деактивировать последнего администратора."""

    code = "AUTH-011"


class AccountLocked(AuthError):
    """AUTH-012 — Учётная запись временно заблокирована.

    Атрибуты:
        failures    — количество неудачных попыток
        delay_sec   — секунд до разблокировки
    """

    code = "AUTH-012"

    def __init__(
        self,
        message: str = "",
        *,
        failures: int = 0,
        delay_sec: int = 0,
        **context: object,
    ) -> None:
        super().__init__(message, failures=failures, delay_sec=delay_sec, **context)
        self.failures = failures
        self.delay_sec = delay_sec
