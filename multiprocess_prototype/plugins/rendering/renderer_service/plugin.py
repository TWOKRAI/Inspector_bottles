"""RenderPlugin — наложение маски на кадр.

Output-плагин: получает mask_ready → читает кадр + маску из SHM →
cv2.addWeighted overlay → записывает результат в SHM → отправляет render_ready.
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
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig


@register_plugin("render", category="output", description="Наложение маски на кадр (overlay)")
class RenderPlugin(ProcessModulePlugin):
    """Наложение маски на кадр. Output-плагин."""

    name = "render"
    category = "output"

    # Порты: два входа (кадр + маска) → один выход (результат)
    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Исходный кадр"),
        Port(name="mask", dtype="image/gray", shape="(H, W, 1)", description="Маска для наложения"),
    ]
    outputs = [
        Port(name="result", dtype="image/bgr", shape="(H, W, 3)", description="Кадр с наложенной маской"),
    ]

    def configure(self, ctx: PluginContext) -> None:
        """Настройка параметров overlay."""
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)
        self._alpha: float = cfg.get("mask_alpha", 0.5)
        self._mask_color = np.array([
            cfg.get("mask_color_b", 0),
            cfg.get("mask_color_g", 255),
            cfg.get("mask_color_r", 0),
        ], dtype=np.uint8)

        self._width: int = cfg.get("resolution_width", 640)
        self._height: int = cfg.get("resolution_height", 480)

        self._pending_mask_info: dict | None = None
        self._ctx = ctx

        ctx.log_info(
            f"RenderPlugin[{self._camera_id}]: alpha={self._alpha}, "
            f"color=BGR({self._mask_color})"
        )

    def start(self, ctx: PluginContext) -> None:
        """Создать render worker."""
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "render_worker", self._render_loop, cfg, auto_start=True
        )
        ctx.log_info(f"RenderPlugin[{self._camera_id}]: worker запущен")

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановка."""
        ctx.log_info(f"RenderPlugin[{self._camera_id}]: shutdown")

    # --- Рендеринг ---

    def _render_loop(self, stop_event, pause_event) -> None:
        """Основной цикл: кадр + маска → overlay → результат в SHM."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            # Проверяем входящие сообщения
            msg = self._ctx.receive_message(timeout=0.01, channel_types=["data"])
            if msg:
                from multiprocess_prototype.backend.helpers import message_as_dict
                msg_dict = message_as_dict(msg)
                data_type = msg_dict.get("data_type")
                if data_type == "mask_ready":
                    data = msg_dict.get("data", {})
                    if data.get("camera_id") == self._camera_id:
                        self._pending_mask_info = data

            if self._pending_mask_info is None:
                continue

            info = self._pending_mask_info
            self._pending_mask_info = None

            mm = self._ctx.memory_manager
            if mm is None:
                continue

            owner = f"camera_{self._camera_id}"

            # Читаем оригинальный кадр
            frame_shm = info.get("frame_shm_name", f"camera_{self._camera_id}_frame")
            frame_idx = info.get("frame_shm_index", 0)
            frame = mm.read_images(owner, frame_shm, frame_idx)
            if frame is None:
                continue

            # Читаем маску
            mask_shm = info.get("shm_name", f"mask_{self._camera_id}")
            mask_idx = info.get("shm_index", 0)
            mask_raw = mm.read_images(owner, mask_shm, mask_idx)
            if mask_raw is None:
                continue

            # Маска может быть (H, W, 1) — сжимаем до (H, W)
            if mask_raw.ndim == 3 and mask_raw.shape[2] == 1:
                mask = mask_raw[:, :, 0]
            else:
                mask = mask_raw

            # Overlay: цветная маска поверх кадра
            overlay = frame.copy()
            color_mask = np.zeros_like(frame)
            color_mask[:] = self._mask_color
            overlay[mask > 0] = cv2.addWeighted(
                frame[mask > 0], 1.0 - self._alpha,
                color_mask[mask > 0], self._alpha,
                0,
            )

            # Записываем результат в SHM
            render_slot = f"render_{self._camera_id}"
            mm.write_images(owner, render_slot, [overlay], 0)

            # IPC: уведомить GUI
            self._ctx.io.send_data(
                "gui",
                "render_ready",
                {
                    "camera_id": self._camera_id,
                    "shm_name": render_slot,
                    "shm_index": 0,
                    "seq_id": info.get("seq_id", 0),
                },
            )
