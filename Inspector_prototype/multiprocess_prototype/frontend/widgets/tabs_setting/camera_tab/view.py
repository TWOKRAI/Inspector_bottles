# multiprocess_prototype/frontend/widgets/camera_tab/view.py
"""Протокол вью вкладки камеры: только то, что нужно презентеру (без Qt-импортов в презентере)."""

from __future__ import annotations

from typing import Protocol

from frontend_module.widgets.tabs import TabViewProtocol


class CameraTabView(TabViewProtocol, Protocol):
    """Вью: индекс ComboBox и стека страниц камеры."""

    def set_stack_index(self, index: int) -> None:
        """Переключить QStackedWidget."""
        ...

    def set_combo_index(self, index: int, *, block_signals: bool = False) -> None:
        """Установить индекс QComboBox; block_signals — без рекурсии в on_camera_type_changed."""
        ...
