"""
LegacySyncTrait — синхронизация с ui_elements/controls для совместимости с v1.

Опциональный трейт: при создании передать ui_elements, controls, callback.
Вызывать после успешной записи и при первичной загрузке.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class LegacySyncContext:
    """Контекст legacy-синхронизации (ui_elements, controls, callback, parent)."""

    ui_elements: dict | None = None
    controls: Any = None
    callback: Any = None
    parent_widget: Any | None = None


class LegacySyncTrait:
    """
    Трейт: обновление legacy-словарей и вызов callback после записи.

    Использует publish_control_value_to_observers и publish_legacy_ui_refs.
    """

    def __init__(
        self,
        context: LegacySyncContext,
        registers_manager: Any,
        register_name: str,
        field_name: str,
    ) -> None:
        self._ctx = context
        self._rm = registers_manager
        self._register_name = register_name
        self._field_name = field_name

    def setup_legacy_refs(
        self,
        value: Any,
        element: Any,
        can_modify: bool,
        resolved_meta: Any | None,
    ) -> None:
        """Первичная регистрация в ui_elements/controls (при attach_view)."""
        from frontend_module.components.common.legacy_sync import (
            publish_legacy_ui_refs,
        )

        publish_legacy_ui_refs(
            field_name=self._field_name,
            value=value,
            slider_element=element,
            can_modify=can_modify,
            ui_elements=self._ctx.ui_elements,
            controls=self._ctx.controls,
            resolved_meta=resolved_meta,
        )

    def notify_after_write(self, value: Any) -> None:
        """Вызвать после каждой успешной записи: notify, ui_elements, controls, callback."""
        from frontend_module.components.common.field_sync import (
            publish_control_value_to_observers,
        )

        publish_control_value_to_observers(
            registers_manager=self._rm,
            register_name=self._register_name,
            field_name=self._field_name,
            value=value,
            parent_widget=self._ctx.parent_widget,
            ui_elements=self._ctx.ui_elements,
            controls=self._ctx.controls,
            callback=self._ctx.callback,
        )
