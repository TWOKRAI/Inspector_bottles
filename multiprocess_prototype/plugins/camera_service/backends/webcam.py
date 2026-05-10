"""WebcamBackend — захват с веб-камеры через OpenCV.

DirectShow на Windows (cv2.CAP_DSHOW).
Retry: до 3 попыток открытия с задержкой 0.3s.
"""

from __future__ import annotations

import os
import sys
import time

import cv2
import numpy as np


def _enum_webcam_devices(max_index: int = 32) -> dict:
    """Перечислить доступные webcam-устройства.

    Перебирает индексы 0..max_index-1, пробует открыть через cv2.VideoCapture.

    Args:
        max_index: максимальный индекс для перебора (по умолчанию 32)

    Returns:
        dict со status и списком devices
    """
    max_index = max(1, min(max_index, 64))
    devices: list[dict] = []

    for i in range(max_index):
        cap = (
            cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if os.name == "nt"
            else cv2.VideoCapture(i)
        )
        if cap.isOpened():
            devices.append({
                "index": i,
                "display_name": f"[OpenCV {i}] Webcam",
                "source": "webcam",
            })
            cap.release()

    return {"status": "ok", "devices": devices}


class WebcamBackend:
    """Backend для USB/встроенных веб-камер через OpenCV.

    Камера НЕ открывается в конструкторе — только в start().
    _open() делает до 3 попыток с задержкой (DirectShow на Windows
    может не отпустить устройство мгновенно после release).
    """

    _OPEN_RETRIES = 3
    _RETRY_DELAY = 0.3  # секунды между попытками

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        device_id: int = 0,
    ) -> None:
        self._width = width
        self._height = height
        self._device_id = device_id
        self._running = False
        self._cap: cv2.VideoCapture | None = None

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

        for attempt in range(self._OPEN_RETRIES):
            try:
                self._cap = (
                    cv2.VideoCapture(self._device_id, cv2.CAP_DSHOW)
                    if sys.platform == "win32"
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

    def capture_frame(self) -> np.ndarray | None:
        """Захватить один кадр. None если камера не готова."""
        if not self._running or self._cap is None:
            return None
        ret, frame = self._cap.read()
        return frame if ret else None

    def start(self) -> None:
        """Открыть камеру и начать захват."""
        opened = self._open()
        self._running = opened

    def stop(self) -> None:
        """Приостановить захват (камера остаётся открытой)."""
        self._running = False

    def close(self) -> None:
        """Полностью освободить камеру."""
        self._running = False
        self._release_cap()

    def handle_command(self, cmd: str, data: dict) -> dict | None:
        """Обработать команду.

        Поддерживает:
            enum_devices — перечислить доступные webcam-устройства
        """
        if cmd == "enum_devices":
            max_idx = data.get("max_index", 32)
            return _enum_webcam_devices(max_idx)
        return None
