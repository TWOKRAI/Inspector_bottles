"""CapturePlugin — захват кадров с вебкамеры.

Самодостаточный плагин (source): cv2.VideoCapture → SHM ring-buffer → IPC frame_ready.
Демонстрирует мощный плагин: SHM, ring buffer, middleware, worker.
"""

from __future__ import annotations

import time

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin
from multiprocess_framework.modules.router_module.middleware import FrameShmMiddleware
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig
from multiprocess_prototype.backend.shm.ring_buffer import RingBufferWriter


@register_plugin("capture", category="source", description="Захват кадров с вебкамеры (cv2)")
class CapturePlugin(ProcessModulePlugin):
    """Захват кадров с вебкамеры через cv2.VideoCapture.

    configure(): ring buffer + SHM middleware + команды
    start(): создание capture_worker (loop, paused)
    shutdown(): остановка камеры, очистка SHM
    """

    name = "capture"
    category = "source"

    # Порты: source — нет входов, один выход (кадр BGR)
    inputs = []
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="BGR-кадр с камеры"),
    ]

    # Команды
    commands = {
        "start_capture": "start_capture",
        "stop_capture": "stop_capture",
    }

    def configure(self, ctx: PluginContext) -> None:
        """Настройка SHM, middleware, команд."""
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)
        self._device_id: int = cfg.get("device_id", 0)
        self._fps: int = cfg.get("fps", 25)
        self._width: int = cfg.get("resolution_width", 640)
        self._height: int = cfg.get("resolution_height", 480)
        ring_buffer_size: int = cfg.get("ring_buffer_size", 3)

        shm_owner = f"camera_{self._camera_id}"
        shm_slot = f"camera_{self._camera_id}_frame"

        ctx.log_info(
            f"CapturePlugin[{self._camera_id}]: device={self._device_id}, "
            f"{self._width}x{self._height}@{self._fps}fps, K={ring_buffer_size}"
        )

        # Ring-buffer (round-robin по K SHM-слотам)
        self._ring_buffer = RingBufferWriter(
            ctx.memory_manager,
            owner=shm_owner,
            slot_prefix=shm_slot,
            k=ring_buffer_size,
        )

        # SHM middleware для отправки кадров
        self._frame_mw = FrameShmMiddleware(
            ctx.memory_manager, owner=shm_owner, slot=shm_slot
        )
        ctx.router_manager.add_send_middleware(self._frame_mw.on_send)

        # Команды
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
        """Создать capture_worker (стартует в паузе — ждёт start_capture)."""
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "capture_worker", self._capture_loop, cfg, auto_start=False
        )
        ctx.worker_manager.pause_worker("capture_worker")
        ctx.log_info(f"CapturePlugin[{self._camera_id}]: worker создан (paused)")

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановка камеры и очистка SHM."""
        ctx.log_info(f"CapturePlugin[{self._camera_id}]: shutdown...")
        if ctx.worker_manager:
            ctx.worker_manager.pause_worker("capture_worker")
        self._release_camera()
        if ctx.memory_manager:
            ctx.memory_manager.close_all(f"camera_{self._camera_id}")

    # --- Внутренние методы ---

    def _start_capture(self, ctx: PluginContext) -> None:
        """Открыть камеру и начать захват."""
        if self._is_capturing:
            return
        self._cap = cv2.VideoCapture(self._device_id)
        if self._cap.isOpened():
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
            self._cap.set(cv2.CAP_PROP_FPS, self._fps)
            self._is_capturing = True
            if not ctx.worker_manager.is_worker_running("capture_worker"):
                ctx.worker_manager.start_worker("capture_worker")
            ctx.worker_manager.resume_worker("capture_worker")
            ctx.log_info(f"CapturePlugin[{self._camera_id}]: захват запущен")
        else:
            ctx.log_error(f"CapturePlugin[{self._camera_id}]: не удалось открыть камеру {self._device_id}")

    def _stop_capture(self, ctx: PluginContext) -> None:
        """Остановить захват."""
        if ctx.worker_manager:
            ctx.worker_manager.pause_worker("capture_worker")
        self._is_capturing = False
        self._release_camera()
        ctx.log_info(f"CapturePlugin[{self._camera_id}]: захват остановлен")

    def _release_camera(self) -> None:
        """Освободить камеру."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _capture_loop(self, stop_event, pause_event) -> None:
        """Основной цикл захвата: cv2.read → SHM → IPC frame_ready."""
        frame_interval = 1.0 / max(self._fps, 1)

        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            if self._cap is None or not self._cap.isOpened():
                time.sleep(0.1)
                continue

            t0 = time.monotonic()
            ret, frame = self._cap.read()

            if not ret or frame is None:
                time.sleep(0.01)
                continue

            # Resize если камера отдаёт другое разрешение
            h, w = frame.shape[:2]
            if w != self._width or h != self._height:
                frame = cv2.resize(frame, (self._width, self._height))

            # Запись в SHM ring-buffer
            slot_index, seq_id = self._ring_buffer.write(frame)
            self._frame_count += 1

            # IPC: уведомить processor
            shm_slot = f"camera_{self._camera_id}_frame"
            self._ctx.io.send_data(
                f"processor_{self._camera_id}",
                "frame_ready",
                {
                    "camera_id": self._camera_id,
                    "shm_name": shm_slot,
                    "shm_index": slot_index,
                    "seq_id": seq_id,
                    "frame_id": self._frame_count,
                    "timestamp": t0,
                },
            )

            # FPS throttle
            elapsed = time.monotonic() - t0
            if elapsed < frame_interval:
                time.sleep(frame_interval - elapsed)
