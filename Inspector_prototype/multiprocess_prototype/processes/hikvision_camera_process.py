# multiprocess_prototype/processes/hikvision_camera_process.py
"""
HikvisionCameraProcess — legacy-обёртка над HikvisionCameraProcessAdapter.

Вся логика в hikvision_camera_module. Этот файл сохранён для обратной совместимости.
"""

from hikvision_camera_module import HikvisionCameraProcessAdapter

# Алиас для обратной совместимости
HikvisionCameraProcess = HikvisionCameraProcessAdapter

__all__ = ["HikvisionCameraProcess", "HikvisionCameraProcessAdapter"]
