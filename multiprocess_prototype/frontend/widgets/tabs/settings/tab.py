"""SettingsTab — таб «Настройки» (BaseTreeNavTab + 9 секций). ADR-126."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import BaseTreeNavTab, TreeNavTabPresenter
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import DiffScrollTabLayout

from ._sections import build_settings_sections
from .presenter import SettingsPresenter

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


def _layout_factory() -> DiffScrollTabLayout:
    return DiffScrollTabLayout(title="Настройки", action_width=160, nav_width=230)


class SettingsTab(BaseTreeNavTab):
    """Таб «Настройки» — 9 секций через BaseTreeNavTab."""

    settings_saved = Signal(dict)
    dirty_changed = Signal(bool)

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        bus = ctx.action_bus()
        super().__init__(
            title="Настройки",
            sections=build_settings_sections(ctx),
            ctx=ctx,
            layout_factory=_layout_factory,
            bus_change_subscriber=(lambda cb: bus.add_change_callback(cb)) if bus else None,
            parent=parent,
        )
        self.enable_undo_redo(bus)
        self.section_dirty_changed.connect(self._on_section_dirty)
        self.section_data_saved.connect(self._on_section_saved)
        self.populate()
        dashboard = self._presenter.section("admin_dashboard")
        if dashboard is not None:
            nav_sig = getattr(dashboard.widget(), "navigate_to", None)
            if nav_sig is not None:
                nav_sig.connect(self._presenter.navigate_to)

    @classmethod
    def create(cls, ctx: "AppContext") -> "SettingsTab":
        return cls(ctx)

    def _tree_object_name(self) -> str:
        return "SettingsTreeNav"

    def _make_presenter(self) -> TreeNavTabPresenter:
        return SettingsPresenter(view=self, rm=None, ui=None, ctx=self._ctx)

    def _on_section_dirty(self, key: str, dirty: bool) -> None:
        if key == "system_settings":
            self.dirty_changed.emit(dirty)

    def _on_section_saved(self, key: str, data: dict) -> None:
        if key == "system_settings":
            self.settings_saved.emit(data)
