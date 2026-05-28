"""Табы приложения — реестр всех tab factories для TabFactory.

Функция register_all_tabs() возвращает dict custom_factories
для подстановки в TabFactory.

Task F.9: фабрики принимают (AppServices, RuntimeDeps), не AppContext (Q-F1=B).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget
    from multiprocess_prototype.domain.app_services import AppServices
    from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps


def register_all_tabs() -> dict[str, Callable[["AppServices", "RuntimeDeps"], "QWidget"]]:
    """Зарегистрировать все табы Phase 10.

    Lazy-импорт каждого модуля чтобы избежать circular imports.
    Ключи соответствуют tab_id из TAB_ORDER в tab_factory.py.

    Task F.9: сигнатура фабрик — ``(AppServices, RuntimeDeps) -> QWidget``.
    """
    from .settings import SettingsTab
    from .processes import ProcessesTab
    from .plugins import PluginsTab
    from .services import ServicesTab
    from .displays import DisplaysTab
    from .recipes import RecipesTab
    from .pipeline import PipelineTab

    return {
        "settings": SettingsTab.create,
        "recipes": RecipesTab.create,
        "processes": ProcessesTab.create,
        "services": ServicesTab.create,
        "plugins": PluginsTab.create,
        "pipeline": PipelineTab.create,
        "displays": DisplaysTab.create,
    }
