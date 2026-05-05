"""ResizePlugin — масштабирование BGR-кадра.

Получает frame_ready → читает BGR из SHM → cv2.resize → записывает в SHM → отправляет frame_ready.
Логика ресайза взята из multiprocess_prototype/services/processor/operations/preprocess/resize_op.py.
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

# Маппинг интерполяции (из ResizeOp)
_INTERP_MAP: dict[str, int] = {
    "nearest": cv2.INTER_NEAREST,
    "linear": cv2.INTER_LINEAR,
    "cubic": cv2.INTER_CUBIC,
    "area": cv2.INTER_AREA,
}


@register_plugin("resize", category="processing", description="Масштабирование BGR-кадра")
class ResizePlugin(ProcessModulePlugin):
    """Масштабирование кадра. Processing-плагин."""

    name = "resize"
    category = "processing"

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Масштабированный BGR-кадр"),
    ]

    commands = {}

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: handler для frame_ready, параметры ресайза."""
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)
        self._scale_factor: float = cfg.get("scale_factor", 1.0)
        self._target_width: int = cfg.get("target_width", 0)
        self._target_height: int = cfg.get("target_height", 0)
        self._interp_str: str = cfg.get("interpolation", "linear")
        self._interp: int = _INTERP_MAP.get(self._interp_str, cv2.INTER_LINEAR)

        # Routing targets
        self._frame_targets: list[str] = cfg.get("frame_targets") or [f"processor_{self._camera_id}"]

        self._pending_frame_info: dict | None = None
        self._ctx = ctx

        # Регистрация handler
        ctx.router_manager.register_message_handler(
            "frame_ready", self._on_frame_ready
        )

        ctx.log_info(
            f"ResizePlugin[{self._camera_id}]: configured "
            f"scale={self._scale_factor}, target={self._target_width}x{self._target_height}, "
            f"interp={self._interp_str}"
        )

    def start(self, ctx: PluginContext) -> None:
        """Создать processing worker."""
        from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "resize_worker", self._process_loop, cfg, auto_start=True
        )
        ctx.log_info(f"ResizePlugin[{self._camera_id}]: worker запущен")

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановка."""
        ctx.log_info(f"ResizePlugin[{self._camera_id}]: shutdown")

    # --- Обработка ---

    def _on_frame_ready(self, msg: dict) -> None:
        """Handler для frame_ready — сохранить info для worker."""
        data = msg.get("data", {})
        if data.get("camera_id") == self._camera_id:
            self._pending_frame_info = data

    def _process_loop(self, stop_event, pause_event) -> None:
        """Цикл: читает BGR из SHM → resize → записывает в SHM → IPC."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            if self._pending_frame_info is None:
                time.sleep(0.01)
                continue

            info = self._pending_frame_info
            self._pending_frame_info = None

            # Читаем кадр из SHM
            shm_name = info.get("shm_name", f"camera_{self._camera_id}_frame")
            shm_index = info.get("shm_index", 0)

            mm = self._ctx.memory_manager
            if mm is None:
                continue

            frame = mm.read_images(f"camera_{self._camera_id}", shm_name, shm_index)
            if frame is None:
                continue

            # Вычисляем target size
            if self._target_width > 0 and self._target_height > 0:
                new_w, new_h = self._target_width, self._target_height
            else:
                h, w = frame.shape[:2]
                new_w = max(1, int(w * self._scale_factor))
                new_h = max(1, int(h * self._scale_factor))

            # Resize (логика из ResizeOp)
            resized = cv2.resize(frame, (new_w, new_h), interpolation=self._interp)

            # Записываем в SHM
            slot_name = f"resized_{self._camera_id}"
            shm_actual = mm.write_images(f"camera_{self._camera_id}", slot_name, [resized], 0)

            # IPC: отправить frame_ready в targets
            out_data = {
                "camera_id": self._camera_id,
                "shm_name": slot_name,
                "shm_index": 0,
                "shm_actual_name": shm_actual,
                "width": new_w,
                "height": new_h,
                "channels": 3,
                "dtype": "uint8",
                "seq_id": info.get("seq_id", 0),
                "frame_id": info.get("frame_id", 0),
                "timestamp": info.get("timestamp", time.monotonic()),
            }
            for target in self._frame_targets:
                self._ctx.io.send_data(target, "frame_ready", out_data)
