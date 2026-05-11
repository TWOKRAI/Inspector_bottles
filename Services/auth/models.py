# -*- coding: utf-8 -*-
"""
Pydantic-модели домена аутентификации.

Все модели наследуют SchemaBase и регистрируются через @register_schema.
FieldMeta используется для метаданных полей и флага sensitive=True на password_hash.

Важно: модели НИКОГДА не передаются между процессами напрямую — только через
to_dict() / model_dump() (правило «Dict at Boundary», ADR-008).

Зарегистрированные имена схем:
    "auth_user"   → User
    "auth_role"   → Role
    "auth_config" → AuthConfig
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)

from .crypto.policies import LockoutPolicy, PasswordPolicy


# =============================================================================
# Вспомогательный FieldMeta для sensitive-полей (не логируются)
# =============================================================================


def _sensitive_meta(description: str, **kwargs: object) -> FieldMeta:
    """
    FieldMeta с пометкой sensitive=True (скрывает значение в логах и repr).

    Реализация: FieldMeta.hidden=True (скрыт в UI-отображении).
    Дополнительно — overridden __repr__ в модели.
    """
    # FieldMeta не имеет атрибута sensitive, используем hidden=True
    # и документируем явно через info, чтобы инструменты понимали
    return FieldMeta(
        description,
        hidden=True,
        info="SENSITIVE — не логируется и не выводится в repr.",
        **kwargs,  # type: ignore[arg-type]
    )


# =============================================================================
# User — пользователь системы
# =============================================================================


@register_schema("auth_user")
class User(SchemaBase):
    """
    Пользователь системы аутентификации.

    Поле password_hash помечено как sensitive (FieldMeta hidden=True).
    Не логируется, не появляется в repr.
    """

    user_id: Annotated[
        str,
        FieldMeta("ID пользователя", info="UUID или строковый идентификатор."),
    ]

    username: Annotated[
        str,
        FieldMeta("Имя пользователя", info="Уникальное имя для входа в систему."),
    ]

    # Sensitive-поле: bcrypt-хеш пароля, не логируется
    password_hash: Annotated[
        str,
        _sensitive_meta("Хеш пароля (bcrypt)"),
    ]

    role_name: Annotated[
        str,
        FieldMeta("Роль", info="Имя роли из Role.name."),
    ]

    created_at: Annotated[
        datetime,
        FieldMeta("Дата создания", info="UTC-время создания пользователя."),
    ]

    last_login_at: Annotated[
        Optional[datetime],
        FieldMeta("Последний вход", info="UTC-время последнего успешного входа."),
    ] = None

    login_count: Annotated[
        int,
        FieldMeta("Число входов", info="Счётчик успешных аутентификаций.", min=0),
    ] = 0

    is_active: Annotated[
        bool,
        FieldMeta("Активен", info="False — учётная запись деактивирована."),
    ] = True

    def safe_dump(self) -> dict:
        """Dict-сериализация User БЕЗ password_hash — для возврата наружу/в логи."""
        data = self.model_dump()
        data.pop("password_hash", None)
        return data

    def __repr__(self) -> str:
        """Repr без password_hash (sensitive-поле)."""
        return (
            f"User(user_id={self.user_id!r}, username={self.username!r}, "
            f"role_name={self.role_name!r}, is_active={self.is_active})"
        )

    def __str__(self) -> str:
        return self.__repr__()


# =============================================================================
# Role — роль с набором permissions
# =============================================================================


@register_schema("auth_role")
class Role(SchemaBase):
    """
    Роль пользователя — именованный набор permissions + legacy level.

    Predefined роли (dev/admin/operator/viewer) создаются bootstrap'ом
    и не могут быть удалены через AuthManager.
    """

    name: Annotated[
        str,
        FieldMeta("Имя роли", info="Уникальный идентификатор роли."),
    ]

    level: Annotated[
        int,
        FieldMeta(
            "Legacy-уровень",
            info="Числовой уровень доступа для обратной совместимости (0–10).",
            min=0, max=10,
        ),
    ] = 0

    permissions: list[str] = []
    """Список строк в формате <scope>.<resource>.<action>."""

    hidden_in_ui: Annotated[
        bool,
        FieldMeta(
            "Скрыть в UI",
            info="True — роль не отображается в списке ролей в интерфейсе (например, dev).",
        ),
    ] = False

    bypass_readonly: Annotated[
        bool,
        FieldMeta(
            "Обход readonly",
            info="True — пользователь с этой ролью может изменять readonly-поля.",
        ),
    ] = False

    show_hidden: Annotated[
        bool,
        FieldMeta(
            "Показывать скрытые элементы",
            info="True — пользователь видит hidden-виджеты и скрытые поля.",
        ),
    ] = False


# =============================================================================
# AuthConfig — конфигурация модуля аутентификации
# =============================================================================


@register_schema("auth_config")
class AuthConfig(SchemaBase):
    """
    Конфигурация системы аутентификации.

    Загружается из env-переменных (INSPECTOR_AUTH_USERS_PATH, …)
    или передаётся напрямую при инициализации AuthManager.

    Вложенные объекты PasswordPolicy и LockoutPolicy — SchemaBase,
    сериализуются вместе с основной конфигурацией.
    """

    users_path: Annotated[
        str,
        FieldMeta(
            "Путь к YAML-файлу пользователей",
            info="Абсолютный путь. Если не задан — используется INSPECTOR_AUTH_USERS_PATH.",
        ),
    ] = ""

    bcrypt_rounds: Annotated[
        int,
        FieldMeta(
            "Rounds bcrypt",
            info="Переопределяет PasswordPolicy.bcrypt_rounds_prod/test. 0 = брать из политики.",
            min=0, max=31,
        ),
    ] = 0

    password_policy: PasswordPolicy = PasswordPolicy()
    """Политика паролей (вложенный SchemaBase)."""

    lockout_policy: LockoutPolicy = LockoutPolicy()
    """Политика блокировки (вложенный SchemaBase)."""
