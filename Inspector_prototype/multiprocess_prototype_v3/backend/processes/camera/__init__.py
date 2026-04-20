"""Процесс camera — инфраструктурный контейнер для CameraService."""

from multiprocess_prototype_v3.backend.processes.camera.process import CameraProcess

__all__ = ["CameraProcess"]
