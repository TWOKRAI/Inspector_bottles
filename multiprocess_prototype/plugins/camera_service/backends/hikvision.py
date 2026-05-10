"""HikvisionBackend — захват с промышленных камер Hikvision (MVS SDK).

Lazy import: hikvision_camera_module загружается только при создании экземпляра.
Работает только на Windows (sys.platform == "win32").
"""

from __future__ import annotations

import sys

import cv2
import numpy as np

# Проверяем доступность SDK при импорте модуля
_HAS_SDK = False
try:
    from hikvision_camera_module import HikvisionCameraFacade  # noqa: F401
    _HAS_SDK = True
except ImportError:
    pass

# Константа pixel type для Bayer RG8 (из MVS SDK)
_PIXEL_TYPE_BAYER_RG8 = 17301513


class HikvisionBackend:
    """Backend для промышленных камер Hikvision через MVS SDK.

    Требования:
        - Windows (sys.platform == "win32")
        - hikvision_camera_module установлен

    Raises:
        ImportError: если SDK не установлен
        RuntimeError: если платформа не Windows
    """

    def __init__(
        self,
        camera_index: int = 0,
        target_width: int = 1920,
        target_height: int = 1080,
    ) -> None:
        # Проверка платформы
        if sys.platform != "win32":
            raise RuntimeError(
                "HikvisionBackend поддерживается только на Windows"
            )

        # Проверка SDK
        if not _HAS_SDK:
            raise ImportError(
                "hikvision_camera_module не установлен. "
                "Установите SDK для работы с камерами Hikvision."
            )

        from hikvision_camera_module import HikvisionCameraFacade

        self._camera_index = camera_index
        self._target_width = target_width
        self._target_height = target_height
        self._running = False

        self._facade = HikvisionCameraFacade(
            on_status=lambda t: None,
            on_error=lambda t: None,
        )

    def _convert_to_rgb(
        self, frame: np.ndarray, pixel_type: int
    ) -> np.ndarray | None:
        """Конвертировать кадр в RGB.

        Обрабатывает Bayer RG8, grayscale, RGBA форматы.
        """
        if len(frame.shape) == 2:
            # Одноканальный — Bayer или grayscale
            code = (
                cv2.COLOR_BayerRG2RGB
                if pixel_type == _PIXEL_TYPE_BAYER_RG8
                else cv2.COLOR_GRAY2RGB
            )
            frame = cv2.cvtColor(frame, code)
        elif len(frame.shape) == 3 and frame.shape[2] == 4:
            # RGBA → RGB
            frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2RGB)

        # Проверка: должен быть 3-канальный
        if len(frame.shape) != 3 or frame.shape[2] != 3:
            return None
        return frame

    def _resize_frame(self, frame: np.ndarray) -> np.ndarray:
        """Привести кадр к целевому разрешению."""
        if (
            frame.shape[0] == self._target_height
            and frame.shape[1] == self._target_width
        ):
            return frame
        return cv2.resize(
            frame,
            (self._target_width, self._target_height),
            interpolation=cv2.INTER_LINEAR,
        )

    def capture_frame(self) -> np.ndarray | None:
        """Захватить один кадр с камеры Hikvision."""
        if not self._running:
            return None
        frame = self._facade.capture_frame(timeout_ms=1000)
        if frame is None:
            return None
        frame = self._convert_to_rgb(frame, self._facade.last_pixel_type)
        if frame is None:
            return None
        return self._resize_frame(frame)

    def start(self) -> None:
        """Открыть камеру и начать захват."""
        result = self._facade.open(self._camera_index)
        if result.get("status") != "ok":
            self._running = False
            return
        result = self._facade.start_grabbing()
        self._running = result.get("status") == "ok"

    def stop(self) -> None:
        """Остановить захват."""
        self._running = False
        self._facade.stop_grabbing()

    def close(self) -> None:
        """Полностью закрыть камеру и освободить ресурсы."""
        self._running = False
        self._facade.close()

    def handle_command(self, cmd: str, data: dict) -> dict | None:
        """Обработать команду Hikvision.

        Поддерживаемые команды:
            enum_devices, open, close, start_grabbing, stop_grabbing,
            get_parameters, set_parameters
        """
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
            return self._facade.get_parameters()

        if cmd == "set_parameters":
            fr = data.get("frame_rate")
            exp = data.get("exposure_time")
            gain = data.get("gain")
            if None in (fr, exp, gain):
                return {"status": "error", "error": "Не хватает параметров"}
            return self._facade.set_parameters(float(fr), float(exp), float(gain))

        return None
