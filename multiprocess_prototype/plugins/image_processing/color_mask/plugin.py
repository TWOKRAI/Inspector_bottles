"""ColorMaskPlugin — HSV-маска по цвету.

Простой processing-плагин: получает frame_ready → читает кадр из SHM →
cv2.cvtColor(HSV) → cv2.inRange → записывает маску в SHM → отправляет mask_ready.
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


@register_plugin("color_mask", category="processing", description="HSV-маска по цвету")
class ColorMaskPlugin(ProcessModulePlugin):
    """HSV-маска по цвету. Простой processing-плагин."""

    name = "color_mask"
    category = "processing"

    # Порты: вход (BGR-кадр) → выход (маска + статистика)
    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной кадр"),
    ]
    outputs = [
        Port(name="mask", dtype="image/gray", shape="(H, W, 1)", description="Бинарная маска"),
        Port(name="stats", dtype="dict", optional=True, description="Статистика маски"),
    ]

    commands = {
        "set_hsv_range": "set_hsv_range",
    }

    def configure(self, ctx: PluginContext) -> None:
        """Настройка HSV-параметров и data-handler."""
        cfg = ctx.config
        self._camera_id: int = cfg.get("camera_id", 0)

        # HSV-диапазон
        self._lower = np.array([
            cfg.get("h_min", 0),
            cfg.get("s_min", 50),
            cfg.get("v_min", 50),
        ])
        self._upper = np.array([
            cfg.get("h_max", 180),
            cfg.get("s_max", 255),
            cfg.get("v_max", 255),
        ])

        self._width: int = cfg.get("resolution_width", 640)
        self._height: int = cfg.get("resolution_height", 480)

        # Последний полученный кадр (для обработки в worker)
        self._pending_frame_info: dict | None = None
        self._ctx = ctx

        # Регистрация data-handler для frame_ready
        ctx.router_manager.register_message_handler(
            "frame_ready", self._on_frame_ready
        )

        ctx.log_info(
            f"ColorMaskPlugin[{self._camera_id}]: "
            f"HSV [{self._lower}]-[{self._upper}]"
        )

    def start(self, ctx: PluginContext) -> None:
        """Создать processing worker."""
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "mask_worker", self._process_loop, cfg, auto_start=True
        )
        ctx.log_info(f"ColorMaskPlugin[{self._camera_id}]: worker запущен")

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановка worker."""
        ctx.log_info(f"ColorMaskPlugin[{self._camera_id}]: shutdown")

    # --- Команды ---

    def set_hsv_range(self, **kwargs) -> None:
        """Обновить HSV-диапазон."""
        if "h_min" in kwargs:
            self._lower[0] = kwargs["h_min"]
        if "h_max" in kwargs:
            self._upper[0] = kwargs["h_max"]
        if "s_min" in kwargs:
            self._lower[1] = kwargs["s_min"]
        if "s_max" in kwargs:
            self._upper[1] = kwargs["s_max"]
        if "v_min" in kwargs:
            self._lower[2] = kwargs["v_min"]
        if "v_max" in kwargs:
            self._upper[2] = kwargs["v_max"]

    # --- Обработка ---

    def _on_frame_ready(self, msg: dict) -> None:
        """Handler для frame_ready — сохранить info для worker."""
        data = msg.get("data", {})
        if data.get("camera_id") == self._camera_id:
            self._pending_frame_info = data

    def _process_loop(self, stop_event, pause_event) -> None:
        """Основной цикл: читает кадр из SHM → HSV mask → записывает маску."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            # Проверяем входящие сообщения
            msg = self._ctx.receive_message(timeout=0, channel_types=["data"])
            if msg:
                from multiprocess_prototype.backend.helpers import message_as_dict
                msg_dict = message_as_dict(msg)
                data_type = msg_dict.get("data_type")
                if data_type == "frame_ready":
                    data = msg_dict.get("data", {})
                    if data.get("camera_id") == self._camera_id:
                        self._pending_frame_info = data

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

            frame = mm.read_images(
                f"camera_{self._camera_id}", shm_name, shm_index
            )
            if frame is None:
                continue

            # HSV-маска
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, self._lower, self._upper)

            # Записываем маску в SHM
            mask_slot = f"mask_{self._camera_id}"
            # Маска — 1-канальная, расширяем до (H, W, 1)
            mask_3d = mask[:, :, np.newaxis]
            mm.write_images(f"camera_{self._camera_id}", mask_slot, [mask_3d], 0)

            # IPC: уведомить renderer
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
