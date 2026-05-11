# -*- coding: utf-8 -*-
"""
Публичные контракты Services/auth.

Все интерфейсы — Protocol с @runtime_checkable для структурной типизации
и удобства мокирования в тестах.

Внешние модули импортируют только из interfaces.py:
    from Services.auth.interfaces import IAuthManager, IUserStorage, IPasswordHasher

По образцу Services/sql/interfaces.py.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .models import AuditEntry


# =============================================================================
# IPasswordHasher
# =============================================================================


@runtime_checkable
class IPasswordHasher(Protocol):
    """Контракт хешера паролей."""

    def hash(self, password: str) -> str:
        """Хешировать пароль. Возвращает строку хеша."""

    def verify(self, password: str, hashed: str) -> bool:
        """Проверить пароль против хеша. True если совпадает."""


# =============================================================================
# IUserStorage
# =============================================================================


@runtime_checkable
class IUserStorage(Protocol):
    """
    Контракт хранилища пользователей и ролей.

    Возвращает dict (Dict at Boundary при пересечении слоёв).
    Внутри хранилища используются Pydantic-модели.
    """

    def load(self) -> dict[str, Any]:
        """
        Загрузить всех пользователей.

        Returns:
            dict {username: User} (Pydantic-объекты внутри хранилища).
        """

    def save(self, users: dict[str, Any]) -> None:
        """
        Сохранить пользователей атомарно.

        Args:
            users — dict {username: User}
        """

    def load_roles(self) -> dict[str, Any]:
        """
        Загрузить все роли.

        Returns:
            dict {role_name: Role} (Pydantic-объекты внутри хранилища).
        """

    def save_roles(self, roles: dict[str, Any]) -> None:
        """
        Сохранить роли атомарно.

        Args:
            roles — dict {role_name: Role}
        """

    def exists(self) -> bool:
        """True если файл/источник данных существует."""


# =============================================================================
# IAuthManager
# =============================================================================


@runtime_checkable
class IAuthManager(Protocol):
    """
    Контракт менеджера аутентификации.

    Все методы принимают и возвращают dict (Dict at Boundary).
    Ошибки сообщаются через ObservableMixin.report_error, не через raise.

    Реализуется: AuthManager(BaseManager, ObservableMixin) — Группа B.
    """

    def login(self, username: str, password: str) -> dict[str, Any]:
        """
        Аутентифицировать пользователя.

        Returns:
            dict с полями: success, role_name, permissions, level, message.
        """

    def logout(self) -> None:
        """Очистить текущую сессию."""

    def create_user(
        self,
        username: str,
        password: str,
        role_name: str,
    ) -> dict[str, Any]:
        """
        Создать нового пользователя.

        Returns:
            dict с полями: success, user_id, message.
        """

    def delete_user(self, username: str) -> None:
        """
        Удалить пользователя. Проверяет last-admin invariant.

        Raises:
            UserNotFound   — пользователь не существует
            LastAdminError — нельзя удалить последнего активного admin
        """

    def update_user_role(self, username: str, role_name: str) -> None:
        """
        Изменить роль пользователя. Проверяет last-admin invariant.

        Raises:
            UserNotFound   — пользователь не существует
            RoleNotFound   — роль не существует
            LastAdminError — нельзя снять роль admin с последнего активного admin
        """

    def reset_password(self, username: str) -> str:
        """
        Сбросить пароль пользователя (генерирует новый).

        Returns:
            Новый пароль в plain-text (возвращается один раз, не логируется).

        Raises:
            UserNotFound — пользователь не существует
        """

    def list_users(self) -> list[dict[str, Any]]:
        """
        Получить список пользователей (без password_hash).

        Returns:
            Список dict (Dict at Boundary). password_hash исключён.
        """

    def list_roles(self) -> list[dict[str, Any]]:
        """
        Получить список ролей.

        Returns:
            Список dict (Dict at Boundary).
        """

    def create_role(
        self,
        name: str,
        permissions: list[str],
        level: int = 0,
        hidden_in_ui: bool = False,
        bypass_readonly: bool = False,
        show_hidden: bool = False,
    ) -> dict[str, Any]:
        """
        Создать новую роль.

        Returns:
            dict с полями роли.

        Raises:
            AuthError — роль с таким именем уже существует
        """

    def update_role_permissions(self, name: str, permissions: list[str]) -> None:
        """
        Обновить список permissions роли.

        Raises:
            RoleNotFound — роль не существует
        """

    def delete_role(self, name: str) -> None:
        """
        Удалить роль.

        Raises:
            AuthError    — роль является predefined (dev/admin/operator/viewer)
            RoleNotFound — роль не существует
        """

    def verify_admin_password(self, password: str) -> bool:
        """
        Проверить пароль текущего admin-пользователя (для confirm-диалогов).

        Returns:
            True если пароль верный.
        """


# =============================================================================
# IAuditWriter
# =============================================================================


@runtime_checkable
class IAuditWriter(Protocol):
    """Контракт асинхронного писателя аудит-лога."""

    def log(self, entry: "AuditEntry") -> None:
        """
        Поставить запись аудита в очередь (non-blocking).

        Args:
            entry: Экземпляр AuditEntry (рекомендуется через AuditEntry.with_truncation).
        """


# =============================================================================
# ISessionTracker
# =============================================================================


@runtime_checkable
class ISessionTracker(Protocol):
    """Контракт трекера сессий пользователей."""

    def open_session(self, user_id: str, username: str) -> str:
        """
        Открыть новую сессию.

        Args:
            user_id:  UUID пользователя.
            username: Имя пользователя (денормализованное).

        Returns:
            session_id (UUID4 строка).
        """

    def close_session(self, session_id: str) -> None:
        """
        Закрыть сессию (проставить logout_at).

        Args:
            session_id: UUID4 идентификатор сессии.
        """
