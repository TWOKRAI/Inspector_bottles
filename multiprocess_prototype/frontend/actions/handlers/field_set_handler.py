"""FieldSetHandler — apply/revert изменения поля регистра через RegistersManager.

Phase 12: опциональная интеграция с TopologyBridge.
При apply/revert — дополнительно отправляет IPC-команду в runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from multiprocess_framework.modules.logger_module import get_logger

if TYPE_CHECKING:
    from multiprocess_framework.modules.actions_module.schemas import Action
    from multiprocess_prototype.frontend.bridge.topology_bridge import TopologyBridge


def _log(msg: str, level: str = "info") -> None:
    """Записать в LoggerManager (если инициализирован), иначе тихо.

    module="trace" — диагностические сообщения уходят в logs/<proc>/trace.log
    (см. LoggerManagerConfig.modules["trace"]) плюс в scope-каналы.
    """
    lm = get_logger()
    if lm is None:
        return
    getattr(lm, level)(msg, module="trace")


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

        _log(f"[trace field_set] apply: {register_name}.{field_name} = {value!r} (bridge={self._bridge is not None})")

        if not register_name or not field_name:
            _log("field_set apply: register_name или field_name пустые", level="warning")
            return

        ok, err = rm.set_field_value(register_name, field_name, value)
        if not ok:
            _log(
                f"field_set apply failed: {register_name}.{field_name} = {value!r} → {err}",
                level="warning",
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
            _log("field_set revert: register_name или field_name пустые", level="warning")
            return

        ok, err = rm.set_field_value(register_name, field_name, value)
        if not ok:
            _log(
                f"field_set revert failed: {register_name}.{field_name} = {value!r} → {err}",
                level="warning",
            )
            return

        # Phase 12: отправить откат в runtime через bridge
        self._notify_bridge(register_name, field_name, value)

    def _notify_bridge(self, register_name: str, field_name: str, value: Any) -> None:
        """Уведомить TopologyBridge об изменении поля (если bridge задан)."""
        if self._bridge is None:
            _log("[trace field_set] _notify_bridge: bridge is None — IPC не отправляется")
            return
        ok = self._bridge.on_field_set(register_name, field_name, value)
        _log(f"[trace field_set] bridge.on_field_set({register_name}.{field_name}, {value!r}) → {ok!r}")
