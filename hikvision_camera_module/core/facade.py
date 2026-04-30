# -*- coding: utf-8 -*-
"""
HikvisionCameraFacade — простой синхронный фасад для Hikvision SDK.

Объединяет capture + parameters. Callbacks on_status, on_error опциональны.
Методы open_sdk_window/close_sdk_window — запуск оригинального окна SDK.
"""

import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from hikvision_camera_module.interfaces import IHikvisionCameraFacade
from hikvision_camera_module.core.capture import HikvisionCapture, enum_devices
from hikvision_camera_module.core.parameters import get_parameters, set_parameters


class HikvisionCameraFacade(IHikvisionCameraFacade):
    """
    Фасад Hikvision камеры. Простой синхронный API.
    """

    def __init__(
        self,
        on_status: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self._capture = HikvisionCapture(on_status=on_status, on_error=on_error)
        self._sdk_process: Optional[subprocess.Popen] = None

    def enum_devices(self) -> Dict[str, Any]:
        return enum_devices()

    def open(self, camera_index: int = 0) -> Dict[str, Any]:
        ok = self._capture.open(camera_index)
        return {"status": "ok" if ok else "error"}

    def close(self) -> Dict[str, Any]:
        self._capture.close()
        return {"status": "ok"}

    def start_grabbing(self) -> Dict[str, Any]:
        ok = self._capture.start_grabbing()
        return {"status": "ok" if ok else "error"}

    def stop_grabbing(self) -> Dict[str, Any]:
        self._capture.stop_grabbing()
        return {"status": "ok"}

    def capture_frame(self, timeout_ms: int = 1000) -> Optional[Any]:
        return self._capture.capture_frame(timeout_ms=timeout_ms)

    @property
    def last_pixel_type(self) -> int:
        """Последний pixel_type кадра (для cv2-конвертации)."""
        return self._capture.last_pixel_type

    def get_parameters(self) -> Dict[str, Any]:
        return get_parameters(self._capture.camera)

    def set_parameters(
        self,
        frame_rate: float,
        exposure_time: float,
        gain: float,
    ) -> Dict[str, Any]:
        return set_parameters(
            self._capture.camera,
            frame_rate,
            exposure_time,
            gain,
        )

    def open_sdk_window(self) -> Dict[str, Any]:
        """Открыть окно оригинального SDK (Clean Camera Test)."""
        if self._sdk_process is not None and self._sdk_process.poll() is None:
            return {"status": "ok", "message": "SDK window already running"}
        try:
            _root = Path(__file__).resolve().parent.parent.parent  # Inspector_bottles (project root)
            cmd = [
                sys.executable,
                "-m",
                "hikvision_camera_module",
            ]
            self._sdk_process = subprocess.Popen(
                cmd,
                cwd=str(_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {"status": "ok", "message": "SDK window started"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def close_sdk_window(self) -> Dict[str, Any]:
        """Закрыть окно оригинального SDK."""
        if self._sdk_process is None:
            return {"status": "ok", "message": "No SDK window was running"}
        try:
            self._sdk_process.terminate()
            self._sdk_process.wait(timeout=5)
        except Exception:
            try:
                self._sdk_process.kill()
            except Exception:
                pass
        finally:
            self._sdk_process = None
        return {"status": "ok"}
