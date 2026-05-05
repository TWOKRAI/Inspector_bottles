"""RegionSplitPlugin — нарезка кадра на регионы с fan-out.

Получает frame_ready → читает BGR из SHM → нарезает на N регионов (ROI) →
записывает каждый в отдельный SHM-слот → отправляет region_ready каждому target-процессу.

Логика safe-clamp ROI взята из multiprocess_prototype/services/processor/operations/roi/region_splitter_op.py.
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


@register_plugin("region_split", category="processing", description="Нарезка кадра на регионы + fan-out")
class RegionSplitPlugin(ProcessModulePlugin):
    """Нарезка кадра на регионы с отправкой каждого в свой процесс."""

    name = "region_split"
    category = "processing"

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
    ]
    outputs = [
        Port(name="region", dtype="image/bgr", shape="(H, W, 3)", description="Вырезанный регион"),
    ]

    commands = {}

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: регионы из конфига, handler для frame_ready."""
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)
        self._regions: list[dict] = cfg.get("regions", [])
        self._default_region: dict | None = cfg.get("default_region")

        self._pending_frame_info: dict | None = None
        self._ctx = ctx

        # Регистрация handler
        ctx.router_manager.register_message_handler(
            "frame_ready", self._on_frame_ready
        )

        region_names = [r["name"] for r in self._regions]
        if self._default_region:
            region_names.append(self._default_region["name"])

        ctx.log_info(
            f"RegionSplitPlugin[{self._camera_id}]: configured "
            f"regions={region_names}"
        )

    def start(self, ctx: PluginContext) -> None:
        """Создать processing worker."""
        from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "region_split_worker", self._process_loop, cfg, auto_start=True
        )
        ctx.log_info(f"RegionSplitPlugin[{self._camera_id}]: worker запущен")

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановка."""
        ctx.log_info(f"RegionSplitPlugin[{self._camera_id}]: shutdown")

    # --- Обработка ---

    def _on_frame_ready(self, msg: dict) -> None:
        """Handler для frame_ready."""
        data = msg.get("data", {})
        if data.get("camera_id") == self._camera_id:
            self._pending_frame_info = data

    def _process_loop(self, stop_event, pause_event) -> None:
        """Цикл: читает кадр → нарезает регионы → fan-out по targets."""
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

            canvas_h, canvas_w = frame.shape[:2]
            seq_id = info.get("seq_id", 0)
            frame_id = info.get("frame_id", 0)
            timestamp = info.get("timestamp", time.monotonic())
            owner = f"camera_{self._camera_id}"

            # Нарезка регионов (логика safe-clamp из RegionSplitterOp)
            for r in self._regions:
                self._split_and_send(
                    frame, r, owner, canvas_w, canvas_h,
                    seq_id, frame_id, timestamp, mm
                )

            # Default region — полный кадр
            if self._default_region:
                default_name = self._default_region["name"]
                default_target = self._default_region.get("target", "stitcher")
                slot_name = f"{default_name}_{self._camera_id}"

                shm_actual = mm.write_images(owner, slot_name, [frame.copy()], 0)

                out_data = {
                    "region_name": default_name,
                    "shm_name": slot_name,
                    "shm_index": 0,
                    "shm_owner": owner,
                    "shm_actual_name": shm_actual,
                    "width": canvas_w,
                    "height": canvas_h,
                    "channels": 3,
                    "original_x": 0,
                    "original_y": 0,
                    "original_width": canvas_w,
                    "original_height": canvas_h,
                    "canvas_width": canvas_w,
                    "canvas_height": canvas_h,
                    "seq_id": seq_id,
                    "frame_id": frame_id,
                    "timestamp": timestamp,
                    "camera_id": self._camera_id,
                }
                self._ctx.io.send_data(default_target, "region_ready", out_data)

    def _split_and_send(
        self, frame: np.ndarray, region: dict, owner: str,
        canvas_w: int, canvas_h: int,
        seq_id: int, frame_id: int, timestamp: float,
        mm,
    ) -> None:
        """Вырезать регион из кадра и отправить в target-процесс."""
        name = region["name"]
        target = region.get("target", "stitcher")
        x, y = int(region["x"]), int(region["y"])
        w, h = int(region["width"]), int(region["height"])

        # Safe-clamp к границам кадра (из RegionSplitterOp)
        H, W = frame.shape[:2]
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(W, x + w), min(H, y + h)

        if x2 <= x1 or y2 <= y1:
            self._ctx.log_info(f"RegionSplitPlugin: регион {name} вне кадра, пропускаем")
            return

        crop = frame[y1:y2, x1:x2].copy()

        # Записываем в SHM
        slot_name = f"{name}_{self._camera_id}"
        shm_actual = mm.write_images(owner, slot_name, [crop], 0)

        # Отправляем region_ready с метаданными координат
        out_data = {
            "region_name": name,
            "shm_name": slot_name,
            "shm_index": 0,
            "shm_owner": owner,
            "shm_actual_name": shm_actual,
            "width": x2 - x1,
            "height": y2 - y1,
            "channels": 3,
            # Метаданные координат для stitcher
            "original_x": x1,
            "original_y": y1,
            "original_width": x2 - x1,
            "original_height": y2 - y1,
            "canvas_width": canvas_w,
            "canvas_height": canvas_h,
            "seq_id": seq_id,
            "frame_id": frame_id,
            "timestamp": timestamp,
            "camera_id": self._camera_id,
        }
        self._ctx.io.send_data(target, "region_ready", out_data)
