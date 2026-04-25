# multiprocess_prototype_v3/frontend/widgets/camera_tab/view.py
"""Протокол вью вкладки камеры: только то, что нужно презентеру (без Qt-импортов в презентере)."""

from __future__ import annotations

from typing import Protocol

from multiprocess_framework.modules.frontend_module.widgets.tabs import TabViewProtocol


class CameraTabView(TabViewProtocol, Protocol):
    """Вью: индекс ComboBox и стека страниц камеры + multi-camera UI."""

    def set_stack_index(self, index: int) -> None:
        """Переключить QStackedWidget."""
        ...

    def set_combo_index(self, index: int, *, block_signals: bool = False) -> None:
        """Установить индекс QComboBox; block_signals — без рекурсии в on_camera_type_changed."""
        ...

    # --- Multi-camera UI (Task 3.10) ---

    def set_camera_status_text(self, text: str, color: str) -> None:
        """Обновить текст и цвет статуса выбранной камеры."""
        ...

    def set_camera_fps_text(self, text: str) -> None:
        """Обновить текст FPS выбранной камеры."""
        ...

    def set_camera_drops_text(self, text: str) -> None:
        """Обновить текст счётчика дропов выбранной камеры."""
        ...

    def populate_camera_selector(self, items: list[str], *, block_signals: bool = False) -> None:
        """Заполнить camera selector списком камер из реестра."""
        ...

    def set_camera_selector_index(self, index: int, *, block_signals: bool = False) -> None:
        """Установить выбранную камеру в camera selector."""
        ...
