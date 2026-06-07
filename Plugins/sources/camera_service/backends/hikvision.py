"""HikvisionBackend — захват с промышленных камер Hikvision (MVS SDK).

Использует пакет Services.hikvision_camera: core state-machine ``HikvisionCamera``
+ ``FrameConverter`` (raw→BGR). Lazy import — SDK/пакет могут отсутствовать.
Работает только на Windows (sys.platform == "win32").
"""

from __future__ import annotations

import sys

import numpy as np

# Доступность пакета hikvision_camera (DLL MVS проверяется отдельно — см. HikvisionCamera.sdk_available)
_HAS_PKG = False
try:
    from Services.hikvision_camera.core.camera import HikvisionCamera
    from Services.hikvision_camera.core.converter import FrameConverter
    from Services.hikvision_camera.core.discovery import enum_devices
    from Services.hikvision_camera.core.parameters import (
        CameraParameters,
        get_parameters,
        set_parameters,
    )

    _HAS_PKG = True
except ImportError:
    pass


class HikvisionBackend:
    """Backend для промышленных камер Hikvision через MVS SDK.

    Требования:
        - Windows (sys.platform == "win32")
        - пакет Services.hikvision_camera импортируется (а для реального
          захвата — установлен MVS SDK / MvCameraControl.dll)

    Raises:
        RuntimeError: если платформа не Windows
        ImportError: если пакет hikvision_camera недоступен
    """

    def __init__(
        self,
        camera_index: int = 0,
        target_width: int = 1920,
        target_height: int = 1080,
    ) -> None:
        if sys.platform != "win32":
            raise RuntimeError("HikvisionBackend поддерживается только на Windows")
        if not _HAS_PKG:
            raise ImportError(
                "Пакет Services.hikvision_camera недоступен. Проверьте установку MVS SDK и доступность пакета."
            )

        self._camera_index = camera_index
        self._target_width = target_width
        self._target_height = target_height
        self._running = False
        self._camera = HikvisionCamera()

    # --- Capture lifecycle ---

    def start(self) -> None:
        """Открыть камеру и начать захват."""
        if not self._camera.open(self._camera_index):
            self._running = False
            return
        self._running = self._camera.start_grabbing()

    def stop(self) -> None:
        """Остановить захват (камера остаётся открытой)."""
        self._running = False
        self._camera.stop_grabbing()

    def close(self) -> None:
        """Полностью закрыть камеру и освободить ресурсы."""
        self._running = False
        self._camera.close()

    def capture_frame(self) -> np.ndarray | None:
        """Захватить один кадр с камеры Hikvision (BGR, 3 канала)."""
        if not self._running:
            return None
        raw_frame, pixel_type = self._camera.capture_frame(timeout_ms=1000)
        if raw_frame is None:
            return None
        bgr = FrameConverter.to_bgr(raw_frame, pixel_type)
        if bgr is None:
            return None
        return FrameConverter.resize(bgr, self._target_width, self._target_height)

    # --- Команды (enum/параметры) ---

    def handle_command(self, cmd: str, data: dict) -> dict | None:
        """Обработать команду Hikvision.

        Поддерживаемые команды:
            enum_devices, open, close, start_grabbing, stop_grabbing,
            get_parameters, set_parameters
        """
        if cmd == "enum_devices":
            devices = []
            for dev in enum_devices():
                d = dev.to_dict() if hasattr(dev, "to_dict") else {}
                d.setdefault("source", "hikvision")
                devices.append(d)
            return {"status": "ok", "devices": devices}

        if cmd == "open":
            idx = data.get("camera_index", self._camera_index)
            self._camera_index = idx
            ok = self._camera.open(idx)
            return {"status": "ok" if ok else "error"}

        if cmd == "close":
            self.close()
            return {"status": "ok"}

        if cmd == "start_grabbing":
            self.start()
            return {"status": "ok" if self._running else "error"}

        if cmd == "stop_grabbing":
            self.stop()
            return {"status": "ok"}

        if cmd == "get_parameters":
            handle = self._camera._camera
            params = get_parameters(handle) if handle is not None else None
            if params is None:
                return {"status": "error", "error": "Параметры недоступны (камера закрыта?)"}
            return {
                "status": "ok",
                "frame_rate": params.frame_rate,
                "exposure_time": params.exposure_time,
                "gain": params.gain,
            }

        if cmd == "set_parameters":
            fr = data.get("frame_rate")
            exp = data.get("exposure_time")
            gain = data.get("gain")
            handle = self._camera._camera
            if None in (fr, exp, gain) or handle is None:
                return {"status": "error", "error": "Не хватает параметров или камера закрыта"}
            ok = set_parameters(handle, CameraParameters(float(fr), float(exp), float(gain)))
            return {"status": "ok" if ok else "error"}

        return None
