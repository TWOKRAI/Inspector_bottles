"""SettingsTab — таб «Настройки» (BaseTreeNavTab + 9 секций). ADR-126.

Task D.5: мигрирован на AppServices DI. Принимает services: AppServices как
основной параметр. auth_ctx передаётся отдельно — AuthContext содержит manager/state/audit,
которые не покрыты AuthFacade Protocol (Phase E расширит Protocol).
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

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext
    from multiprocess_prototype.frontend.auth_context import AuthContext


def _layout_factory() -> DiffScrollTabLayout:
    return DiffScrollTabLayout(title="Настройки", action_width=160, nav_width=230)


class SettingsTab(BaseTreeNavTab):
    """Таб «Настройки» — 9 секций через BaseTreeNavTab.

    Task D.5: принимает AppServices вместо AppContext. auth_ctx отдельно —
    admin-панели используют AuthContext (manager+state+audit), которые выходят
    за рамки минимального AuthFacade Protocol из domain. Phase E расширит
    AuthFacade или введёт отдельный AdminAuthContext Protocol.
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
        # ActionBus получаем из services.commands если оно поддерживает action_bus,
        # иначе bus=None (graceful degradation для тестов).
        bus = getattr(services.commands, "action_bus", None)
        if callable(bus):
            bus = bus()

        # Сохраняем ДО super().__init__, т.к. _make_presenter() вызывается
        # внутри BaseTreeNavTab.__init__ и требует self._services.
        self._services = services

        super().__init__(
            title="Настройки",
            sections=build_settings_sections(services, auth_ctx=auth_ctx),
            ctx=None,  # type: ignore[arg-type]  # BaseTreeNavTab legacy параметр
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
    def create_from_services(
        cls,
        services: AppServices,
        *,
        auth_ctx: "AuthContext | None" = None,
    ) -> "SettingsTab":
        """Создать SettingsTab из AppServices (основной factory-метод Phase D+)."""
        return cls(services, auth_ctx=auth_ctx)

    @classmethod
    def create(cls, ctx: "AppContext") -> "SettingsTab":
        """Адаптер для register_all_tabs() / TabFactory — принимает AppContext.

        Task D.5: AppServices из ctx.app_services. auth_ctx из ctx.auth.
        Если ctx.app_services is None — AssertionError с диагностикой.

        Phase E заменит AppContext на AppServices напрямую в register_all_tabs().
        """
        assert ctx.app_services is not None, (  # type: ignore[union-attr]
            "AppServices не инициализирован в ctx. Убедитесь что Task D.1 factory вызван в run_gui()."
        )
        return cls(ctx.app_services, auth_ctx=ctx.auth)  # type: ignore[union-attr]

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
