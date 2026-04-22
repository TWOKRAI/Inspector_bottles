# -*- coding: utf-8 -*-
"""
ProfileSwitchHandler — обработчик PROFILE_SWITCH действий.

apply():  применить forward_patch["snapshot"] — записать каждое поле в регистр через rm.
revert(): применить backward_patch["snapshot"] — откатить к снимку до переключения.

Snapshot format: {register_name: {field_name: value}} или {field_name: value}
(для profile используется один регистр SETTINGS_REGISTER, поэтому оба варианта поддержаны).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from ..bus import IRegistersManagerGui
    from ..schemas import Action

logger = logging.getLogger(__name__)


class ProfileSwitchHandler:
    """Обработчик действий типа PROFILE_SWITCH (переключение профиля настроек).

    Snapshot-based undo/redo: применяет снимок полей регистров целиком,
    не вызывая switch_profile повторно (только при undo/redo).
    """

    def apply(self, action: "Action", rm: "IRegistersManagerGui") -> None:
        """Применить forward_patch["snapshot"] к регистрам."""
        snapshot = action.forward_patch.get("snapshot")
        if snapshot is None:
            logger.warning(
                "ProfileSwitchHandler.apply: snapshot отсутствует в forward_patch, action_id=%s",
                action.action_id,
            )
            return
        self._apply_snapshot(snapshot, rm, "apply", action.action_id)

    def revert(self, action: "Action", rm: "IRegistersManagerGui") -> None:
        """Откатить: применить backward_patch["snapshot"] к регистрам."""
        snapshot = action.backward_patch.get("snapshot")
        if snapshot is None:
            logger.warning(
                "ProfileSwitchHandler.revert: snapshot отсутствует в backward_patch, action_id=%s",
                action.action_id,
            )
            return
        self._apply_snapshot(snapshot, rm, "revert", action.action_id)

    @staticmethod
    def _apply_snapshot(
        snapshot: Any,
        rm: "IRegistersManagerGui",
        operation: str,
        action_id: str,
    ) -> None:
        """Записать snapshot в регистры через rm.set_field_value.

        Поддерживает два формата snapshot:
        - {register_name: {field_name: value}} — полный (multi-register)
        - {field_name: value} — плоский (один регистр SETTINGS_REGISTER)
        """
        if not isinstance(snapshot, dict):
            logger.warning(
                "ProfileSwitchHandler.%s: snapshot не является dict, action_id=%s",
                operation,
                action_id,
            )
            return

        # Определяем формат: если значения — dict, то это multi-register формат
        is_multi_register = any(isinstance(v, dict) for v in snapshot.values())

        if is_multi_register:
            # {register_name: {field_name: value}}
            _apply_multi_register_snapshot(snapshot, rm, operation, action_id)
        else:
            # {field_name: value} — плоский (один регистр settings)
            from multiprocess_prototype_v3.registers.constants import SETTINGS_REGISTER
            _apply_register_fields(SETTINGS_REGISTER, snapshot, rm, operation, action_id)


def _apply_multi_register_snapshot(
    snapshot: Dict[str, Any],
    rm: "IRegistersManagerGui",
    operation: str,
    action_id: str,
) -> None:
    """Применить многорегистровый снимок {register_name: {field_name: value}}."""
    for register_name, fields in snapshot.items():
        if not isinstance(fields, dict):
            logger.warning(
                "ProfileSwitchHandler.%s: поля регистра '%s' не dict, action_id=%s",
                operation,
                register_name,
                action_id,
            )
            continue
        _apply_register_fields(register_name, fields, rm, operation, action_id)


def _apply_register_fields(
    register_name: str,
    fields: Dict[str, Any],
    rm: "IRegistersManagerGui",
    operation: str,
    action_id: str,
) -> None:
    """Записать каждое поле регистра через rm.set_field_value."""
    for field_name, value in fields.items():
        ok, err = rm.set_field_value(register_name, field_name, value)
        if not ok:
            logger.warning(
                "ProfileSwitchHandler.%s: set_field_value(%s, %s) вернул ошибку: %s, action_id=%s",
                operation,
                register_name,
                field_name,
                err,
                action_id,
            )
