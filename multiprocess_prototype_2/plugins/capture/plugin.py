"""CapturePlugin -- захват кадров с вебкамеры.

Source-плагин: produce() возвращает BGR-кадры.
SHM write и IPC send выполняет GenericProcess (SourceProducer).
Запускается в паузе, ждёт команды start_capture.
"""

from __future__ import annotations

import time

import cv2

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin


@register_plugin("capture", category="source", description="Захват кадров с вебкамеры (cv2)")
class CapturePlugin(ProcessModulePlugin):
    """Захват кадров с вебкамеры через cv2.VideoCapture.

    Lifecycle:
        configure() -- параметры камеры + команды start/stop
        start()     -- auto_start если задан в конфиге
        produce()   -- захват одного кадра (вызывается SourceProducer)
        shutdown()  -- освобождение камеры
    """

    name = "capture"
    category = "source"

    inputs = []
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="BGR-кадр с камеры"),
    ]

    commands = {}

    def configure(self, ctx: PluginContext) -> None:
        """Настройка параметров камеры и команд."""
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)
        self._device_id: int = cfg.get("device_id", 0)
        self._fps: int = cfg.get("fps", 25)
        self._width: int = cfg.get("resolution_width", 640)
        self._height: int = cfg.get("resolution_height", 480)
        self._auto_start: bool = cfg.get("auto_start", False)

        ctx.log_info(
            f"CapturePlugin[{self._camera_id}]: device={self._device_id}, "
            f"{self._width}x{self._height}@{self._fps}fps"
        )

        # Команды start/stop
        def cmd_start_capture(data: dict) -> dict:
            self._start_capture(ctx)
            return {"status": "ok"}

        def cmd_stop_capture(data: dict) -> dict:
            self._stop_capture(ctx)
            return {"status": "ok"}

        ctx.command_manager.register_command("start_capture", cmd_start_capture)
        ctx.command_manager.register_command("stop_capture", cmd_stop_capture)

        # Состояние
        self._cap: cv2.VideoCapture | None = None
        self._is_capturing = False
        self._frame_count = 0
        self._ctx = ctx

    def start(self, ctx: PluginContext) -> None:
        """Auto-start камеры если задан в конфиге."""
        if self._auto_start:
            self._start_capture(ctx)

    def shutdown(self, ctx: PluginContext) -> None:
        """Освобождение камеры."""
        ctx.log_info(f"CapturePlugin[{self._camera_id}]: shutdown...")
        self._is_capturing = False
        self._release_camera()

    def produce(self) -> list[dict]:
        """Захватить один кадр с камеры.

        Возвращает [{"frame": ndarray, "camera_id": int, ...}] или [].
        SHM write и IPC send выполняет SourceProducer.
        """
        if not self._is_capturing or self._cap is None:
            return []

        try:
            ret, frame = self._cap.read()
        except Exception:
            return []

        if not ret or frame is None:
            return []

        # Resize если камера отдаёт другое разрешение
        h, w = frame.shape[:2]
        if w != self._width or h != self._height:
            frame = cv2.resize(frame, (self._width, self._height))

        self._frame_count += 1

        return [{
            "frame": frame,
            "camera_id": self._camera_id,
            "seq_id": self._frame_count,
            "frame_id": self._frame_count,
            "timestamp": time.monotonic(),
            "width": self._width,
            "height": self._height,
            "channels": 3,
            "dtype": "uint8",
        }]

    # --- Внутренние методы ---

    def _start_capture(self, ctx: PluginContext) -> None:
        """Открыть камеру и начать захват."""
        if self._is_capturing:
            return
        self._cap = cv2.VideoCapture(self._device_id, cv2.CAP_DSHOW)
        if self._cap.isOpened():
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
            self._cap.set(cv2.CAP_PROP_FPS, self._fps)
            actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            ctx.log_info(
                f"CapturePlugin[{self._camera_id}]: камера открыта "
                f"(реальное разрешение: {actual_w}x{actual_h})"
            )
            self._is_capturing = True
            ctx.log_info(f"CapturePlugin[{self._camera_id}]: захват запущен")
        else:
            ctx.log_error(
                f"CapturePlugin[{self._camera_id}]: не удалось открыть камеру {self._device_id}"
            )

    def _stop_capture(self, ctx: PluginContext) -> None:
        """Остановить захват."""
        self._is_capturing = False
        self._release_camera()
        ctx.log_info(f"CapturePlugin[{self._camera_id}]: захват остановлен")

    def _release_camera(self) -> None:
        """Освободить камеру."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
