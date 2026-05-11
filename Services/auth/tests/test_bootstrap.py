# -*- coding: utf-8 -*-
"""
Тесты bootstrap CLI.

Сценарии: env var dev-password, слабый пароль, уже инициализировано, интерактивный режим.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from Services.auth.bootstrap import _PREDEFINED_ROLES, main
from Services.auth.storage import YamlUserStorage


# =============================================================================
# Вспомогательные функции
# =============================================================================


def _make_path(tmp_path: Path) -> str:
    """Путь к users.yaml в tmp_path."""
    return str(tmp_path / "users.yaml")


# =============================================================================
# Режим 1: INSPECTOR_DEV_PASSWORD задан
# =============================================================================


def test_dev_password_creates_dev_user(tmp_path: Path) -> None:
    """INSPECTOR_DEV_PASSWORD → создаётся dev-user, predefined роли, exit 0."""
    users_path = _make_path(tmp_path)

    with patch.dict(os.environ, {"INSPECTOR_DEV_PASSWORD": "DevPass@1", "INSPECTOR_AUTH_USERS_PATH": users_path}):
        exit_code = main()

    assert exit_code == 0

    storage = YamlUserStorage(users_path)
    assert storage.exists()

    users = storage.load()
    assert "dev" in users
    assert users["dev"].role_name == "dev"

    roles = storage.load_roles()
    for role_name in _PREDEFINED_ROLES:
        assert role_name in roles


def test_dev_password_creates_all_predefined_roles(tmp_path: Path) -> None:
    """bootstrap с INSPECTOR_DEV_PASSWORD создаёт все 4 predefined роли."""
    users_path = _make_path(tmp_path)

    with patch.dict(os.environ, {"INSPECTOR_DEV_PASSWORD": "DevPass@1", "INSPECTOR_AUTH_USERS_PATH": users_path}):
        exit_code = main()

    assert exit_code == 0

    storage = YamlUserStorage(users_path)
    roles = storage.load_roles()
    assert set(roles.keys()) == {"dev", "admin", "operator", "viewer"}


def test_dev_password_file_is_valid_yaml(tmp_path: Path) -> None:
    """Созданный файл является валидным YAML и читаем через YamlUserStorage."""
    users_path = _make_path(tmp_path)

    with patch.dict(os.environ, {"INSPECTOR_DEV_PASSWORD": "DevPass@1", "INSPECTOR_AUTH_USERS_PATH": users_path}):
        exit_code = main()

    assert exit_code == 0

    storage = YamlUserStorage(users_path)
    # Должно не падать
    users = storage.load()
    roles = storage.load_roles()
    assert isinstance(users, dict)
    assert isinstance(roles, dict)


# =============================================================================
# Режим 2: Слабый пароль → exit 2
# =============================================================================


def test_weak_dev_password_returns_exit_2(tmp_path: Path) -> None:
    """INSPECTOR_DEV_PASSWORD с слабым паролем → exit 2."""
    users_path = _make_path(tmp_path)

    with patch.dict(os.environ, {"INSPECTOR_DEV_PASSWORD": "weak", "INSPECTOR_AUTH_USERS_PATH": users_path}):
        exit_code = main()

    assert exit_code == 2


def test_weak_dev_password_no_file_created(tmp_path: Path) -> None:
    """При слабом пароле файл не остаётся после ошибки."""
    users_path = _make_path(tmp_path)

    with patch.dict(os.environ, {"INSPECTOR_DEV_PASSWORD": "weak", "INSPECTOR_AUTH_USERS_PATH": users_path}):
        main()

    assert not Path(users_path).exists()


# =============================================================================
# Режим 3: Уже инициализировано → exit 1
# =============================================================================


def test_already_initialized_returns_exit_1(tmp_path: Path) -> None:
    """Если users.yaml существует → exit 1."""
    users_path = _make_path(tmp_path)
    # Создаём файл-заглушку
    Path(users_path).parent.mkdir(parents=True, exist_ok=True)
    Path(users_path).write_text("users: {}\nroles: {}\n", encoding="utf-8")

    with patch.dict(os.environ, {"INSPECTOR_AUTH_USERS_PATH": users_path}, clear=False):
        # Убираем INSPECTOR_DEV_PASSWORD если вдруг задан
        env = {k: v for k, v in os.environ.items() if k != "INSPECTOR_DEV_PASSWORD"}
        env["INSPECTOR_AUTH_USERS_PATH"] = users_path
        with patch.dict(os.environ, env, clear=True):
            exit_code = main()

    assert exit_code == 1


# =============================================================================
# Режим 4: Интерактивный режим (monkeypatch input/getpass)
# =============================================================================


def test_interactive_creates_admin_user(tmp_path: Path) -> None:
    """Интерактивный режим → создаётся admin-пользователь, exit 0."""
    users_path = _make_path(tmp_path)

    # Убираем INSPECTOR_DEV_PASSWORD, задаём путь
    env = {k: v for k, v in os.environ.items() if k != "INSPECTOR_DEV_PASSWORD"}
    env["INSPECTOR_AUTH_USERS_PATH"] = users_path

    with (
        patch.dict(os.environ, env, clear=True),
        patch("Services.auth.bootstrap.input", return_value=""),        # default "admin"
        patch("Services.auth.bootstrap.getpass.getpass", return_value="AdminPass@1"),
    ):
        exit_code = main()

    assert exit_code == 0

    storage = YamlUserStorage(users_path)
    users = storage.load()
    assert "admin" in users
    assert users["admin"].role_name == "admin"
