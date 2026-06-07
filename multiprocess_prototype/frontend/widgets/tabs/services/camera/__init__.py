"""Services «Камера» — подробный фасад настроек вебкамеры (IPC, без cv2).

Управляет работающим плагином camera_service через TopologyBridge (IPC);
actual-параметры читаются из state store. Полный каталог CAP_PROP — из
Plugins/sources/camera_service/backends/webcam_controls.py.
"""

from .section import build_camera_section

__all__ = ["build_camera_section"]
