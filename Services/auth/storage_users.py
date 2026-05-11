# -*- coding: utf-8 -*-
"""
YamlUserStorage — хранилище пользователей и ролей в YAML-файле.

Использует `pathlib.Path` для работы с файлом напрямую (YAML),
т.к. FileStorage из data_schema_module работает с JSON-форматом.

Формат файла (единый YAML с двумя секциями):
    users:
      alice:
        user_id: "..."
        username: "alice"
        password_hash: "$2b$..."
        role_name: "admin"
        ...
    roles:
      admin:
        name: "admin"
        level: 9
        permissions: [...]
        ...

Atomic write: запись идёт во временный файл рядом с целевым,
затем os.replace() — атомарно в POSIX, атомарно на Windows (Python 3.3+).

Sensitive-поля (password_hash) НИКОГДА не попадают в логи.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .exceptions import StorageCorrupted
from .models import Role, User


class YamlUserStorage:
    """
    Хранилище пользователей и ролей в YAML-файле.

    Формат: два раздела users: / roles: в одном файле.
    Обеспечивает атомарные записи через tempfile + os.replace.

    Атрибуты:
        path — pathlib.Path к YAML-файлу (создаётся при save если не существует).
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        """Путь к YAML-файлу."""
        return self._path

    # =========================================================================
    # Публичный API
    # =========================================================================

    def load(self) -> dict[str, User]:
        """
        Загрузить пользователей из YAML.

        Returns:
            dict {username: User}. Пустой dict если файл не существует.

        Raises:
            StorageCorrupted — при ошибке парсинга YAML или валидации модели.
        """
        raw = self._read_yaml()
        users_data: dict[str, Any] = raw.get("users", {}) or {}

        result: dict[str, User] = {}
        for username, data in users_data.items():
            try:
                result[username] = User.model_validate(data)
            except Exception as exc:
                raise StorageCorrupted(
                    f"Ошибка валидации пользователя '{username}': {exc}",
                    path=str(self._path),
                ) from exc
        return result

    def save(self, users: dict[str, User]) -> None:
        """
        Сохранить пользователей атомарно.

        Существующие роли в файле сохраняются (не перезаписываются).

        Args:
            users — dict {username: User}

        Note:
            Атомарность: пишем во временный файл, затем os.replace().
        """
        raw = self._read_yaml()
        raw["users"] = {
            username: user.model_dump()
            for username, user in users.items()
        }
        self._atomic_yaml_dump(raw)

    def load_roles(self) -> dict[str, Role]:
        """
        Загрузить роли из YAML.

        Returns:
            dict {role_name: Role}. Пустой dict если файл не существует.

        Raises:
            StorageCorrupted — при ошибке парсинга или валидации.
        """
        raw = self._read_yaml()
        roles_data: dict[str, Any] = raw.get("roles", {}) or {}

        result: dict[str, Role] = {}
        for role_name, data in roles_data.items():
            try:
                result[role_name] = Role.model_validate(data)
            except Exception as exc:
                raise StorageCorrupted(
                    f"Ошибка валидации роли '{role_name}': {exc}",
                    path=str(self._path),
                ) from exc
        return result

    def save_roles(self, roles: dict[str, Role]) -> None:
        """
        Сохранить роли атомарно.

        Существующие пользователи в файле сохраняются.

        Args:
            roles — dict {role_name: Role}
        """
        raw = self._read_yaml()
        raw["roles"] = {
            role_name: role.model_dump()
            for role_name, role in roles.items()
        }
        self._atomic_yaml_dump(raw)

    def exists(self) -> bool:
        """Проверить наличие файла хранилища."""
        return self._path.exists()

    # =========================================================================
    # Внутренние методы
    # =========================================================================

    def _read_yaml(self) -> dict[str, Any]:
        """
        Прочитать YAML-файл. Возвращает пустой dict если файл не существует.

        Raises:
            StorageCorrupted — если YAML не парсится.
        """
        if not self._path.exists():
            return {}

        try:
            content = self._path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if data is None:
                return {}
            if not isinstance(data, dict):
                raise StorageCorrupted(
                    f"Ожидался YAML-dict, получено {type(data).__name__}",
                    path=str(self._path),
                )
            return data
        except StorageCorrupted:
            raise
        except Exception as exc:
            raise StorageCorrupted(
                f"Ошибка чтения YAML-файла: {exc}",
                path=str(self._path),
            ) from exc

    def _atomic_yaml_dump(self, data: dict[str, Any]) -> None:
        """
        Атомарно сохранить dict как YAML.

        Алгоритм:
        1. Создаём временный файл в той же директории (важно для rename!).
        2. Пишем данные в него.
        3. os.replace(tmp, target) — атомарная операция на POSIX и Windows.

        Если запись прерывается — целевой файл остаётся нетронутым.
        """
        # Гарантируем наличие родительской директории
        self._path.parent.mkdir(parents=True, exist_ok=True)

        content = yaml.dump(
            data,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=True,
        )

        # Временный файл должен быть на том же filesystem что и целевой,
        # иначе os.replace может падать с OSError на разных разделах.
        dir_path = str(self._path.parent)
        fd, tmp_path = tempfile.mkstemp(
            dir=dir_path,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.replace(tmp_path, str(self._path))
        except Exception:
            # Убираем временный файл при ошибке
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
