"""Camera capture backends: Simulator, Webcam, Hikvision + factory."""

from __future__ import annotations

import os
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np

from multiprocess_prototype_v3.registers.camera import (
    CAMERA_TYPES,
    DEFAULT_CAMERA_TYPE,
    WEBCAM_ENUM_DEFAULT_MAX_INDEX,
    WEBCAM_ENUM_HARD_CAP,
)


class BaseCaptureBackend(ABC):
    @abstractmethod
    def capture_frame(self) -> Optional[np.ndarray]:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass

    def handle_command(self, cmd: str, data: dict) -> Optional[dict]:
        return None


class SimulatorBackend(BaseCaptureBackend):
    def __init__(self, width: int, height: int, image_path: Optional[str] = None):
        from multiprocess_prototype_v3.services.camera.frame_generator import FrameGenerator
        self._generator = FrameGenerator(width, height, image_path=image_path)
        self._running = False

    def capture_frame(self) -> Optional[np.ndarray]:
        return self._generator.generate_frame() if self._running else None

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
    max_index = _coerce_webcam_enum_max(max_index)
    try:
        import cv2
    except ImportError:
        return {"status": "error", "error": "opencv-python not installed", "devices": []}
    devices = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(i)
        if cap.isOpened():
            devices.append({"index": i, "display_name": f"[OpenCV {i}] Webcam", "source": "webcam"})
            cap.release()
    return {"status": "ok", "devices": devices}


