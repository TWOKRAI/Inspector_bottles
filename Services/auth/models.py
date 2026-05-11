# -*- coding: utf-8 -*-
"""
Pydantic-модели домена аутентификации.

Все модели наследуют SchemaBase и регистрируются через @register_schema.
FieldMeta используется для метаданных полей и флага sensitive=True на password_hash.

Важно: модели НИКОГДА не передаются между процессами напрямую — только через
to_dict() / model_dump() (правило «Dict at Boundary», ADR-008).

Зарегистрированные имена схем:
    "auth_user"     → User
    "auth_role"     → Role
    "auth_config"   → AuthConfig
    "auth_session"  → SessionEntry
    "auth_audit"    → AuditEntry
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

# Максимальный размер before_json / after_json (10 КБ)
_JSON_MAX_BYTES = 10 * 1024
_TRUNCATED_SUFFIX = "<truncated>"


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

    audit_db_path: Annotated[
        str,
        FieldMeta(
            "Путь к SQLite БД аудита",
            info=(
                "Абсолютный путь к файлу audit.sqlite. "
                "Если не задан — аудит в памяти (только для тестов). "
                "Env: INSPECTOR_AUTH_DB_PATH."
            ),
        ),
    ] = ""


# =============================================================================
# SessionEntry — запись об одной сессии пользователя
# =============================================================================


@register_schema("auth_session")
class SessionEntry(SchemaBase):
    """
    Запись о сессии пользователя (login → logout).

    Хранится в таблице ``auth_sessions``.
    Индекс: (user_id, login_at) — для быстрой выборки сессий пользователя.
    """

    class SQLMeta:
        table_name = "auth_sessions"
        indexes = [("user_id", "login_at")]
        unique_together: tuple = ()
        primary_key = ["session_id"]

    session_id: Annotated[
        str,
        FieldMeta("ID сессии", info="UUID4 — уникальный идентификатор сессии."),
    ]

    user_id: Annotated[
        str,
        FieldMeta("ID пользователя", info="Ссылка на User.user_id."),
    ]

    username: Annotated[
        str,
        FieldMeta("Имя пользователя", info="Денормализованное имя для быстрого отображения."),
    ]

    login_at: Annotated[
        datetime,
        FieldMeta("Время входа", info="UTC-метка начала сессии."),
    ]

    logout_at: Annotated[
        Optional[datetime],
        FieldMeta("Время выхода", info="UTC-метка окончания сессии. None — активная сессия."),
    ] = None

    host: Annotated[
        str,
        FieldMeta("Хост", info="Имя хоста или IP-адрес клиента."),
    ] = "localhost"


# =============================================================================
# AuditEntry — неизменяемая запись аудит-лога
# =============================================================================


@register_schema("auth_audit")
class AuditEntry(SchemaBase):
    """
    Запись аудит-лога — фиксирует любое действие пользователя.

    Хранится в таблице ``audit_log``.
    Append-only: UPDATE и DELETE на этой таблице запрещены через SqliteAuditStorage.

    Метод-фабрика ``with_truncation`` автоматически усекает before_json / after_json
    если их размер превышает 10 КБ.
    """

    class SQLMeta:
        table_name = "audit_log"
        indexes = [("user_id", "ts"), ("resource", "ts")]
        unique_together: tuple = ()
        primary_key = ["entry_id"]

    entry_id: Annotated[
        str,
        FieldMeta("ID записи", info="UUID4 — уникальный идентификатор записи аудита."),
    ]

    ts: Annotated[
        datetime,
        FieldMeta("Метка времени", info="UTC-время события."),
    ]

    user_id: Annotated[
        str,
        FieldMeta("ID пользователя", info="Ссылка на User.user_id."),
    ]

    username: Annotated[
        str,
        FieldMeta("Имя пользователя", info="Денормализованное имя для отображения."),
    ]

    action_type: Annotated[
        str,
        FieldMeta("Тип действия", info="Строковый код действия (например, 'field_update')."),
    ]

    resource: Annotated[
        Optional[str],
        FieldMeta("Ресурс", info="Имя ресурса / поля / вкладки, к которому относится действие."),
    ] = None

    before_json: Annotated[
        Optional[str],
        FieldMeta("Состояние до", info="JSON-строка состояния ресурса ДО действия. Усекается при >10 KB."),
    ] = None

    after_json: Annotated[
        Optional[str],
        FieldMeta("Состояние после", info="JSON-строка состояния ресурса ПОСЛЕ действия. Усекается при >10 KB."),
    ] = None

    comment: Annotated[
        str,
        FieldMeta("Комментарий", info="Произвольный комментарий к записи аудита."),
    ] = ""

    @classmethod
    def with_truncation(
        cls,
        entry_id: str,
        ts: datetime,
        user_id: str,
        username: str,
        action_type: str,
        resource: Optional[str] = None,
        before_json: Optional[str] = None,
        after_json: Optional[str] = None,
        comment: str = "",
    ) -> "AuditEntry":
        """
        Фабричный метод — создать AuditEntry с автоматическим усечением
        before_json / after_json при превышении 10 КБ.

        Если значение превышает ``_JSON_MAX_BYTES``, оно обрезается и
        к нему добавляется суффикс ``<truncated>``.

        Args:
            entry_id:    UUID4 идентификатор записи.
            ts:          UTC-метка времени события.
            user_id:     ID пользователя.
            username:    Имя пользователя.
            action_type: Строковый код действия.
            resource:    Имя ресурса (опционально).
            before_json: JSON-строка «до» (опционально).
            after_json:  JSON-строка «после» (опционально).
            comment:     Произвольный комментарий.

        Returns:
            Новый экземпляр AuditEntry с усечёнными полями при необходимости.
        """
        return cls(
            entry_id=entry_id,
            ts=ts,
            user_id=user_id,
            username=username,
            action_type=action_type,
            resource=resource,
            before_json=_truncate_json(before_json),
            after_json=_truncate_json(after_json),
            comment=comment,
        )


def _truncate_json(value: Optional[str]) -> Optional[str]:
    """
    Усечь JSON-строку если её UTF-8 размер превышает 10 КБ.

    Добавляет суффикс ``<truncated>`` к усечённому значению.
    None передаётся без изменений.
    """
    if value is None:
        return None
    encoded = value.encode("utf-8")
    if len(encoded) <= _JSON_MAX_BYTES:
        return value
    # Обрезать до _JSON_MAX_BYTES байт, декодируя с игнорированием неполных символов
    truncated = encoded[:_JSON_MAX_BYTES].decode("utf-8", errors="ignore")
    return truncated + _TRUNCATED_SUFFIX
