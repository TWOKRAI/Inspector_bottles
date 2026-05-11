# -*- coding: utf-8 -*-
"""
Тесты AuthManager.

Bcrypt rounds=4 для скорости тестов.
Все тесты используют tmp_path для изоляции файловой системы.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from Services.auth import (
    AccountLocked,
    AuthConfig,
    AuthError,
    AuthManager,
    BcryptHasher,
    InvalidCredentials,
    LastAdminError,
    LockoutPolicy,
    PasswordPolicy,
    Role,
    RoleNotFound,
    User,
    UserAlreadyExists,
    UserNotFound,
    YamlUserStorage,
)


# =============================================================================
# Фикстуры
# =============================================================================


@pytest.fixture
def config(tmp_path: Path) -> AuthConfig:
    """AuthConfig с rounds=4, быстрой lockout-политикой."""
    return AuthConfig(
        users_path=str(tmp_path / "users.yaml"),
        bcrypt_rounds=4,
        password_policy=PasswordPolicy(
            min_length=8,
            require_classes=3,
            bcrypt_rounds_prod=4,
            bcrypt_rounds_test=4,
        ),
        lockout_policy=LockoutPolicy(
            failed_threshold=5,
            reset_after_sec=1800,
            delays_sec=[30, 60, 120, 240, 480],
        ),
    )


@pytest.fixture
def manager(config: AuthConfig) -> AuthManager:
    """AuthManager с инициализацией."""
    m = AuthManager(config)
    m.initialize()
    return m


@pytest.fixture
def storage(config: AuthConfig) -> YamlUserStorage:
    """Storage для прямого управления данными в тестах."""
    return YamlUserStorage(config.users_path)


def _make_user(username: str, role_name: str = "admin") -> User:
    """Создать тестового пользователя с валидным bcrypt-хешем (rounds=4)."""
    hasher = BcryptHasher(rounds=4)
    return User(
        user_id=f"uid-{username}",
        username=username,
        password_hash=hasher.hash("ValidPass@1"),
        role_name=role_name,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        is_active=True,
    )


def _make_role(name: str, level: int = 1) -> Role:
    """Создать тестовую роль."""
    return Role(name=name, level=level, permissions=["tabs.view"])


def _seed_storage(storage: YamlUserStorage, config: AuthConfig) -> None:
    """Заполнить хранилище базовыми данными: роль admin + пользователь alice."""
    storage.save_roles({
        "admin": _make_role("admin", level=9),
        "operator": _make_role("operator", level=5),
        "viewer": _make_role("viewer", level=1),
    })
    storage.save({"alice": _make_user("alice", "admin")})


# =============================================================================
# lifecycle: initialize / shutdown
# =============================================================================


def test_initialize_returns_true(config: AuthConfig) -> None:
    """initialize() возвращает True и устанавливает is_initialized."""
    m = AuthManager(config)
    assert m.initialize() is True
    assert m.is_initialized is True


def test_shutdown_returns_true(manager: AuthManager) -> None:
    """shutdown() возвращает True, очищает состояние."""
    assert manager.shutdown() is True
    assert manager.is_initialized is False


# =============================================================================
# login: success
# =============================================================================


def test_login_success_returns_access_context(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """login() с верными данными возвращает dict AccessContext."""
    _seed_storage(storage, manager._config)
    ctx = manager.login("alice", "ValidPass@1")

    assert ctx["username"] == "alice"
    assert ctx["role_name"] == "admin"
    assert "level" in ctx
    assert isinstance(ctx["permissions"], list)
    assert "password_hash" not in ctx


def test_login_updates_last_login_at(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """login() обновляет last_login_at и login_count."""
    _seed_storage(storage, manager._config)
    manager.login("alice", "ValidPass@1")

    users = storage.load()
    assert users["alice"].last_login_at is not None
    assert users["alice"].login_count == 1


def test_login_permissions_sorted(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """login() возвращает permissions как sorted list."""
    storage.save_roles({
        "admin": Role(name="admin", level=9, permissions=["z.perm", "a.perm", "m.perm"])
    })
    storage.save({"alice": _make_user("alice", "admin")})

    ctx = manager.login("alice", "ValidPass@1")
    assert ctx["permissions"] == sorted(ctx["permissions"])


# =============================================================================
# login: failures
# =============================================================================


def test_login_wrong_password_raises(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """Неверный пароль → InvalidCredentials."""
    _seed_storage(storage, manager._config)
    with pytest.raises(InvalidCredentials):
        manager.login("alice", "WrongPass@1")


def test_login_unknown_user_raises(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """Несуществующий пользователь → InvalidCredentials (защита от user enumeration)."""
    _seed_storage(storage, manager._config)
    with pytest.raises(InvalidCredentials):
        manager.login("nobody", "ValidPass@1")


def test_login_inactive_user_raises(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """Деактивированный пользователь → InvalidCredentials."""
    storage.save_roles({"admin": _make_role("admin", 9)})
    inactive_user = _make_user("alice", "admin").model_copy(update={"is_active": False})
    storage.save({"alice": inactive_user})

    with pytest.raises(InvalidCredentials):
        manager.login("alice", "ValidPass@1")


# =============================================================================
# login: lockout
# =============================================================================


def test_lockout_after_n_failures(config: AuthConfig, storage: YamlUserStorage) -> None:
    """5 неудачных попыток → AccountLocked."""
    fast_config = AuthConfig(
        users_path=config.users_path,
        bcrypt_rounds=4,
        password_policy=config.password_policy,
        lockout_policy=LockoutPolicy(
            failed_threshold=5,
            reset_after_sec=3600,
            delays_sec=[30, 60],
        ),
    )
    m = AuthManager(fast_config)
    m.initialize()
    _seed_storage(storage, fast_config)

    # 5 неудач
    for _ in range(5):
        try:
            m.login("alice", "WrongPass@1")
        except (UserNotFound, InvalidCredentials):
            pass

    with pytest.raises(AccountLocked):
        m.login("alice", "ValidPass@1")


def test_lockout_reset_after_success(config: AuthConfig, storage: YamlUserStorage) -> None:
    """После успешного входа lockout сбрасывается."""
    fast_config = AuthConfig(
        users_path=config.users_path,
        bcrypt_rounds=4,
        password_policy=config.password_policy,
        lockout_policy=LockoutPolicy(
            failed_threshold=3,
            reset_after_sec=3600,
            delays_sec=[1, 2],
        ),
    )
    m = AuthManager(fast_config)
    m.initialize()
    _seed_storage(storage, fast_config)

    # 2 неудачи (меньше threshold)
    for _ in range(2):
        try:
            m.login("alice", "WrongPass@1")
        except InvalidCredentials:
            pass

    # Успешный вход — сбрасывает счётчик
    ctx = m.login("alice", "ValidPass@1")
    assert ctx["username"] == "alice"

    # Снова 2 неудачи — не блокирует
    for _ in range(2):
        try:
            m.login("alice", "WrongPass@1")
        except InvalidCredentials:
            pass

    # Должен пройти без AccountLocked
    ctx = m.login("alice", "ValidPass@1")
    assert ctx["username"] == "alice"


# =============================================================================
# logout
# =============================================================================


def test_logout_clears_session(manager: AuthManager, storage: YamlUserStorage) -> None:
    """logout() очищает _current_user."""
    _seed_storage(storage, manager._config)
    manager.login("alice", "ValidPass@1")
    assert manager._current_user is not None

    manager.logout()
    assert manager._current_user is None


# =============================================================================
# create_user
# =============================================================================


def test_create_user_success(manager: AuthManager, storage: YamlUserStorage) -> None:
    """create_user() создаёт пользователя и сохраняет в storage."""
    storage.save_roles({"operator": _make_role("operator", 5)})

    result = manager.create_user("bob", "ValidPass@1", "operator")
    assert result["username"] == "bob"
    assert result["role_name"] == "operator"

    users = storage.load()
    assert "bob" in users
    assert users["bob"].password_hash != "ValidPass@1"  # хеш, не plain-text


def test_create_user_duplicate_raises(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """Создание пользователя с существующим именем → UserAlreadyExists."""
    storage.save_roles({"admin": _make_role("admin", 9)})
    storage.save({"alice": _make_user("alice", "admin")})

    with pytest.raises(UserAlreadyExists):
        manager.create_user("alice", "NewPass@1", "admin")


def test_create_user_unknown_role_raises(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """Создание пользователя с несуществующей ролью → RoleNotFound."""
    storage.save_roles({"admin": _make_role("admin", 9)})

    with pytest.raises(RoleNotFound):
        manager.create_user("bob", "ValidPass@1", "nonexistent")


def test_create_user_weak_password_raises(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """Создание пользователя со слабым паролем → WeakPassword."""
    from Services.auth import WeakPassword

    storage.save_roles({"admin": _make_role("admin", 9)})

    with pytest.raises(WeakPassword):
        manager.create_user("bob", "weak", "admin")


# =============================================================================
# delete_user
# =============================================================================


def test_delete_user_success(manager: AuthManager, storage: YamlUserStorage) -> None:
    """delete_user() удаляет пользователя."""
    storage.save_roles({
        "admin": _make_role("admin", 9),
        "operator": _make_role("operator", 5),
    })
    storage.save({
        "alice": _make_user("alice", "admin"),
        "bob": _make_user("bob", "operator"),
    })

    manager.delete_user("bob")
    users = storage.load()
    assert "bob" not in users


def test_delete_user_not_found_raises(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """delete_user() несуществующего → UserNotFound."""
    storage.save_roles({"admin": _make_role("admin", 9)})
    storage.save({"alice": _make_user("alice", "admin")})

    with pytest.raises(UserNotFound):
        manager.delete_user("nobody")


def test_delete_last_admin_raises(manager: AuthManager, storage: YamlUserStorage) -> None:
    """Удаление последнего активного admin → LastAdminError."""
    storage.save_roles({"admin": _make_role("admin", 9)})
    storage.save({"alice": _make_user("alice", "admin")})

    with pytest.raises(LastAdminError):
        manager.delete_user("alice")


def test_delete_non_last_admin_ok(manager: AuthManager, storage: YamlUserStorage) -> None:
    """Удаление admin при наличии другого admin → OK."""
    storage.save_roles({"admin": _make_role("admin", 9)})
    storage.save({
        "alice": _make_user("alice", "admin"),
        "bob": _make_user("bob", "admin"),
    })

    manager.delete_user("bob")
    users = storage.load()
    assert "bob" not in users
    assert "alice" in users


# =============================================================================
# update_user_role
# =============================================================================


def test_update_user_role_success(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """update_user_role() меняет роль пользователя."""
    storage.save_roles({
        "admin": _make_role("admin", 9),
        "operator": _make_role("operator", 5),
    })
    storage.save({
        "alice": _make_user("alice", "admin"),
        "bob": _make_user("bob", "admin"),
    })

    manager.update_user_role("bob", "operator")
    users = storage.load()
    assert users["bob"].role_name == "operator"


def test_update_last_admin_role_raises(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """Снятие роли admin с последнего активного admin → LastAdminError."""
    storage.save_roles({
        "admin": _make_role("admin", 9),
        "operator": _make_role("operator", 5),
    })
    storage.save({"alice": _make_user("alice", "admin")})

    with pytest.raises(LastAdminError):
        manager.update_user_role("alice", "operator")


def test_update_role_unknown_user_raises(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """update_user_role() несуществующего → UserNotFound."""
    storage.save_roles({"admin": _make_role("admin", 9)})
    with pytest.raises(UserNotFound):
        manager.update_user_role("nobody", "admin")


def test_update_role_unknown_role_raises(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """update_user_role() с несуществующей ролью → RoleNotFound."""
    storage.save_roles({
        "admin": _make_role("admin", 9),
        "operator": _make_role("operator", 5),
    })
    storage.save({
        "alice": _make_user("alice", "admin"),
        "bob": _make_user("bob", "admin"),
    })

    with pytest.raises(RoleNotFound):
        manager.update_user_role("bob", "superadmin")


# =============================================================================
# reset_password
# =============================================================================


def test_reset_password_returns_new_password(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """reset_password() возвращает новый plain-text пароль."""
    storage.save_roles({"admin": _make_role("admin", 9)})
    storage.save({"alice": _make_user("alice", "admin")})

    new_password = manager.reset_password("alice")
    assert isinstance(new_password, str)
    assert len(new_password) >= 8


def test_reset_password_validates_new_password(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """Новый пароль после reset соответствует PasswordPolicy (через login)."""
    storage.save_roles({"admin": _make_role("admin", 9)})
    storage.save({"alice": _make_user("alice", "admin")})

    new_password = manager.reset_password("alice")
    # Логинимся с новым паролем
    ctx = manager.login("alice", new_password)
    assert ctx["username"] == "alice"


def test_reset_password_changes_hash(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """После reset_password хеш в storage изменился."""
    storage.save_roles({"admin": _make_role("admin", 9)})
    original_user = _make_user("alice", "admin")
    storage.save({"alice": original_user})
    old_hash = original_user.password_hash

    manager.reset_password("alice")

    users = storage.load()
    assert users["alice"].password_hash != old_hash


def test_reset_password_not_found_raises(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """reset_password() несуществующего → UserNotFound."""
    with pytest.raises(UserNotFound):
        manager.reset_password("nobody")


# =============================================================================
# list_users
# =============================================================================


def test_list_users_excludes_password_hash(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """list_users() не включает password_hash."""
    _seed_storage(storage, manager._config)
    users = manager.list_users()
    for user_dict in users:
        assert "password_hash" not in user_dict


def test_list_users_sorted(manager: AuthManager, storage: YamlUserStorage) -> None:
    """list_users() возвращает отсортированный список."""
    storage.save_roles({"admin": _make_role("admin", 9), "operator": _make_role("operator", 5)})
    storage.save({
        "charlie": _make_user("charlie", "admin"),
        "alice": _make_user("alice", "admin"),
        "bob": _make_user("bob", "operator"),
    })
    users = manager.list_users()
    usernames = [u["username"] for u in users]
    assert usernames == sorted(usernames)


# =============================================================================
# Role CRUD
# =============================================================================


def test_create_role_success(manager: AuthManager, storage: YamlUserStorage) -> None:
    """create_role() создаёт новую роль."""
    result = manager.create_role(
        name="qa",
        permissions=["tabs.recipes.view"],
        level=3,
    )
    assert result["name"] == "qa"
    assert result["level"] == 3

    roles = storage.load_roles()
    assert "qa" in roles


def test_create_role_empty_permissions(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """create_role() с пустым списком permissions — OK."""
    result = manager.create_role(name="readonly", permissions=[])
    assert result["permissions"] == []


def test_create_role_duplicate_raises(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """create_role() с дублирующимся именем → AuthError."""
    manager.create_role(name="qa", permissions=["tabs.view"])
    with pytest.raises(AuthError):
        manager.create_role(name="qa", permissions=["tabs.edit"])


def test_delete_role_predefined_raises(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """delete_role('admin') → AuthError (predefined role)."""
    storage.save_roles({"admin": _make_role("admin", 9)})

    with pytest.raises(AuthError):
        manager.delete_role("admin")


def test_delete_role_predefined_dev_raises(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """delete_role('dev') → AuthError (predefined role)."""
    with pytest.raises(AuthError):
        manager.delete_role("dev")


def test_delete_role_not_found_raises(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """delete_role() несуществующей → RoleNotFound."""
    with pytest.raises(RoleNotFound):
        manager.delete_role("nonexistent")


def test_delete_role_custom_success(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """delete_role() кастомной роли → OK."""
    storage.save_roles({"qa": _make_role("qa", 3)})
    manager.delete_role("qa")
    roles = storage.load_roles()
    assert "qa" not in roles


def test_update_role_permissions_success(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """update_role_permissions() обновляет и персистирует permissions."""
    storage.save_roles({"operator": _make_role("operator", 5)})
    manager.update_role_permissions("operator", ["tabs.recipes.view", "tabs.pipeline.edit"])

    roles = storage.load_roles()
    assert "tabs.recipes.view" in roles["operator"].permissions
    assert "tabs.pipeline.edit" in roles["operator"].permissions


def test_update_role_permissions_not_found_raises(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """update_role_permissions() несуществующей → RoleNotFound."""
    with pytest.raises(RoleNotFound):
        manager.update_role_permissions("nonexistent", ["tabs.view"])


# =============================================================================
# verify_admin_password
# =============================================================================


def test_verify_admin_password_correct(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """verify_admin_password() с верным паролем → True."""
    _seed_storage(storage, manager._config)
    manager.login("alice", "ValidPass@1")
    assert manager.verify_admin_password("ValidPass@1") is True


def test_verify_admin_password_wrong(
    manager: AuthManager, storage: YamlUserStorage
) -> None:
    """verify_admin_password() с неверным паролем → False."""
    _seed_storage(storage, manager._config)
    manager.login("alice", "ValidPass@1")
    assert manager.verify_admin_password("WrongPass@1") is False


def test_verify_admin_password_no_session(manager: AuthManager) -> None:
    """verify_admin_password() без активной сессии → False."""
    assert manager.verify_admin_password("AnyPassword@1") is False
