"""NegativePlugin — инверсия цвета BGR-кадра.

Получает region_ready → читает BGR из SHM → 255 - frame → записывает в SHM → отправляет region_processed.
Пробрасывает метаданные координат для stitcher.
"""

from __future__ import annotations

import time

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin


@register_plugin("negative", category="processing", description="Инверсия цвета (негатив)")
class NegativePlugin(ProcessModulePlugin):
    """Инверсия цвета: 255 - frame. Processing-плагин для region pipeline."""

    name = "negative"
    category = "processing"

    inputs = [
        Port(name="region", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-регион"),
    ]
    outputs = [
        Port(name="region", dtype="image/bgr", shape="(H, W, 3)", description="Инвертированный BGR-регион"),
    ]

    commands = {}

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: handler для region_ready."""
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)
        self._target: str = cfg.get("target", "stitcher")

        self._pending_region_info: dict | None = None
        self._ctx = ctx

        # Слушаем region_ready от region_splitter
        ctx.router_manager.register_message_handler(
            "region_ready", self._on_region_ready
        )

        ctx.log_info(f"NegativePlugin[{self._camera_id}]: configured, target={self._target}")

    def start(self, ctx: PluginContext) -> None:
        """Создать processing worker."""
        from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "negative_worker", self._process_loop, cfg, auto_start=True
        )
        ctx.log_info(f"NegativePlugin[{self._camera_id}]: worker запущен")

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановка."""
        ctx.log_info(f"NegativePlugin[{self._camera_id}]: shutdown")

    # --- Обработка ---

    def _on_region_ready(self, msg: dict) -> None:
        """Handler для region_ready — сохранить info для worker."""
        data = msg.get("data", {})
        self._pending_region_info = data

    def _process_loop(self, stop_event, pause_event) -> None:
        """Цикл: читает BGR из SHM → инвертирует → записывает в SHM → IPC."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            if self._pending_region_info is None:
                time.sleep(0.01)
                continue

            info = self._pending_region_info
            self._pending_region_info = None

            # Читаем регион из SHM
            shm_name = info.get("shm_name")
            shm_index = info.get("shm_index", 0)
            owner = info.get("shm_owner", f"camera_{self._camera_id}")

            mm = self._ctx.memory_manager
            if mm is None:
                continue

            frame = mm.read_images(owner, shm_name, shm_index)
            if frame is None:
                continue

            # Инверсия: 255 - frame
            negative = np.asarray(255 - frame, dtype=np.uint8)

            # Записываем в SHM
            slot_name = f"negative_{self._camera_id}"
            shm_actual = mm.write_images(owner, slot_name, [negative], 0)

            # Пробрасываем все метаданные координат + обновляем shm
            out_data = {
                "region_name": info.get("region_name", "unknown"),
                "shm_name": slot_name,
                "shm_index": 0,
                "shm_owner": owner,
                "shm_actual_name": shm_actual,
                "width": info.get("width", negative.shape[1]),
                "height": info.get("height", negative.shape[0]),
                "channels": 3,
                # Метаданные координат — пробрасываем без изменений
                "original_x": info.get("original_x", 0),
                "original_y": info.get("original_y", 0),
                "original_width": info.get("original_width", 0),
                "original_height": info.get("original_height", 0),
                "canvas_width": info.get("canvas_width", 0),
                "canvas_height": info.get("canvas_height", 0),
                "seq_id": info.get("seq_id", 0),
                "frame_id": info.get("frame_id", 0),
                "timestamp": info.get("timestamp", time.monotonic()),
                "camera_id": self._camera_id,
            }

            self._ctx.io.send_data(self._target, "region_processed", out_data)
