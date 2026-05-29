"""SettingsTab — таб «Настройки» (BaseTreeNavTab + 9 секций). ADR-126.

Task D.5: мигрирован на AppServices DI. Принимает services: AppServices.
Task F.9: create() принимает (services, runtime: RuntimeDeps) — Q-F1=B.
auth_ctx передаётся через RuntimeDeps.auth_ctx.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from multiprocess_framework.modules.frontend_module.widgets.tabs import BaseTreeNavTab, TreeNavTabPresenter
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import DiffScrollTabLayout
from multiprocess_prototype.domain.app_services import AppServices

from ._sections import build_settings_sections
from .presenter import SettingsPresenter

from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.auth_context import AuthContext


def _layout_factory() -> DiffScrollTabLayout:
    return DiffScrollTabLayout(title="Настройки", action_width=160, nav_width=230)


class SettingsTab(BaseTreeNavTab):
    """Таб «Настройки» — 9 секций через BaseTreeNavTab.

    Task D.5: принимает AppServices вместо AppContext.
    Task F.9: create(services, runtime) — Q-F1=B. auth_ctx через RuntimeDeps.
    """

    settings_saved = Signal(dict)
    dirty_changed = Signal(bool)

    def __init__(
        self,
        services: AppServices,
        *,
        auth_ctx: "AuthContext | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        # G.4.4: undo/redo на domain CommandDispatcher (services.commands
        # удовлетворяет UndoRedoController). Единая глобальная история; кнопки
        # рефрешат enabled-состояние по change-callback после dispatch/undo/redo.
        commands = services.commands

        # Сохраняем ДО super().__init__, т.к. _make_presenter() вызывается
        # внутри BaseTreeNavTab.__init__ и требует self._services.
        self._services = services

        super().__init__(
            title="Настройки",
            sections=build_settings_sections(services, auth_ctx=auth_ctx),
            ctx=None,  # type: ignore[arg-type]  # framework generic-слот, прототип не использует ctx
            layout_factory=_layout_factory,
            bus_change_subscriber=lambda cb: commands.add_change_callback(cb),
            parent=parent,
        )
        self.enable_undo_redo(commands)
        self.section_dirty_changed.connect(self._on_section_dirty)
        self.section_data_saved.connect(self._on_section_saved)
        self.populate()
        dashboard = self._presenter.section("admin_dashboard")
        if dashboard is not None:
            nav_sig = getattr(dashboard.widget(), "navigate_to", None)
            if nav_sig is not None:
                nav_sig.connect(self._presenter.navigate_to)

    @classmethod
    def create_from_services(
        cls,
        services: AppServices,
        *,
        auth_ctx: "AuthContext | None" = None,
    ) -> "SettingsTab":
        """Создать SettingsTab из AppServices (основной factory-метод Phase D+)."""
        return cls(services, auth_ctx=auth_ctx)

    @classmethod
    def create(
        cls,
        services: AppServices,
        runtime: RuntimeDeps = RuntimeDeps(),
    ) -> "SettingsTab":
        """Фабричный метод для register_all_tabs() / TabFactory.

        Task F.9: принимает AppServices + RuntimeDeps (Q-F1=B).
        auth_ctx берётся из runtime.auth_ctx.
        """
        return cls(services, auth_ctx=runtime.auth_ctx)

    def _tree_object_name(self) -> str:
        return "SettingsTreeNav"

    def _make_presenter(self) -> TreeNavTabPresenter:
        return SettingsPresenter(view=self, rm=None, ui=None, services=self._services)

    def _on_section_dirty(self, key: str, dirty: bool) -> None:
        if key == "system_settings":
            self.dirty_changed.emit(dirty)

    def _on_section_saved(self, key: str, data: dict) -> None:
        if key == "system_settings":
            self.settings_saved.emit(data)
