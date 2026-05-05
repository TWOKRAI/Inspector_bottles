"""ColorMaskPlugin — HSV-маска по цвету.

Processing-плагин: получает frame_ready → читает BGR из SHM →
cv2.cvtColor(HSV) → cv2.inRange → записывает маску в SHM → отправляет mask_ready.
Пороги изменяются через команду set_hsv_range (runtime).
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


@register_plugin("color_mask", category="processing", description="HSV-маска по цвету")
class ColorMaskPlugin(ProcessModulePlugin):
    """HSV-маска по цвету с runtime-настройкой порогов."""

    name = "color_mask"
    category = "processing"

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
    ]
    outputs = [
        Port(name="mask", dtype="image/gray", shape="(H, W, 1)", description="Бинарная маска"),
    ]

    commands = {
        "set_hsv_range": "set_hsv_range",
    }

    def configure(self, ctx: PluginContext) -> None:
        """Настройка HSV-параметров и handler."""
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)

        # HSV-диапазон
        self._lower = np.array([
            cfg.get("h_min", 0),
            cfg.get("s_min", 50),
            cfg.get("v_min", 50),
        ], dtype=np.uint8)
        self._upper = np.array([
            cfg.get("h_max", 180),
            cfg.get("s_max", 255),
            cfg.get("v_max", 255),
        ], dtype=np.uint8)

        self._width: int = cfg.get("resolution_width", 640)
        self._height: int = cfg.get("resolution_height", 480)

        self._pending_frame_info: dict | None = None
        self._ctx = ctx

        # Handler для frame_ready
        ctx.router_manager.register_message_handler(
            "frame_ready", self._on_frame_ready
        )

        ctx.log_info(
            f"ColorMaskPlugin[{self._camera_id}]: "
            f"HSV [{self._lower}]-[{self._upper}]"
        )

    def start(self, ctx: PluginContext) -> None:
        """Создать processing worker."""
        from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "mask_worker", self._process_loop, cfg, auto_start=True
        )
        ctx.log_info(f"ColorMaskPlugin[{self._camera_id}]: worker запущен")

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановка."""
        ctx.log_info(f"ColorMaskPlugin[{self._camera_id}]: shutdown")

    # --- Команды ---

    def set_hsv_range(self, data: dict) -> dict:
        """Обновить HSV-диапазон в runtime.

        Args:
            data: {"h_min": 10, "h_max": 90, "s_min": 100, ...}
        """
        if "h_min" in data:
            self._lower[0] = data["h_min"]
        if "h_max" in data:
            self._upper[0] = data["h_max"]
        if "s_min" in data:
            self._lower[1] = data["s_min"]
        if "s_max" in data:
            self._upper[1] = data["s_max"]
        if "v_min" in data:
            self._lower[2] = data["v_min"]
        if "v_max" in data:
            self._upper[2] = data["v_max"]

        self._ctx.log_info(
            f"ColorMaskPlugin[{self._camera_id}]: HSV обновлён "
            f"[{self._lower}]-[{self._upper}]"
        )
        return {"status": "ok", "lower": self._lower.tolist(), "upper": self._upper.tolist()}

    # --- Обработка ---

    def _on_frame_ready(self, msg: dict) -> None:
        """Handler для frame_ready — сохранить info для worker."""
        data = msg.get("data", {})
        if data.get("camera_id") == self._camera_id:
            self._pending_frame_info = data

    def _process_loop(self, stop_event, pause_event) -> None:
        """Цикл: BGR из SHM → HSV mask → SHM → IPC mask_ready."""
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

            # HSV-маска
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, self._lower, self._upper)

            # Записываем маску в SHM (H, W, 1)
            mask_slot = f"mask_{self._camera_id}"
            mask_3d = mask[:, :, np.newaxis]
            mm.write_images(f"camera_{self._camera_id}", mask_slot, [mask_3d], 0)

            # IPC: mask_ready
            self._ctx.io.send_data(
                "renderer",
                "mask_ready",
                {
                    "camera_id": self._camera_id,
                    "shm_name": mask_slot,
                    "shm_index": 0,
                    "frame_shm_name": shm_name,
                    "frame_shm_index": shm_index,
                    "seq_id": info.get("seq_id", 0),
                },
            )
