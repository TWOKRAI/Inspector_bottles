"""webcam_camera — минимальный сервис веб-камеры для ServiceRegistry.

Shell-реализация под IService Protocol (Phase 3).
Полный бэкенд с захватом кадров, SHM и Hikvision — Phase 6.

Пример использования:
    from Services.webcam_camera import WebcamCameraService

    svc = WebcamCameraService()
    svc.start({"device_id": 0})
    status = svc.get_status()   # {"name": "webcam_camera", "status": "running", ...}
    svc.stop()
"""

from __future__ import annotations

from Services.webcam_camera.service import WebcamCameraService

__all__ = ["WebcamCameraService"]
