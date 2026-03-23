# multiprocess_prototype/frontend/widgets/camera_common/
"""
Simulator / Webcam: схема UI, секция FPS, виджет SimWebcamWidget (MVP).

Два экземпляра SimWebcamWidget с разным camera_type_id в стеке вкладки камеры;
фактический тип — поле camera_type в регистре (переключатель ComboBox).
"""

from .callbacks import SimWebcamWidgetCallbacks, build_sim_webcam_callbacks
from .fps_section import FpsFallbackWidgets, add_fps_section_to_layout
from .schemas import SimWebcamUiConfig
from .widget import CameraTypeId, SimWebcamWidget

__all__ = [
    "CameraTypeId",
    "FpsFallbackWidgets",
    "SimWebcamUiConfig",
    "SimWebcamWidget",
    "SimWebcamWidgetCallbacks",
    "add_fps_section_to_layout",
    "build_sim_webcam_callbacks",
]
