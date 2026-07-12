"""Табы приложения — реестр tab factories для TabFactory.

NEW-D1 (D-4): состав вкладок больше не хардкодится здесь вторым списком —
``register_all_tabs()`` деривится из единого источника ``TABS``
(``multiprocess_prototype.frontend.tabs_registry``). Ключи = tab_id, значения =
фабрики ``(AppServices, RuntimeDeps) -> QWidget``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from multiprocess_prototype.domain.app_services import AppServices
    from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps


def register_all_tabs() -> dict[str, Callable[["AppServices", "RuntimeDeps"], "QWidget"]]:
    """Вернуть dict ``{tab_id: factory}`` — derived из единого источника TABS."""
    from multiprocess_prototype.frontend.tabs_registry import TABS

    return {spec.id: spec.factory for spec in TABS if spec.factory is not None}
