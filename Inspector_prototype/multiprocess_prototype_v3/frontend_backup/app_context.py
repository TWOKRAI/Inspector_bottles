"""Frontend application context — dependency container for tabs and windows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class FrontendAppContext:
    """Dependency snapshot for tab widget factory."""

    config: Dict[str, Any]
    registers_manager: Optional[Any]
    camera_callbacks_map: Dict[str, Any]
    camera_type: str
    recipe_manager: Optional[Any] = None
    command_handler: Optional[Any] = None
    extras: Dict[str, Any] = field(default_factory=dict)

    def get_camera_tab_ui(self) -> Any:
        return self.config.get("camera_tab")

    def get_processing_tab_ui(self) -> Any:
        return self.config.get("processing_tab_ui")

    def get_touch_keyboard(self) -> Any:
        return self.config.get("touch_keyboard")
