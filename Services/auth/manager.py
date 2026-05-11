# -*- coding: utf-8 -*-
"""
AuthManager — менеджер аутентификации и управления пользователями/ролями.

Наследует BaseManager + ObservableMixin.
Интеграция: logger через _log_info/_log_warning/_log_error.

Контракты:
- Все публичные методы принимают и возвращают dict (Dict at Boundary).
- login() возвращает dict-форму AccessContext (без password_hash).
- Ошибки: raise из exceptions.py + _log_warning перед raise для аудита.
- Никогда не логирует plain-text пароли и password_hash.

Использование:
    from Services.auth import AuthManager, AuthConfig

    config = AuthConfig(users_path="/data/auth/users.yaml")
    manager = AuthManager(config)
    manager.initialize()

    ctx = manager.login("alice", "MySecret@1")  # dict с полями AccessContext
    manager.logout()
"""
from __future__ import annotations

import secrets
import string
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin

from .crypto import BcryptHasher, PasswordPolicy
from .exceptions import (
    AccountLocked,
    AuthError,
    InvalidCredentials,
    LastAdminError,
    RoleNotFound,
    UserAlreadyExists,
    UserNotFound,
    WeakPassword,
)
from .interfaces import IAuditWriter, IPasswordHasher, ISessionTracker, IUserStorage
from .models import AuthConfig, Role, User
from .predefined_roles import PREDEFINED_ROLES as _PREDEFINED_ROLES_SPEC
from .security import LockoutTracker, PermissionsRegistry
from .storage import YamlUserStorage

# Predefined роли — запрещено удалять
_PREDEFINED_ROLES = frozenset(_PREDEFINED_ROLES_SPEC.keys())

# Длина генерируемого пароля при reset_password
_GENERATED_PASSWORD_LENGTH = 16


