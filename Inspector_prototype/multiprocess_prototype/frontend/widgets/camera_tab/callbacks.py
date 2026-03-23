# multiprocess_prototype/frontend/widgets/camera_tab/callbacks.py
"""
Типизированные колбэки вкладки камеры (frozen dataclass вместо dict).

Все колбэки опциональны. from_dict/to_dict — для совместимости с launcher
и GuiCommandHandler, ожидающими dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from frontend_module.components.tabs import (
    tab_callbacks_from_dict,
    tab_callbacks_to_dict,
)


@dataclass(frozen=True)
class CameraTabCallbacks:
    """
    Колбэки отправки команд в backend (GuiCommandHandler).

    Имена полей соответствуют регистрам command_dispatch; None — колбэк не задан.
    """

    on_start: Optional[Callable[[], None]] = None
    on_stop: Optional[Callable[[], None]] = None
    on_set_fps: Optional[Callable[[int], None]] = None
    on_enum_devices: Optional[Callable[[], None]] = None
    on_open: Optional[Callable[..., None]] = None  # ожидает camera_index=...
    on_close: Optional[Callable[[], None]] = None
    on_start_grabbing: Optional[Callable[[], None]] = None
    on_stop_grabbing: Optional[Callable[[], None]] = None
    on_get_parameters: Optional[Callable[[], None]] = None
    on_set_parameters: Optional[Callable[[float, float, float], None]] = None
    on_camera_type_changed: Optional[Callable[[str], None]] = None

    def to_dict(self) -> dict[str, Optional[Callable]]:
        """Для совместимости с кодом, ожидающим словарь."""
        return tab_callbacks_to_dict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CameraTabCallbacks":
        """Собрать из словаря (launcher, legacy)."""
        return tab_callbacks_from_dict(cls, d)
