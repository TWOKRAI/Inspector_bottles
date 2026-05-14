# -*- coding: utf-8 -*-
"""
Тесты YamlUserStorage.

Покрывают: CRUD на tmp_path, atomic write (файл не повреждается при прерывании).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from Services.auth import Role, StorageCorrupted, User, YamlUserStorage


# =============================================================================
# Фикстуры
# =============================================================================


def _make_user(username: str, role_name: str = "operator") -> User:
    """Создать тестового пользователя."""
    return User(
        user_id=f"uid-{username}",
        username=username,
        password_hash="$2b$04$fakehashfortesting",
        role_name=role_name,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _make_role(name: str, level: int = 1) -> Role:
    """Создать тестовую роль."""
    return Role(
        name=name,
        level=level,
        permissions=["tabs.recipes.view"],
    )


@pytest.fixture
def storage(tmp_path: Path) -> YamlUserStorage:
    """Storage с файлом в tmp_path."""
    return YamlUserStorage(tmp_path / "users.yaml")


# =============================================================================
# Базовый CRUD — пользователи
# =============================================================================


def test_load_nonexistent_file_returns_empty(storage: YamlUserStorage) -> None:
    """Файл не существует → load() возвращает пустой dict."""
    assert storage.load() == {}


def test_save_and_load_user(storage: YamlUserStorage) -> None:
    """Сохранённый пользователь загружается корректно."""
    user = _make_user("alice", role_name="admin")
    storage.save({"alice": user})

    loaded = storage.load()
    assert "alice" in loaded
    assert loaded["alice"].username == "alice"
    assert loaded["alice"].role_name == "admin"
    assert loaded["alice"].user_id == "uid-alice"


def test_save_multiple_users(storage: YamlUserStorage) -> None:
    """Несколько пользователей сохраняются и загружаются."""
    users = {
        "alice": _make_user("alice", "admin"),
        "bob": _make_user("bob", "operator"),
        "carol": _make_user("carol", "viewer"),
    }
    storage.save(users)
    loaded = storage.load()
    assert set(loaded.keys()) == {"alice", "bob", "carol"}
    assert loaded["bob"].role_name == "operator"


def test_save_overwrites_existing(storage: YamlUserStorage) -> None:
    """Повторный save заменяет предыдущих пользователей."""
    storage.save({"alice": _make_user("alice", "operator")})
    storage.save({"alice": _make_user("alice", "admin")})

    loaded = storage.load()
    assert loaded["alice"].role_name == "admin"


def test_password_hash_preserved(storage: YamlUserStorage) -> None:
    """password_hash сохраняется и восстанавливается без изменений."""
    user = _make_user("alice")
    user_with_hash = user.model_copy(update={"password_hash": "$2b$04$realspecialhash"})
    storage.save({"alice": user_with_hash})

    loaded = storage.load()
    assert loaded["alice"].password_hash == "$2b$04$realspecialhash"


# =============================================================================
# Базовый CRUD — роли
# =============================================================================


def test_load_roles_nonexistent_returns_empty(storage: YamlUserStorage) -> None:
    """Файл не существует → load_roles() возвращает пустой dict."""
    assert storage.load_roles() == {}


def test_save_and_load_roles(storage: YamlUserStorage) -> None:
    """Роли сохраняются и загружаются корректно."""
    roles = {
        "admin": _make_role("admin", level=9),
        "viewer": _make_role("viewer", level=1),
    }
    storage.save_roles(roles)

    loaded = storage.load_roles()
    assert "admin" in loaded
    assert loaded["admin"].level == 9
    assert loaded["viewer"].name == "viewer"


def test_users_and_roles_coexist(storage: YamlUserStorage) -> None:
    """Users и roles хранятся в одном файле без взаимных перезаписей."""
    storage.save({"alice": _make_user("alice")})
    storage.save_roles({"admin": _make_role("admin", level=9)})

    # После save_roles пользователи сохранились
    users = storage.load()
    assert "alice" in users

    # После save ролей — роли тоже на месте
    roles = storage.load_roles()
    assert "admin" in roles


def test_save_users_preserves_roles(storage: YamlUserStorage) -> None:
    """save(users) не стирает существующие роли."""
    storage.save_roles({"admin": _make_role("admin")})
    storage.save({"alice": _make_user("alice")})

    roles = storage.load_roles()
    assert "admin" in roles


def test_save_roles_preserves_users(storage: YamlUserStorage) -> None:
    """save_roles(roles) не стирает существующих пользователей."""
    storage.save({"alice": _make_user("alice")})
    storage.save_roles({"viewer": _make_role("viewer")})

    users = storage.load()
    assert "alice" in users


# =============================================================================
# exists()
# =============================================================================


def test_exists_false_when_no_file(storage: YamlUserStorage) -> None:
    assert storage.exists() is False


def test_exists_true_after_save(storage: YamlUserStorage) -> None:
    storage.save({"alice": _make_user("alice")})
    assert storage.exists() is True


# =============================================================================
# Atomic write: файл не повреждается при ошибке записи
# =============================================================================


def test_atomic_write_original_preserved_on_error(tmp_path: Path) -> None:
    """
    Если запись прерывается на середине — оригинальный файл остаётся нетронутым.

    Симулируем через мок: os.replace бросает OSError.
    Оригинальный файл должен содержать старые данные.
    """
    yaml_path = tmp_path / "users.yaml"
    storage = YamlUserStorage(yaml_path)

    # Сохраняем первоначальные данные
    original_user = _make_user("alice", "admin")
    storage.save({"alice": original_user})

    original_content = yaml_path.read_text(encoding="utf-8")

    # Пытаемся сохранить новые данные, но os.replace падает
    with patch("Services.auth.storage.yaml_users.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            storage.save({"bob": _make_user("bob", "operator")})

    # Оригинальный файл должен остаться нетронутым
    current_content = yaml_path.read_text(encoding="utf-8")
    assert current_content == original_content

    # Загрузка должна вернуть старые данные
    loaded = storage.load()
    assert "alice" in loaded
    assert "bob" not in loaded


def test_atomic_write_no_tmp_files_left_on_error(tmp_path: Path) -> None:
    """При ошибке записи временные файлы убираются."""
    yaml_path = tmp_path / "users.yaml"
    storage = YamlUserStorage(yaml_path)

    with patch("Services.auth.storage.yaml_users.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            storage.save({"alice": _make_user("alice")})

    # Нет .tmp файлов в директории
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0, f"Остались tmp-файлы: {tmp_files}"


def test_atomic_write_creates_file_correctly(storage: YamlUserStorage) -> None:
    """Нормальная запись создаёт файл и он читаем."""
    storage.save({"alice": _make_user("alice")})
    assert storage.path.exists()
    # Файл должен быть валидным YAML
    loaded = storage.load()
    assert "alice" in loaded


# =============================================================================
# Обработка ошибок
# =============================================================================


def test_load_corrupted_yaml_raises_storage_corrupted(tmp_path: Path) -> None:
    """Повреждённый YAML-файл вызывает StorageCorrupted."""
    yaml_path = tmp_path / "users.yaml"
    yaml_path.write_text("not: valid: yaml: {{{", encoding="utf-8")
    storage = YamlUserStorage(yaml_path)

    with pytest.raises(StorageCorrupted):
        storage.load()


def test_load_invalid_user_data_raises_storage_corrupted(tmp_path: Path) -> None:
    """Невалидные данные пользователя вызывают StorageCorrupted."""
    yaml_path = tmp_path / "users.yaml"
    yaml_path.write_text(
        "users:\n  alice:\n    username: alice\n    invalid_field: true\n",
        encoding="utf-8",
    )
    storage = YamlUserStorage(yaml_path)

    with pytest.raises(StorageCorrupted):
        storage.load()


def test_path_property(storage: YamlUserStorage) -> None:
    """path property возвращает переданный путь."""
    assert isinstance(storage.path, Path)