def _generate_password(length: int = _GENERATED_PASSWORD_LENGTH) -> str:
    """
    Сгенерировать случайный пароль, удовлетворяющий требованиям PasswordPolicy
    (min 3 из 4 классов символов, длина >= 8).

    Алгоритм: гарантируем минимум по 1 символу из lower/upper/digit/symbol,
    затем добавляем случайные символы до нужной длины и перемешиваем.
    """
    lower = string.ascii_lowercase
    upper = string.ascii_uppercase
    digits = string.digits
    special = "!@#$%^&*"
    alphabet = lower + upper + digits + special

    # Гарантируем по одному символу каждого класса
    chars = [
        secrets.choice(lower),
        secrets.choice(upper),
        secrets.choice(digits),
        secrets.choice(special),
    ]
    # Добавляем оставшиеся символы
    chars += [secrets.choice(alphabet) for _ in range(length - 4)]

    # Перемешиваем
    chars_list = list(chars)
    for i in range(len(chars_list) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars_list[i], chars_list[j] = chars_list[j], chars_list[i]

    return "".join(chars_list)


class AuthManager(BaseManager, ObservableMixin):
    """
    Менеджер аутентификации и RBAC.

    Ответственности:
    - Аутентификация пользователей (login/logout с LockoutTracker).
    - CRUD пользователей (create/delete/update_role/reset_password/list).
    - CRUD ролей (create/update_permissions/delete/list).
    - Проверка last-admin invariant.
    - Логирование auth-событий через ObservableMixin.

    Все методы возвращают dict (Dict at Boundary).
    Ошибки — raise из exceptions.py (с _log_warning для аудита).
    """

    def __init__(
        self,
        config: AuthConfig,
        storage: Optional[IUserStorage] = None,
        hasher: Optional[IPasswordHasher] = None,
        permissions: Optional[PermissionsRegistry] = None,
        managers: Optional[Dict[str, Any]] = None,
        process: Optional[Any] = None,
    ) -> None:
        BaseManager.__init__(self, "AuthManager", process=process)
        ObservableMixin.__init__(
            self,
            managers=managers or {},
            config={},
        )

        self._config = config

        # Зависимости (DI с дефолтами)
        rounds = config.bcrypt_rounds if config.bcrypt_rounds > 0 else config.password_policy.bcrypt_rounds_prod
        self._hasher: IPasswordHasher = hasher or BcryptHasher(rounds=rounds)
        self._storage: IUserStorage = storage or YamlUserStorage(config.users_path)
        self._permissions = permissions or PermissionsRegistry()

        # LockoutTracker создаётся всегда внутри (не DI — state in-memory)
        self._lockout = LockoutTracker(config.lockout_policy)

        # Текущий залогиненный пользователь (in-memory, не персистируется)
        self._current_user: Optional[User] = None

        # DI: AuditWriter и SessionTracker — инжектируются извне через сеттеры
        self._audit_writer: Optional[IAuditWriter] = None
        self._session_tracker: Optional[ISessionTracker] = None
        # Текущий session_id — проставляется в login(), сбрасывается в logout()
        self._current_session_id: Optional[str] = None

        # StatsManager: скользящее окно попыток входа (1 час)
        # Каждый элемент: (timestamp: datetime, success: bool)
        self._login_attempts: Deque[Tuple[datetime, bool]] = deque()

    # =========================================================================
    # Lifecycle (BaseManager)
    # =========================================================================

    def initialize(self) -> bool:
        """Инициализация: проверяем доступность хранилища и выравниваем predefined роли.

        Auto-merge: если в хранилище у predefined роли (admin/operator/viewer/dev)
        отсутствуют permissions, перечисленные в эталонном `PREDEFINED_ROLES`
        (`Services.auth.predefined_roles`), они добавляются и хранилище
        перезаписывается. Custom-роли не затрагиваются. Существующие permissions
        у predefined ролей не удаляются — миграция аддитивная.
        """
        self._migrate_predefined_roles_permissions()
        self.is_initialized = True
        self._log_info("AuthManager initialized")
        return True

    def _migrate_predefined_roles_permissions(self) -> None:
        """Добавить недостающие permissions в predefined-роли (idempotent)."""
        # До-bootstrap состояние — файл хранилища не создан; миграция отложена
        # до первого вызова bootstrap. Это предотвращает «теневое» создание
        # users.yaml только с predefined-ролями (без пользователей).
        if not self._storage.exists():
            return

        try:
            roles = self._storage.load_roles()
        except Exception as exc:
            # Любые ошибки чтения пробрасываем выше через лог — фоновую миграцию
            # не падаем, чтобы не блокировать lifecycle BaseManager.
            self._log_warning(
                f"auth.migrate.predefined_roles.skip: reason={type(exc).__name__}"
            )
            return

        changed = False
        for name, spec in _PREDEFINED_ROLES_SPEC.items():
            current = roles.get(name)
            if current is None:
                # Predefined-роль удалена — восстанавливаем целиком.
                roles[name] = spec
                changed = True
                self._log_info(
                    f"auth.migrate.predefined_roles.restored: name={name!r}"
                )
                continue
            expected = set(spec.permissions)
            existing = set(current.permissions)
            missing = expected - existing
            if not missing:
                continue
            merged_perms = sorted(existing | expected)
            roles[name] = current.model_copy(update={"permissions": merged_perms})
            changed = True
            self._log_info(
                f"auth.migrate.predefined_roles.merged: "
                f"name={name!r}, added={sorted(missing)}"
            )

        if changed:
            self._storage.save_roles(roles)

    def shutdown(self) -> bool:
        """Завершение: очищаем сессию."""
        self._current_user = None
        self.is_initialized = False
        self._log_info("AuthManager shutdown")
        return True

    # =========================================================================
    # DI: AuditWriter и SessionTracker
    # =========================================================================

    def set_audit_writer(self, writer: IAuditWriter) -> None:
        """Инжектировать AuditWriter (вызывается из composition root).

        Args:
            writer: Реализация IAuditWriter.
        """
        self._audit_writer = writer

    def set_session_tracker(self, tracker: ISessionTracker) -> None:
        """Инжектировать SessionTracker (вызывается из composition root).

        Если tracker является экземпляром SessionTracker (конкретная реализация,
        а не только интерфейс), дополнительно регистрирует callback для публикации
        метрики ``auth.sessions.active`` через ObservableMixin.

        Args:
            tracker: Реализация ISessionTracker.
        """
        from .session_tracker import SessionTracker as _ConcreteSessionTracker
        self._session_tracker = tracker
        # Подключаем callback для метрики активных сессий (только конкретная реализация)
        if isinstance(tracker, _ConcreteSessionTracker) and tracker._on_active_change is None:
            tracker._on_active_change = lambda count: self._record_metric(
                "auth.sessions.active", count
            )

    @property
    def permissions(self) -> PermissionsRegistry:
        """Каталог зарегистрированных permissions (read+write)."""
        return self._permissions

    # =========================================================================
    # StatsManager интеграция
    # =========================================================================

    def _record_login_attempt(self, success: bool) -> None:
        """
        Записать попытку входа в скользящее окно (1 час) и обновить метрики.

        Вызывается из login() при каждом исходе: AccountLocked,
        InvalidCredentials, успешный вход.

        Args:
            success: True — успешный вход, False — неудача.
        """
        now = datetime.now(timezone.utc)
        self._login_attempts.append((now, success))

        # Удалить записи старше 1 часа
        cutoff = now - timedelta(hours=1)
        while self._login_attempts and self._login_attempts[0][0] < cutoff:
            self._login_attempts.popleft()

        total = len(self._login_attempts)
        failed = sum(1 for _, ok in self._login_attempts if not ok)
        failed_ratio = failed / total if total > 0 else 0.0

        self._record_metric("auth.login.attempts.per_hour", total)
        self._record_metric("auth.login.failed_ratio", failed_ratio)

    # =========================================================================
    # Auth lifecycle
    # =========================================================================

    def login(self, username: str, password: str) -> dict:
        """
        Аутентифицировать пользователя.

        Returns:
            dict с полями AccessContext:
            {user_id, username, role_name, level, permissions (sorted list),
             bypass_readonly, show_hidden, last_login_at}

        Raises:
            AccountLocked     — аккаунт заблокирован из-за неудачных попыток
            UserNotFound      — пользователь не существует
            InvalidCredentials — неверный пароль или аккаунт неактивен
        """
        # Проверка блокировки ДО верификации пароля
        locked, wait_sec = self._lockout.is_locked(username)
        if locked:
            failures = self._lockout.get_failures(username)
            self._log_warning(
                f"auth.lockout.engaged: username={username!r}, delay_sec={wait_sec}, failures={failures}"
            )
            self._record_login_attempt(success=False)
            raise AccountLocked(
                f"Учётная запись временно заблокирована. Ждите {wait_sec} сек.",
                failures=failures,
                delay_sec=wait_sec,
            )

        # Загрузка пользователя
        users = self._storage.load()
        user = users.get(username)
        if user is None:
            self._lockout.record_failure(username)
            self._log_warning(f"auth.login.failed: username={username!r}, reason=user_not_found")
            self._record_login_attempt(success=False)
            # Единое исключение для unknown user и wrong password — защита от user enumeration
            raise InvalidCredentials("Неверный логин или пароль.", username=username)

        if not user.is_active:
            self._lockout.record_failure(username)
            self._log_warning(
                f"auth.login.failed: username={username!r}, reason=account_inactive"
            )
            self._record_login_attempt(success=False)
            raise InvalidCredentials(
                "Учётная запись деактивирована.", username=username
            )

        # Верификация пароля
        if not self._hasher.verify(password, user.password_hash):
            self._lockout.record_failure(username)
            self._log_warning(
                f"auth.login.failed: username={username!r}, reason=wrong_password"
            )
            self._record_login_attempt(success=False)
            raise InvalidCredentials("Неверный логин или пароль.", username=username)

        # Успех — сбрасываем lockout
        self._lockout.record_success(username)

        # Обновляем last_login_at и login_count
        now = datetime.now(timezone.utc)
        updated_user = user.model_copy(update={
            "last_login_at": now,
            "login_count": user.login_count + 1,
        })
        users[username] = updated_user
        self._storage.save(users)

        # Загружаем роль для построения AccessContext
        roles = self._storage.load_roles()
        role = roles.get(user.role_name)

        self._current_user = updated_user
        self._log_info(
            f"auth.login.success: username={username!r}, role_name={user.role_name!r}"
        )
        self._record_login_attempt(success=True)

        # Открываем сессию (если SessionTracker подключён)
        if self._session_tracker is not None:
            try:
                self._current_session_id = self._session_tracker.open_session(
                    updated_user.user_id, updated_user.username
                )
            except Exception as exc:
                self._log_error(
                    f"auth.session.open_failed: Не удалось открыть сессию: {exc!r}"
                )

        return self._build_access_context(updated_user, role)

    def logout(self) -> None:
        """Очистить текущую сессию."""
        username = self._current_user.username if self._current_user else "<none>"

        # Закрываем сессию ДО сброса _current_user (нужен session_id)
        if self._session_tracker is not None and self._current_session_id is not None:
            try:
                self._session_tracker.close_session(self._current_session_id)
            except Exception as exc:
                self._log_error(
                    f"auth.session.close_failed: "
                    f"Не удалось закрыть сессию {self._current_session_id!r}: {exc!r}"
                )

        self._current_user = None
        self._current_session_id = None
        self._log_info(f"auth.logout: username={username!r}")

    def verify_admin_password(self, password: str) -> bool:
        """
        Проверить пароль текущего пользователя (для confirm-диалогов в UI).

        Returns:
            True если текущий пользователь аутентифицирован и пароль совпадает.
        """
        if self._current_user is None:
            return False
        return self._hasher.verify(password, self._current_user.password_hash)

    # =========================================================================
    # User CRUD
    # =========================================================================

    def create_user(
        self,
        username: str,
        password: str,
        role_name: str,
    ) -> dict:
        """
        Создать нового пользователя.

        Raises:
            UserAlreadyExists — пользователь уже существует
            RoleNotFound      — указанная роль не существует
            WeakPassword      — пароль не соответствует политике

        Returns:
            dict {user_id, username, role_name}
        """
        # Валидация пароля
        self._config.password_policy.validate(password)

        users = self._storage.load()
        if username in users:
            self._log_warning(
                f"auth.create_user.failed: username={username!r}, reason=already_exists"
            )
            raise UserAlreadyExists(
                f"Пользователь '{username}' уже существует.", username=username
            )

        # Проверяем что роль существует
        roles = self._storage.load_roles()
        if role_name not in roles:
            self._log_warning(
                f"auth.create_user.failed: username={username!r}, reason=role_not_found, role={role_name!r}"
            )
            raise RoleNotFound(
                f"Роль '{role_name}' не найдена.", role_name=role_name
            )

        user_id = f"uid-{secrets.token_hex(8)}"
        new_user = User(
            user_id=user_id,
            username=username,
            password_hash=self._hasher.hash(password),
            role_name=role_name,
            created_at=datetime.now(timezone.utc),
        )
        users[username] = new_user
        self._storage.save(users)

        self._log_info(
            f"auth.user.created: username={username!r}, role_name={role_name!r}"
        )

        return {"user_id": user_id, "username": username, "role_name": role_name}

    def delete_user(self, username: str) -> None:
        """
        Удалить пользователя.

        Raises:
            UserNotFound      — пользователь не существует
            LastAdminError    — нельзя удалить последнего активного admin
        """
        users = self._storage.load()
        if username not in users:
            self._log_warning(
                f"auth.delete_user.failed: username={username!r}, reason=not_found"
            )
            raise UserNotFound(f"Пользователь '{username}' не найден.", username=username)

        # Last-admin invariant
        user = users[username]
        if user.role_name == "admin" and user.is_active:
            active_admins = [
                u for u in users.values()
                if u.role_name == "admin" and u.is_active
            ]
            if len(active_admins) <= 1:
                self._log_warning(
                    f"auth.delete_user.failed: username={username!r}, reason=last_admin"
                )
                raise LastAdminError(
                    f"Нельзя удалить последнего активного администратора.",
                    username=username,
                )

        del users[username]
        self._storage.save(users)
        self._log_info(f"auth.user.deleted: username={username!r}")

    def update_user_role(self, username: str, role_name: str) -> None:
        """
        Изменить роль пользователя.

        Raises:
            UserNotFound   — пользователь не существует
            RoleNotFound   — роль не существует
            LastAdminError — нельзя снять роль admin с последнего активного admin
        """
        users = self._storage.load()
        if username not in users:
            self._log_warning(
                f"auth.update_role.failed: username={username!r}, reason=not_found"
            )
            raise UserNotFound(f"Пользователь '{username}' не найден.", username=username)

        roles = self._storage.load_roles()
        if role_name not in roles:
            self._log_warning(
                f"auth.update_role.failed: username={username!r}, reason=role_not_found, role={role_name!r}"
            )
            raise RoleNotFound(f"Роль '{role_name}' не найдена.", role_name=role_name)

        user = users[username]
        old_role = user.role_name

        # Last-admin invariant: нельзя снять роль admin если это последний admin
        if old_role == "admin" and role_name != "admin" and user.is_active:
            active_admins = [
                u for u in users.values()
                if u.role_name == "admin" and u.is_active
            ]
            if len(active_admins) <= 1:
                self._log_warning(
                    f"auth.update_role.failed: username={username!r}, reason=last_admin"
                )
                raise LastAdminError(
                    f"Нельзя снять роль admin с последнего активного администратора.",
                    username=username,
                )

        updated = user.model_copy(update={"role_name": role_name})
        users[username] = updated
        self._storage.save(users)
        self._log_info(
            f"auth.user.role_updated: username={username!r}, old_role={old_role!r}, new_role={role_name!r}"
        )

    def reset_password(self, username: str) -> str:
        """
        Сбросить пароль пользователя (генерирует новый).

        Returns:
            Новый пароль в plain-text (возвращается один раз, не логируется).

        Raises:
            UserNotFound — пользователь не существует
        """
        users = self._storage.load()
        if username not in users:
            self._log_warning(
                f"auth.reset_password.failed: username={username!r}, reason=not_found"
            )
            raise UserNotFound(f"Пользователь '{username}' не найден.", username=username)

        new_password = _generate_password()
        user = users[username]
        updated = user.model_copy(update={"password_hash": self._hasher.hash(new_password)})
        users[username] = updated
        self._storage.save(users)

        # Логируем без пароля
        self._log_info(f"auth.password.reset: username={username!r}")

        return new_password

    def list_users(self) -> list[dict]:
        """
        Получить список пользователей (без password_hash).

        Returns:
            Список dict, отсортированных по username.
            password_hash исключён из каждого dict.
        """
        users = self._storage.load()
        return [
            user.safe_dump()
            for user in sorted(users.values(), key=lambda u: u.username)
        ]

    # =========================================================================
    # Role CRUD
    # =========================================================================

    def list_roles(self) -> list[dict]:
        """
        Получить список ролей.

        Returns:
            Список dict, отсортированных по name.
        """
        roles = self._storage.load_roles()
        return [r.model_dump() for r in sorted(roles.values(), key=lambda r: r.name)]

    def create_role(
        self,
        name: str,
        permissions: list[str],
        level: int = 0,
        hidden_in_ui: bool = False,
        bypass_readonly: bool = False,
        show_hidden: bool = False,
    ) -> dict:
        """
        Создать новую роль.

        Raises:
            AuthError — роль с таким именем уже существует

        Returns:
            dict с полями роли.
        """
        roles = self._storage.load_roles()
        if name in roles:
            self._log_warning(
                f"auth.create_role.failed: name={name!r}, reason=already_exists"
            )
            raise AuthError(f"Роль '{name}' уже существует.", name=name)

        new_role = Role(
            name=name,
            level=level,
            permissions=list(permissions),
            hidden_in_ui=hidden_in_ui,
            bypass_readonly=bypass_readonly,
            show_hidden=show_hidden,
        )
        roles[name] = new_role
        self._storage.save_roles(roles)

        self._log_info(
            f"auth.role.created: name={name!r}, level={level}, permissions={len(permissions)}"
        )
        return new_role.model_dump()

    def update_role_permissions(self, name: str, permissions: list[str]) -> None:
        """
        Обновить список permissions роли.

        Raises:
            RoleNotFound — роль не существует
        """
        roles = self._storage.load_roles()
        if name not in roles:
            self._log_warning(
                f"auth.update_role_permissions.failed: name={name!r}, reason=not_found"
            )
            raise RoleNotFound(f"Роль '{name}' не найдена.", role_name=name)

        updated = roles[name].model_copy(update={"permissions": list(permissions)})
        roles[name] = updated
        self._storage.save_roles(roles)
        self._log_info(
            f"auth.role.updated: name={name!r}, permissions_count={len(permissions)}"
        )

    def delete_role(self, name: str) -> None:
        """
        Удалить роль.

        Raises:
            AuthError    — роль является predefined (dev/admin/operator/viewer)
            RoleNotFound — роль не существует
        """
        if name in _PREDEFINED_ROLES:
            self._log_warning(
                f"auth.delete_role.failed: name={name!r}, reason=predefined"
            )
            raise AuthError(
                f"Нельзя удалить predefined роль '{name}'.",
                name=name,
            )

        roles = self._storage.load_roles()
        if name not in roles:
            self._log_warning(
                f"auth.delete_role.failed: name={name!r}, reason=not_found"
            )
            raise RoleNotFound(f"Роль '{name}' не найдена.", role_name=name)

        del roles[name]
        self._storage.save_roles(roles)
        self._log_info(f"auth.role.deleted: name={name!r}")

    # =========================================================================
    # Вспомогательные методы
    # =========================================================================

    def _build_access_context(self, user: User, role: Optional[Role]) -> dict:
        """
        Построить dict AccessContext из User + Role.

        Не включает password_hash.
        permissions сериализуется как sorted list[str].
        """
        perms: List[str] = sorted(role.permissions) if role else []
        return {
            "user_id": user.user_id,
            "username": user.username,
            "role_name": user.role_name,
            "level": role.level if role else 0,
            "permissions": perms,
            "bypass_readonly": role.bypass_readonly if role else False,
            "show_hidden": role.show_hidden if role else False,
            "last_login_at": (
                user.last_login_at.isoformat() if user.last_login_at else None
            ),
        }
