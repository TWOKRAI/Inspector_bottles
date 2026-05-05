"""GrayscalePlugin — BGR → Grayscale.

Processing-плагин: получает frame_ready или region_ready → читает BGR из SHM →
cv2.cvtColor(GRAY) → записывает результат в SHM → отправляет дальше.

Поддерживает два режима:
1. Standalone: frame_ready → frame_ready (target из конфига)
2. Region pipeline: region_ready → region_processed (с пробросом метаданных координат)
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


@register_plugin("grayscale", category="processing", description="Конвертация BGR → Grayscale")
class GrayscalePlugin(ProcessModulePlugin):
    """Конвертация BGR → Grayscale. Processing-плагин с поддержкой region pipeline."""

    name = "grayscale"
    category = "processing"

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Grayscale-кадр (BGR 3ch для совместимости)"),
    ]

    commands = {}

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: handler для frame_ready и region_ready, SHM параметры."""
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)
        self._width: int = cfg.get("resolution_width", 640)
        self._height: int = cfg.get("resolution_height", 480)
        self._target: str = cfg.get("target", "renderer")

        # Режим работы: region_mode если есть target и не "renderer"
        self._region_mode: bool = cfg.get("target") is not None and cfg.get("target") != "renderer"

        self._pending_frame_info: dict | None = None
        self._ctx = ctx

        # Регистрация handler для frame_ready (всегда)
        ctx.router_manager.register_message_handler(
            "frame_ready", self._on_frame_ready
        )

        # Регистрация handler для region_ready (для region pipeline)
        ctx.router_manager.register_message_handler(
            "region_ready", self._on_region_ready
        )

        ctx.log_info(
            f"GrayscalePlugin[{self._camera_id}]: configured "
            f"{self._width}x{self._height}, target={self._target}, "
            f"region_mode={self._region_mode}"
        )

    def start(self, ctx: PluginContext) -> None:
        """Создать processing worker."""
        from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "grayscale_worker", self._process_loop, cfg, auto_start=True
        )
        ctx.log_info(f"GrayscalePlugin[{self._camera_id}]: worker запущен")

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановка."""
        ctx.log_info(f"GrayscalePlugin[{self._camera_id}]: shutdown")

    # --- Обработка ---

    def _on_frame_ready(self, msg: dict) -> None:
        """Handler для frame_ready — сохранить info для worker."""
        data = msg.get("data", {})
        if data.get("camera_id") == self._camera_id:
            data["_msg_type"] = "frame_ready"
            self._pending_frame_info = data

    def _on_region_ready(self, msg: dict) -> None:
        """Handler для region_ready — сохранить info для worker (region pipeline)."""
        data = msg.get("data", {})
        data["_msg_type"] = "region_ready"
        self._pending_frame_info = data

    def _process_loop(self, stop_event, pause_event) -> None:
        """Цикл: читает BGR из SHM → grayscale → записывает в SHM → IPC."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            if self._pending_frame_info is None:
                time.sleep(0.01)
                continue

            info = self._pending_frame_info
            self._pending_frame_info = None

            # Определяем режим по типу входящего сообщения
            is_region = info.pop("_msg_type", "frame_ready") == "region_ready"

            # Читаем кадр из SHM
            shm_name = info.get("shm_name", f"camera_{self._camera_id}_frame")
            shm_index = info.get("shm_index", 0)
            owner = info.get("shm_owner", f"camera_{self._camera_id}")

            mm = self._ctx.memory_manager
            if mm is None:
                continue

            frame = mm.read_images(owner, shm_name, shm_index)
            if frame is None:
                continue

            # BGR → Grayscale → BGR (3 канала для совместимости с stitcher)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray_bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

            # Записываем в SHM
            gray_slot = f"gray_{self._camera_id}"
            shm_actual = mm.write_images(owner, gray_slot, [gray_bgr], 0)

            if is_region:
                # Region pipeline: отправляем region_processed с метаданными координат
                out_data = {
                    "region_name": info.get("region_name", "unknown"),
                    "shm_name": gray_slot,
                    "shm_index": 0,
                    "shm_owner": owner,
                    "shm_actual_name": shm_actual,
                    "width": info.get("width", gray_bgr.shape[1]),
                    "height": info.get("height", gray_bgr.shape[0]),
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
            else:
                # Standalone: отправляем frame_ready
                self._ctx.io.send_data(
                    self._target,
                    "frame_ready",
                    {
                        "camera_id": self._camera_id,
                        "shm_name": gray_slot,
                        "shm_index": 0,
                        "seq_id": info.get("seq_id", 0),
                        "frame_id": info.get("frame_id", 0),
                        "timestamp": info.get("timestamp", time.monotonic()),
                        "dtype": "gray",
                    },
                )
