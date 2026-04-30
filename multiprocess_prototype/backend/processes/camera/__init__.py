"""Процесс camera — инфраструктурный контейнер для CameraService."""

from multiprocess_prototype.backend.processes.camera.process import CameraProcess

__all__ = ["CameraProcess"]
