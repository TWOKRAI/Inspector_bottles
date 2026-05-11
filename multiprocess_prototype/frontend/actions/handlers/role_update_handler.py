# -*- coding: utf-8 -*-
"""RoleUpdateHandler — apply/revert обновления permissions роли через AuthManager.

Используется ActionBus для undoable-изменения прав:
  - apply:  forward_patch  → auth_manager.update_role_permissions(new)
  - revert: backward_patch → auth_manager.update_role_permissions(old)

Не требует IRegistersManagerGui — rm может быть None.
Логируется через AuditMiddleware автоматически (PR4 Group B).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from multiprocess_framework.modules.actions_module.schemas import Action
    from Services.auth.interfaces import IAuthManager

logger = logging.getLogger(__name__)


class RoleUpdateHandler:
    """Обработчик role_update: применяет/откатывает permissions роли через AuthManager.

    Совместим с протоколом ActionHandler (apply/revert).

    Args:
        auth_manager: Реализация IAuthManager (AuthManager или mock в тестах).
    """

    def __init__(self, auth_manager: "IAuthManager") -> None:
        self._auth_manager = auth_manager

    def apply(self, action: "Action", rm: Any) -> None:
        """Установить новые permissions роли (forward_patch).

        Args:
            action: Action с forward_patch = {"role_name": str, "permissions": list[str]}.
            rm:     RegistersManager — не используется (может быть None).
        """
        role_name: str = action.forward_patch.get("role_name", "")
        permissions: list[str] = action.forward_patch.get("permissions", [])

        if not role_name:
            logger.warning("role_update apply: role_name пустое, пропускаем")
            return

        try:
            self._auth_manager.update_role_permissions(role_name, permissions)
        except Exception as exc:
            logger.warning(
                "role_update apply failed: role=%r → %s",
                role_name, exc,
            )

    def revert(self, action: "Action", rm: Any) -> None:
        """Восстановить предыдущие permissions роли (backward_patch).

        Args:
            action: Action с backward_patch = {"role_name": str, "permissions": list[str]}.
            rm:     RegistersManager — не используется (может быть None).
        """
        role_name: str = action.backward_patch.get("role_name", "")
        permissions: list[str] = action.backward_patch.get("permissions", [])

        if not role_name:
            logger.warning("role_update revert: role_name пустое, пропускаем")
            return

        try:
            self._auth_manager.update_role_permissions(role_name, permissions)
        except Exception as exc:
            logger.warning(
                "role_update revert failed: role=%r → %s",
                role_name, exc,
            )
