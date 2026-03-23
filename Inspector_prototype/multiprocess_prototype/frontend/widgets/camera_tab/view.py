# multiprocess_prototype/frontend/widgets/camera_tab/view.py
"""Интерфейс вью для презентера (без Qt в презентере)."""

from __future__ import annotations

from typing import Any, Protocol

from frontend_module.components.tabs import TabViewProtocol


class CameraTabView(TabViewProtocol, Protocol):
    """Методы, которыми презентер обновляет UI."""

    def set_camera_type_combo_index(self, index: int) -> None:
        """Установить индекс QComboBox типа камеры (blockSignals внутри)."""
        ...

    def set_stack_index(self, index: int) -> None:
        """Переключить страницу стека (0=Sim/Web, 1=Hikvision)."""
        ...

    def set_fps_label_text(self, text: str) -> None:
        """Обновить подпись FPS (fallback)."""
        ...

    def get_selected_camera_index(self) -> int:
        """Индекс устройства Hikvision в комбобоксе (0=placeholder)."""
        ...

    def set_devices_list(self, devices: list) -> None:
        """Заполнить комбобокс устройств (display_name)."""
        ...

    def set_hikvision_params_lines(self, params: dict[str, Any]) -> None:
        """Обновить fallback line edits (frame_rate, exposure_time, gain)."""
        ...

    def get_hikvision_params_from_lines(self) -> tuple[float, float, float]:
        """Прочитать triple из fallback line edits (при отсутствии rm)."""
        ...
