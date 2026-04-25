# multiprocess_prototype_v3/frontend/widgets/settings_tab/prefs_store.py
"""Persistence режима отображения вкладок через QSettings.

view_mode -- это user preference (а не свойство рецепта/алгоритма),
поэтому хранится отдельно от app_aggregate, чтобы не дублировать в каждом YAML-слоте.
"""

from __future__ import annotations

# QSettings нет в frontend_module.qt_imports (он редко используется) -- импорт напрямую
from PySide6.QtCore import QSettings

_ORG = "Inspector"
_APP = "ui_preferences"

KEY_SETTINGS_MODE = "settings/view_mode"
KEY_RECIPES_MODE = "recipes/view_mode"


def _settings() -> QSettings:
    return QSettings(_ORG, _APP)


def get_view_mode(key: str, default: int = 0) -> int:
    """Прочитать сохранённый режим (0=карточки, 1=таблица). Безопасный fallback."""
    raw = _settings().value(key, default)
    try:
        mode = int(raw)
    except (TypeError, ValueError):
        return default
    return mode if mode in (0, 1) else default


def set_view_mode(key: str, mode: int) -> None:
    """Сохранить режим. Допустимые значения: 0 / 1."""
    if mode not in (0, 1):
        return
    _settings().setValue(key, int(mode))
