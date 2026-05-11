"""FieldSetHandler — apply/revert изменения поля регистра через RegistersManager.

Phase 12: опциональная интеграция с TopologyBridge.
При apply/revert — дополнительно отправляет IPC-команду в runtime.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from multiprocess_framework.modules.actions_module.schemas import Action
    from multiprocess_prototype.frontend.bridge.topology_bridge import TopologyBridge

logger = logging.getLogger(__name__)


class FieldSetHandler:
    """Обработчик field_set: применяет/откатывает значение поля через rm.set_field_value().

    Совместим с протоколом ActionHandler (apply/revert).

    Phase 12: если topology_bridge задан, после apply/revert отправляет
    IPC-команду в целевой процесс через bridge.on_field_set().
    """

    def __init__(self, topology_bridge: "TopologyBridge | None" = None) -> None:
        self._bridge = topology_bridge

    def apply(self, action: "Action", rm: Any) -> None:
        """Установить новое значение поля (forward_patch)."""
        register_name = action.register_name
        field_name = action.field_name
        value = action.forward_patch.get("value")

        if not register_name or not field_name:
            logger.warning("field_set apply: register_name или field_name пустые")
            return

        ok, err = rm.set_field_value(register_name, field_name, value)
        if not ok:
            logger.warning(
                "field_set apply failed: %s.%s = %r → %s",
                register_name, field_name, value, err,
            )
            return

        # Phase 12: отправить в runtime через bridge
        self._notify_bridge(register_name, field_name, value)

    def revert(self, action: "Action", rm: Any) -> None:
        """Восстановить предыдущее значение поля (backward_patch)."""
        register_name = action.register_name
        field_name = action.field_name
        value = action.backward_patch.get("value")

        if not register_name or not field_name:
            logger.warning("field_set revert: register_name или field_name пустые")
            return

        ok, err = rm.set_field_value(register_name, field_name, value)
        if not ok:
            logger.warning(
                "field_set revert failed: %s.%s = %r → %s",
                register_name, field_name, value, err,
            )
            return

        # Phase 12: отправить откат в runtime через bridge
        self._notify_bridge(register_name, field_name, value)

    def _notify_bridge(self, register_name: str, field_name: str, value: Any) -> None:
        """Уведомить TopologyBridge об изменении поля (если bridge задан)."""
        if self._bridge is None:
            return
        ok = self._bridge.on_field_set(register_name, field_name, value)
        if not ok:
            logger.debug(
                "field_set bridge notify: %s.%s — bridge отклонил",
                register_name, field_name,
            )
