"""Тесты для register_all_permissions — каталог permissions приложения."""
from __future__ import annotations

import pytest

from multiprocess_prototype.frontend.permissions import register_all_permissions
from multiprocess_prototype.frontend.tab_factory import TAB_ORDER
from Services.auth.security import PermissionsRegistry


class TestRegisterAllPermissions:
    """Проверки заполнения каталога permissions."""

    def test_registers_tabs_view_and_edit_for_every_tab(self):
        """Для каждой записи TAB_ORDER регистрируются view + edit permissions."""
        reg = PermissionsRegistry()
        register_all_permissions(reg)

        for tab in TAB_ORDER:
            tab_id = tab["id"]
            assert reg.has(f"tabs.{tab_id}.view"), (
                f"Не зарегистрирован tabs.{tab_id}.view"
            )
            assert reg.has(f"tabs.{tab_id}.edit"), (
                f"Не зарегистрирован tabs.{tab_id}.edit"
            )

    def test_registers_users_crud(self):
        """Users CRUD permissions присутствуют."""
        reg = PermissionsRegistry()
        register_all_permissions(reg)

        for name in (
            "users.view",
            "users.create",
            "users.edit",
            "users.delete",
            "users.reset_password",
        ):
            assert reg.has(name), f"Не зарегистрирован {name}"

    def test_registers_roles_permissions(self):
        """Roles permissions присутствуют (view + edit/create/delete для PR4)."""
        reg = PermissionsRegistry()
        register_all_permissions(reg)

        for name in (
            "roles.view",
            "roles.edit",
            "roles.create",
            "roles.delete",
        ):
            assert reg.has(name), f"Не зарегистрирован {name}"

    def test_idempotent(self):
        """Повторный вызов не дублирует и не падает."""
        reg = PermissionsRegistry()
        register_all_permissions(reg)
        size_first = len(reg)

        register_all_permissions(reg)
        assert len(reg) == size_first

    def test_total_count(self):
        """7 табов × 2 (view+edit) + 5 users + 4 roles = 23 permissions."""
        reg = PermissionsRegistry()
        register_all_permissions(reg)
        assert len(reg) == len(TAB_ORDER) * 2 + 5 + 4
