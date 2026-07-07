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

from . import webcam_controls as controls


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
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(i)
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
        fps: int | None = None,
        mjpg: bool = False,
        params: dict | None = None,
    ) -> None:
        self._width = width
        self._height = height
        self._device_id = device_id
        self._fps = fps
        self._mjpg = mjpg
        # Желаемые значения управляемых параметров (desired) — переживают
        # переоткрытие устройства и применяются заново в _open().
        self._params: dict = dict(params or {})
        self._running = False
        self._cap: cv2.VideoCapture | None = None

    def _release_cap(self) -> None:
        """Безопасно освободить текущий VideoCapture."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # no-health: defensive release на cleanup/shutdown, устройство уже отпускается
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
                    # Порядок критичен: MJPG(FOURCC) → width/height → fps →
                    # остальные параметры. См. webcam_controls.apply_open_sequence.
                    controls.apply_open_sequence(
                        self._cap,
                        mjpg=self._mjpg,
                        width=self._width,
                        height=self._height,
                        fps=self._fps,
                        params=self._params,
                    )
                    return True
                # Не открылся — освободить и попробовать снова
                self._release_cap()
            except RuntimeError:  # no-health: retry-петля открытия (DSHOW не отпустил устройство), отказ виден по start()→_running=False
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

    # --- Live-управление параметрами (через control-core) ---

    def set_param(self, name: str, value) -> bool:
        """Применить управляемый параметр live и запомнить как desired.

        Запоминается даже если cap не открыт — применится при следующем _open().
        """
        self._params[name] = value
        return controls.apply_param(self._cap, name, value)

    def set_mjpg(self, on: bool) -> bool:
        """Переключить MJPG-кодек. Запоминается как desired для переоткрытия."""
        self._mjpg = bool(on)
        return controls.set_mjpg(self._cap, on)

    def set_fps(self, fps: int) -> bool:
        """Применить целевой FPS live (cap.set FPS). Запоминается как desired."""
        self._fps = int(fps)
        if self._cap is None:
            return False
        try:
            return bool(self._cap.set(cv2.CAP_PROP_FPS, int(fps)))
        except Exception:  # no-health: best-effort cap.set, отказ возвращается вызывателю как False
            return False

    def get_actual(self, names: list[str] | None = None) -> dict:
        """Прочитать actual-значения (что камера реально применила)."""
        return controls.read_actual(self._cap, names)

    def handle_command(self, cmd: str, data: dict) -> dict | None:
        """Обработать команду.

        Поддерживает:
            enum_devices — перечислить доступные webcam-устройства
            set_param    — применить параметр (data: name, value)
            set_mjpg     — переключить MJPG (data: on)
            get_actual   — прочитать actual-значения (data: names опц.)
        """
        if cmd == "enum_devices":
            max_idx = data.get("max_index", 32)
            return _enum_webcam_devices(max_idx)
        if cmd == "set_param":
            ok = self.set_param(data.get("name", ""), data.get("value"))
            return {"status": "ok" if ok else "error", "applied": ok}
        if cmd == "set_mjpg":
            ok = self.set_mjpg(bool(data.get("on", True)))
            return {"status": "ok" if ok else "error", "applied": ok}
        if cmd == "get_actual":
            return {"status": "ok", "actual": self.get_actual(data.get("names"))}
        return None
