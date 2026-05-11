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

from typing import Any, Protocol, runtime_checkable


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

    def delete_user(self, username: str) -> dict[str, Any]:
        """
        Удалить пользователя. Проверяет last-admin invariant.

        Returns:
            dict с полями: success, message.
        """

    def update_user_role(self, username: str, role_name: str) -> dict[str, Any]:
        """
        Изменить роль пользователя. Проверяет last-admin invariant.

        Returns:
            dict с полями: success, message.
        """

    def reset_password(self, username: str) -> dict[str, Any]:
        """
        Сбросить пароль пользователя (генерирует новый).

        Returns:
            dict с полями: success, new_password (plain-text!), message.
            Примечание: new_password возвращается один раз и не логируется.
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

    def verify_admin_password(self, password: str) -> bool:
        """
        Проверить пароль текущего admin-пользователя (для confirm-диалогов).

        Returns:
            True если пароль верный.
        """