def _reset_webcam(device_id: int = 0, delay_after_ms: int = 300) -> None:
    """Reset webcam device (release and re-acquire)."""
    try:
        import cv2
        cap = cv2.VideoCapture(device_id, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(device_id)
        if cap.isOpened():
            cap.release()
        if delay_after_ms > 0:
            time.sleep(delay_after_ms / 1000.0)
    except Exception:
        pass


class WebcamBackend(BaseCaptureBackend):
    """Webcam через OpenCV (DirectShow на Windows).

    Камера НЕ открывается в конструкторе — только в start().
    _open() делает до 3 попыток с задержкой (DirectShow на Windows
    может не отпустить устройство мгновенно после release).
    """

    _OPEN_RETRIES = 3
    _RETRY_DELAY = 0.3  # секунды между попытками

    def __init__(self, width: int, height: int, device_id: int = 0):
        self._width = width
        self._height = height
        self._device_id = device_id
        self._running = False
        self._cap = None

    def _release_cap(self) -> None:
        """Безопасно освободить текущий VideoCapture."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _open(self) -> bool:
        """Открыть камеру. До 3 попыток с задержкой на Windows.

        Returns:
            True если камера открылась.
        """
        # Если уже открыт — ничего не делать
        if self._cap is not None and self._cap.isOpened():
            return True
        # Если cap есть но не открыт — освободить
        self._release_cap()

        try:
            import cv2
        except ImportError:
            return False

        for attempt in range(self._OPEN_RETRIES):
            try:
                self._cap = (
                    cv2.VideoCapture(self._device_id, cv2.CAP_DSHOW)
                    if os.name == "nt"
                    else cv2.VideoCapture(self._device_id)
                )
                if self._cap.isOpened():
                    self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
                    self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
                    return True
                # Не открылся — освободить и попробовать снова
                self._release_cap()
            except RuntimeError:
                self._release_cap()

            if attempt < self._OPEN_RETRIES - 1:
                time.sleep(self._RETRY_DELAY)

        return False

    def capture_frame(self) -> Optional[np.ndarray]:
        if not self._running or not self._cap:
            return None
        ret, frame = self._cap.read()
        return frame if ret else None

    def start(self) -> None:
        opened = self._open()
        self._running = opened

    def stop(self) -> None:
        self._running = False

    def close(self) -> None:
        self._running = False
        self._release_cap()

    def handle_command(self, cmd: str, data: dict) -> Optional[dict]:
        if cmd == "enum_devices":
            return _enum_webcam_devices(data.get("max_index"))
        return None


class HikvisionBackend(BaseCaptureBackend):
    _PIXEL_TYPE_BAYER_RG8 = 17301513

    def __init__(self, camera_index: int, target_width: int, target_height: int,
                 send_to_gui: Callable[[str, dict], None]):
        from hikvision_camera_module import HikvisionCameraFacade
        self._camera_index = camera_index
        self._target_width = target_width
        self._target_height = target_height
        self._send_to_gui = send_to_gui
        self._running = False
        self._facade = HikvisionCameraFacade(
            on_status=lambda t: send_to_gui("status", {"status": t}),
            on_error=lambda t: send_to_gui("error", {"error": t}),
        )

    def _convert_to_rgb(self, frame: np.ndarray, pixel_type: int) -> Optional[np.ndarray]:
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

    def _resize_frame(self, frame: np.ndarray) -> np.ndarray:
        if frame.shape[0] == self._target_height and frame.shape[1] == self._target_width:
            return frame
        try:
            import cv2
            return cv2.resize(frame, (self._target_width, self._target_height), interpolation=cv2.INTER_LINEAR)
        except ImportError:
            return frame

    def capture_frame(self) -> Optional[np.ndarray]:
        if not self._running:
            return None
        frame = self._facade.capture_frame(timeout_ms=1000)
        if frame is None:
            return None
        frame = self._convert_to_rgb(frame, self._facade.last_pixel_type)
        return self._resize_frame(frame) if frame is not None else None

    def start(self) -> None:
        result = self._facade.open(self._camera_index)
        if result.get("status") != "ok":
            self._send_to_gui("error", {"error": "Не удалось открыть камеру Hikvision"})
            self._running = False
            return
        result = self._facade.start_grabbing()
        self._running = result.get("status") == "ok"
        if not self._running:
            self._send_to_gui("error", {"error": "Не удалось начать захват Hikvision"})

    def stop(self) -> None:
        self._running = False
        self._facade.stop_grabbing()

    def close(self) -> None:
        self._running = False
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
            self._running = False
            self._facade.close()
            self._send_to_gui("status", {"status": "Camera closed"})
            return {"status": "ok"}
        if cmd == "start_grabbing":
            self._facade.open(self._camera_index)
            result = self._facade.start_grabbing()
            self._running = result.get("status") == "ok"
            return result
        if cmd == "stop_grabbing":
            self._running = False
            self._facade.stop_grabbing()
            return {"status": "ok"}
        if cmd == "get_parameters":
            r = self._facade.get_parameters()
            if r.get("status") == "ok" and "parameters" in r:
                self._send_to_gui("parameters_response", {"parameters": r["parameters"]})
            return r
        if cmd == "set_parameters":
            fr, exp, gain = data.get("frame_rate"), data.get("exposure_time"), data.get("gain")
            if None in (fr, exp, gain):
                self._send_to_gui("error", {"error": "Missing parameters"})
                return {"status": "error"}
            return self._facade.set_parameters(float(fr), float(exp), float(gain))
        return None


@dataclass
class CameraBackendParams:
    width: int
    height: int
    device_id: int
    camera_index: int
    hikvision_width: int
    hikvision_height: int
    simulator_image_path: Optional[str]
    send_to_gui: Callable[[str, dict], None]


def create_camera_backend(camera_type: str, p: CameraBackendParams) -> BaseCaptureBackend:
    if camera_type not in CAMERA_TYPES:
        camera_type = DEFAULT_CAMERA_TYPE
    if camera_type == "hikvision":
        if sys.platform != "win32":
            p.send_to_gui("status", {"status": "Hikvision only on Windows, using Simulator"})
            return SimulatorBackend(p.width, p.height, image_path=p.simulator_image_path)
        try:
            return HikvisionBackend(p.camera_index, p.hikvision_width, p.hikvision_height, send_to_gui=p.send_to_gui)
        except Exception:
            p.send_to_gui("error", {"error": "Hikvision SDK unavailable, using Simulator"})
            return SimulatorBackend(p.width, p.height, image_path=p.simulator_image_path)
    if camera_type == "webcam":
        return WebcamBackend(p.width, p.height, device_id=p.device_id)
    return SimulatorBackend(p.width, p.height, image_path=p.simulator_image_path)
