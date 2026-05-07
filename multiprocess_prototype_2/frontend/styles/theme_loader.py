"""theme_loader — загрузка и применение темы оформления для v2."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from multiprocess_framework.modules.frontend_module.managers.theme_manager import ThemeManager

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

_STYLES_DIR = Path(__file__).resolve().parent


def create_theme_manager() -> ThemeManager:
    """Создать ThemeManager с путём к v2 styles/."""
    return ThemeManager(_STYLES_DIR)


def apply_default_theme(app: "QApplication") -> None:
    """Применить дефолтную тему innotech_theme к QApplication."""
    tm = create_theme_manager()
    tm.apply_theme("innotech_theme")
