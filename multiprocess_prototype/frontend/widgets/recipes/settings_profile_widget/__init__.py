"""Панель профилей настроек приложения (Phase 2)."""

from .schemas import SettingsProfileTabConfig

__all__ = ["SettingsProfileTabConfig", "SettingsProfilePanelWidget"]


def __getattr__(name: str):
    """Lazy import для Qt-зависимого виджета (не ломает headless-тесты)."""
    if name == "SettingsProfilePanelWidget":
        from .panel_widget import SettingsProfilePanelWidget

        return SettingsProfilePanelWidget
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
