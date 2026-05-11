# -*- coding: utf-8 -*-
"""
PermissionsRegistry — декларативный каталог permissions.

Используется для регистрации и перечисления именованных permissions
в namespace-формате <scope>.<resource>.<action>.

Thread-safe через threading.Lock.

Пример:
    from Services.auth.permissions_registry import PermissionsRegistry

    registry = PermissionsRegistry()
    registry.register("tabs.recipes.view", "Просмотр вкладки Рецепты")
    registry.register("tabs.recipes.edit", "Редактирование рецептов")

    for perm in registry.list_all():
        print(perm.name, perm.description)
"""
from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionDescriptor:
    """
    Описание отдельного permission.

    Атрибуты:
        name        — идентификатор в формате <scope>.<resource>.<action>
        description — человекочитаемое описание для UI
    """

    name: str
    description: str


class PermissionsRegistry:
    """
    Реестр именованных permissions.

    Каждая permission регистрируется один раз с уникальным именем.
    Повторная регистрация с тем же именем — молчаливое игнорирование
    (идемпотентность при многократном импорте модулей).
    """

    def __init__(self) -> None:
        self._permissions: dict[str, PermissionDescriptor] = {}
        self._lock = threading.Lock()

    def register(self, name: str, description: str) -> None:
        """
        Зарегистрировать permission.

        Args:
            name        — строка в формате <scope>.<resource>.<action>.
                          Рекомендуется kebab-case для scope (tabs.recipes.view).
            description — описание для UI и документации.

        Если имя уже зарегистрировано — молча игнорируется.
        """
        with self._lock:
            if name not in self._permissions:
                self._permissions[name] = PermissionDescriptor(
                    name=name,
                    description=description,
                )

    def list_all(self) -> list[PermissionDescriptor]:
        """
        Получить список всех зарегистрированных permissions.

        Returns:
            Список PermissionDescriptor, отсортированный по name.
        """
        with self._lock:
            return sorted(self._permissions.values(), key=lambda p: p.name)

    def has(self, name: str) -> bool:
        """Проверить наличие зарегистрированного permission."""
        with self._lock:
            return name in self._permissions

    def get(self, name: str) -> PermissionDescriptor | None:
        """Получить PermissionDescriptor по имени или None."""
        with self._lock:
            return self._permissions.get(name)

    def clear(self) -> None:
        """Очистить реестр (для тестов)."""
        with self._lock:
            self._permissions.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._permissions)
