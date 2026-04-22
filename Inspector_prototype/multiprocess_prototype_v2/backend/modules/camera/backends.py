# multiprocess_prototype_v2/backend/modules/camera/backends.py
"""
Бэкенды захвата кадров: Simulator, Webcam, Hikvision.

Единый интерфейс: capture_frame() -> np.ndarray | None, start(), stop(), close().
HikvisionBackend использует hikvision_camera_module.HikvisionCameraFacade.

Словарь устройства (enum_devices): index, display_name, source ("webcam"|"hikvision"), опционально type/model (Hikvision).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

import numpy as np

from multiprocess_prototype_v2.registers.camera import (
    WEBCAM_ENUM_DEFAULT_MAX_INDEX,
    WEBCAM_ENUM_HARD_CAP,
)


class BaseCaptureBackend(ABC):
    """Базовый класс бэкенда захвата."""

    @abstractmethod
    def capture_frame(self) -> Optional[np.ndarray]:
        """Захватить кадр. None = пропуск (например, нет захвата)."""
        pass

    def start(self) -> None:
        """Начать захват."""
        pass

    def stop(self) -> None:
        """Остановить захват."""
        pass

    def close(self) -> None:
        """Освободить ресурсы."""
        pass

    def handle_command(self, cmd: str, data: dict) -> Optional[dict]:
        """Обработать команду (backend-specific). None = не обработано."""
        return None


class SimulatorBackend(BaseCaptureBackend):
    """Имитация: FrameGenerator."""

    def __init__(self, width: int, height: int, image_path: Optional[str] = None):
        from multiprocess_prototype_v2.utils.frame_generator import FrameGenerator

        self._generator = FrameGenerator(width, height, image_path=image_path)
        self._running = False

    def capture_frame(self) -> Optional[np.ndarray]:
        if not self._running:
            return None
        return self._generator.generate_frame()

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def close(self) -> None:
        self._running = False
        if hasattr(self._generator, "close"):
            self._generator.close()


def _coerce_webcam_enum_max(max_index: Any) -> int:
    try:
        n = int(max_index)
    except (TypeError, ValueError):
        n = WEBCAM_ENUM_DEFAULT_MAX_INDEX
    return max(1, min(n, WEBCAM_ENUM_HARD_CAP))


def _enum_webcam_devices(max_index: int = WEBCAM_ENUM_DEFAULT_MAX_INDEX) -> dict:
    """Перечислить веб-камеры (OpenCV). На Windows — CAP_DSHOW, как в WebcamCapture."""
    max_index = _coerce_webcam_enum_max(max_index)
    try:
        import cv2
    except ImportError:
        return {"status": "error", "error": "opencv-python not installed", "devices": []}
    devices = []
    for i in range(max_index):
        if os.name == "nt":
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(i)
        if cap.isOpened():
            devices.append(
                {
                    "index": i,
                    "display_name": f"[OpenCV {i}] Webcam",
                    "source": "webcam",
                }
            )
            cap.release()
    return {"status": "ok", "devices": devices}


class WebcamBackend(BaseCaptureBackend):
    """Веб-камера: WebcamCapture."""

    def __init__(self, width: int, height: int, device_id: int = 0):
        from multiprocess_prototype_v2.utils.webcam_capture import WebcamCapture

        self._WebcamCapture = WebcamCapture
        self._generator: Optional[WebcamCapture] = None
        self._width = width
        self._height = height
        self._device_id = device_id
        self._running = False
        self._open()

    def _open(self) -> None:
        """Открыть камеру (создать WebcamCapture)."""
        if self._generator is not None:
            return
        try:
            self._generator = self._WebcamCapture(
                self._width, self._height, device_id=self._device_id
            )
        except (ImportError, RuntimeError):
            self._generator = None

    def capture_frame(self) -> Optional[np.ndarray]:
        if not self._running or not self._generator:
            return None
        return self._generator.generate_frame()

    def start(self) -> None:
        self._open()
        self._running = True

    def stop(self) -> None:
        self._running = False

    def close(self) -> None:
        """Закрыть камеру — освободить устройство (гаснет LED)."""
        self._running = False
        if self._generator and hasattr(self._generator, "close"):
            self._generator.close()
        self._generator = None

    def handle_command(self, cmd: str, data: dict) -> Optional[dict]:
        if cmd == "enum_devices":
            return _enum_webcam_devices(data.get("max_index"))
        return super().handle_command(cmd, data)


class HikvisionBackend(BaseCaptureBackend):
    """Hikvision SDK через HikvisionCameraFacade — обёртка над фасадом."""

    _PIXEL_TYPE_BAYER_RG8 = 17301513

    def __init__(
        self,
        camera_index: int,
        target_width: int,
        target_height: int,
        send_to_gui: Callable[[str, dict], None],
    ):
        from hikvision_camera_module import HikvisionCameraFacade

        self._camera_index = camera_index
        self._target_width = target_width
        self._target_height = target_height
        self._send_to_gui = send_to_gui

        def _on_status(text: str):
            send_to_gui("status", {"status": text})

        def _on_error(text: str):
            send_to_gui("error", {"error": text})

        self._facade = HikvisionCameraFacade(on_status=_on_status, on_error=_on_error)

    def _convert_to_rgb(self, frame: np.ndarray, pixel_type: int) -> Optional[np.ndarray]:
        """Сырой кадр → RGB (3 канала)."""
        try:
            import cv2
        except ImportError:
            return frame
        if len(frame.shape) == 2:
            code = cv2.COLOR_BayerRG2RGB if pixel_type == self._PIXEL_TYPE_BAYER_RG8 else cv2.COLOR_GRAY2RGB
            frame = cv2.cvtColor(frame, code)
        elif len(frame.shape) == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2RGB)
        if len(frame.shape) != 3 or frame.shape[2] != 3:
            return None
        return frame

    def _convert_to_bgr(self, frame: np.ndarray, pixel_type: int) -> Optional[np.ndarray]:
        """Сырой кадр → BGR."""
        rgb = self._convert_to_rgb(frame, pixel_type)
        if rgb is None:
            return None
        try:
            import cv2
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        except ImportError:
            return rgb

    def _resize_frame(self, frame: np.ndarray) -> np.ndarray:
        if frame.shape[0] == self._target_height and frame.shape[1] == self._target_width:
            return frame
        try:
            import cv2
            return cv2.resize(
                frame,
                (self._target_width, self._target_height),
                interpolation=cv2.INTER_LINEAR,
            )
        except ImportError:
            return frame

    def capture_frame(self) -> Optional[np.ndarray]:
        frame = self._facade.capture_frame(timeout_ms=1000)
        if frame is None:
            return None
        pixel_type = self._facade.last_pixel_type
        frame = self._convert_to_rgb(frame, pixel_type)
        if frame is None:
            return None
        return self._resize_frame(frame)

    def start(self) -> None:
        self._facade.open(self._camera_index)
        self._facade.start_grabbing()

    def stop(self) -> None:
        self._facade.stop_grabbing()

    def close(self) -> None:
        self._facade.close()

    def handle_command(self, cmd: str, data: dict) -> Optional[dict]:
        if cmd == "enum_devices":
            result = self._facade.enum_devices() or {}
            if isinstance(result, dict) and result.get("status") == "ok":
                for dev in result.get("devices") or []:
                    if isinstance(dev, dict):
                        dev.setdefault("source", "hikvision")
            return result
        if cmd == "open":
            idx = data.get("camera_index", self._camera_index)
            self._camera_index = idx
            return self._facade.open(idx)
        if cmd == "close":
            self._facade.close()
            self._send_to_gui("status", {"status": "Camera closed"})
            return {"status": "ok"}
        if cmd == "start_grabbing":
            self._facade.open(self._camera_index)
            return self._facade.start_grabbing()
        if cmd == "stop_grabbing":
            self._facade.stop_grabbing()
            return {"status": "ok"}
        if cmd == "get_parameters":
            r = self._facade.get_parameters()
            if r.get("status") == "ok" and "parameters" in r:
                self._send_to_gui("parameters_response", {"parameters": r["parameters"]})
            return r
        if cmd == "set_parameters":
            fr = data.get("frame_rate")
            exp = data.get("exposure_time")
            gain = data.get("gain")
            if None in (fr, exp, gain):
                self._send_to_gui("error", {"error": "Missing parameters"})
                return {"status": "error"}
            return self._facade.set_parameters(float(fr), float(exp), float(gain))
        return None
