# -*- coding: utf-8 -*-
"""
Тесты RoleUpdateHandler — apply/revert обновления permissions через AuthManager.

Тесты не требуют Qt и не зависят от GUI.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.actions_module.schemas import Action
from multiprocess_prototype.frontend.actions.handlers.role_update_handler import RoleUpdateHandler
from Services.auth.interfaces import IAuthManager


# =============================================================================
# Вспомогательные фабрики
# =============================================================================


def _make_role_update_action(
    role_name: str = "operator",
    old_perms: list[str] | None = None,
    new_perms: list[str] | None = None,
) -> Action:
    """Создать Action с типом role_update для тестов."""
    if old_perms is None:
        old_perms = ["tabs.recipes.view", "tabs.recipes.edit"]
    if new_perms is None:
        new_perms = ["tabs.recipes.view"]

    return Action(
        action_type="role_update",
        forward_patch={"role_name": role_name, "permissions": new_perms},
        backward_patch={"role_name": role_name, "permissions": old_perms},
        resource=f"roles.{role_name}",
        undoable=True,
        description=f"Изменить права роли: {role_name}",
    )


def _make_handler(auth_manager=None) -> tuple[RoleUpdateHandler, MagicMock]:
    """Создать handler с mock auth_manager."""
    if auth_manager is None:
        auth_manager = MagicMock(spec=IAuthManager)
    return RoleUpdateHandler(auth_manager), auth_manager


# =============================================================================
# Тесты apply
# =============================================================================


class TestRoleUpdateHandlerApply:
    """apply() → auth_manager.update_role_permissions(forward.role_name, forward.permissions)."""

    def test_apply_calls_update_permissions(self) -> None:
        """apply() вызывает update_role_permissions с новыми правами."""
        handler, auth_manager = _make_handler()
        action = _make_role_update_action(
            role_name="operator",
            old_perms=["tabs.recipes.view", "tabs.recipes.edit"],
            new_perms=["tabs.recipes.view"],
        )

        handler.apply(action, rm=None)

        auth_manager.update_role_permissions.assert_called_once_with(
            "operator", ["tabs.recipes.view"]
        )

    def test_apply_passes_empty_permissions(self) -> None:
        """apply() с пустыми new_permissions — update_role_permissions([])."""
        handler, auth_manager = _make_handler()
        action = _make_role_update_action(
            role_name="viewer",
            old_perms=["tabs.settings.view"],
            new_perms=[],
        )

        handler.apply(action, rm=None)

        auth_manager.update_role_permissions.assert_called_once_with("viewer", [])

    def test_apply_with_rm_none(self) -> None:
        """apply() не падает если rm=None (rm не используется)."""
        handler, auth_manager = _make_handler()
        action = _make_role_update_action()

        # Не должно бросить исключение
        handler.apply(action, rm=None)

        assert auth_manager.update_role_permissions.call_count == 1

    def test_apply_empty_role_name_skips(self) -> None:
        """apply() с пустым role_name не вызывает update_role_permissions."""
        handler, auth_manager = _make_handler()
        action = Action(
            action_type="role_update",
            forward_patch={"role_name": "", "permissions": ["tabs.recipes.view"]},
            backward_patch={"role_name": "", "permissions": []},
        )

        handler.apply(action, rm=None)

        auth_manager.update_role_permissions.assert_not_called()

    def test_apply_handles_auth_manager_exception(self) -> None:
        """apply() при исключении в auth_manager — логирует, не пробрасывает."""
        handler, auth_manager = _make_handler()
        auth_manager.update_role_permissions.side_effect = RuntimeError("Роль не найдена")
        action = _make_role_update_action()

        # Не должно пробрасывать исключение
        handler.apply(action, rm=None)

        auth_manager.update_role_permissions.assert_called_once()


# =============================================================================
# Тесты revert
# =============================================================================


class TestRoleUpdateHandlerRevert:
    """revert() → auth_manager.update_role_permissions(backward.role_name, backward.permissions)."""

    def test_revert_restores_old_permissions(self) -> None:
        """revert() вызывает update_role_permissions со старыми правами."""
        handler, auth_manager = _make_handler()
        action = _make_role_update_action(
            role_name="admin",
            old_perms=["tabs.settings.view", "tabs.settings.edit", "users.view"],
            new_perms=["tabs.settings.view"],
        )

        handler.revert(action, rm=None)

        auth_manager.update_role_permissions.assert_called_once_with(
            "admin",
            ["tabs.settings.view", "tabs.settings.edit", "users.view"],
        )

    def test_revert_with_rm_none(self) -> None:
        """revert() не падает если rm=None (rm не используется)."""
        handler, auth_manager = _make_handler()
        action = _make_role_update_action()

        handler.revert(action, rm=None)

        assert auth_manager.update_role_permissions.call_count == 1

    def test_revert_empty_role_name_skips(self) -> None:
        """revert() с пустым role_name не вызывает update_role_permissions."""
        handler, auth_manager = _make_handler()
        action = Action(
            action_type="role_update",
            forward_patch={"role_name": "", "permissions": []},
            backward_patch={"role_name": "", "permissions": ["tabs.recipes.view"]},
        )

        handler.revert(action, rm=None)

        auth_manager.update_role_permissions.assert_not_called()

    def test_revert_handles_auth_manager_exception(self) -> None:
        """revert() при исключении в auth_manager — логирует, не пробрасывает."""
        handler, auth_manager = _make_handler()
        auth_manager.update_role_permissions.side_effect = ValueError("Роль заблокирована")
        action = _make_role_update_action()

        handler.revert(action, rm=None)

        auth_manager.update_role_permissions.assert_called_once()


# =============================================================================
# Тесты apply+revert связка (undo-round-trip)
# =============================================================================


class TestRoleUpdateHandlerRoundTrip:
    """apply → revert возвращает исходные permissions."""

    def test_apply_then_revert_roundtrip(self) -> None:
        """apply() затем revert() — два вызова update_role_permissions."""
        handler, auth_manager = _make_handler()
        old_perms = ["tabs.recipes.view", "tabs.recipes.edit"]
        new_perms = ["tabs.recipes.view"]
        action = _make_role_update_action(
            role_name="operator",
            old_perms=old_perms,
            new_perms=new_perms,
        )

        handler.apply(action, rm=None)
        handler.revert(action, rm=None)

        assert auth_manager.update_role_permissions.call_count == 2
        calls = auth_manager.update_role_permissions.call_args_list
        # Первый вызов — apply с новыми правами
        assert calls[0].args == ("operator", new_perms)
        # Второй вызов — revert со старыми правами
        assert calls[1].args == ("operator", old_perms)
