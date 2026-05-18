# -*- coding: utf-8 -*-
"""SettingsPresenter — app-specific обёртка над TreeNavTabPresenter.

Только undo/redo через ActionBus. Конфигурация секций — в _sections.py,
универсальная навигация — в TreeNavTabPresenter.

См. ADR-126.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from multiprocess_framework.modules.frontend_module.widgets.tabs import (
    TreeNavTabPresenter,
)

from .view import SettingsView

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


class SettingsPresenter(TreeNavTabPresenter[SettingsView, None]):
    """Презентер таба Settings — undo/redo подписан на ActionBus."""

    def __init__(
        self,
        *,
        view: SettingsView,
        rm=None,
        ui=None,
        ctx: "AppContext",
    ) -> None:
        super().__init__(view=view, rm=rm, ui=ui)
        self._ctx = ctx

    def on_bus_change(self) -> None:
        """Обновить состояние кнопок Undo/Redo по текущему ActionBus."""
        bus = self._ctx.action_bus()
        if bus is None:
            return
        layout = getattr(self._view, "_layout", None)
        if layout is None:
            return
        undo_btn = getattr(layout, "undo_button", None)
        redo_btn = getattr(layout, "redo_button", None)
        if undo_btn is not None:
            undo_btn.setEnabled(bus.can_undo())
        if redo_btn is not None:
            redo_btn.setEnabled(bus.can_redo())
