"""RendererProcess — инфраструктурный контейнер для RendererService.

Тонкий ProcessModule: управление воркерами, IPC, SHM.
Команды и register-хендлеры — в commands.py, адаптер — в adapter.py.
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.router_module.middleware import FrameShmMiddleware
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig
from multiprocess_prototype_v3.backend.helpers import (
    apply_register_update,
    message_as_dict,
)
from multiprocess_prototype_v3.registers import RENDERER_REGISTER
from multiprocess_prototype_v3.services.renderer.service import RendererService

from .adapter import RendererAdapter
from .commands import build_command_table, build_register_handlers


class RendererProcess(ProcessModule):
    """Процесс рендеринга. Инфраструктура: воркеры, IPC, SHM, команды."""

    def _init_application_threads(self) -> None:
        self._log_info("RendererProcess initializing...")

        # SHM middleware: приём оригинальных кадров от камеры (camera/camera_frame)
        self._recv_frame_mw = FrameShmMiddleware(
            self.memory_manager, owner="camera", slot="camera_frame"
        )
        self.router_manager.add_receive_middleware(self._recv_frame_mw.on_receive)

        adapter = RendererAdapter(self)
        self._service = RendererService(
            output=adapter,
            output_dir=self.get_config("output_dir", "./output_frames"),
            save_frames=self.get_config("save_frames", False),
            draw_bboxes=self.get_config("draw_bboxes", True),
            draw_contours=self.get_config("draw_contours", True),
            show_original=self.get_config("show_original", True),
            show_mask=self.get_config("show_mask", True),
        )

        # Команды из таблицы
        cmd_table = build_command_table(self._service)
        for cmd, handler in cmd_table.items():
            self.command_manager.register_command(cmd, handler)

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "render_worker", self._render_worker, cfg, auto_start=True
        )
        self._log_info("RendererProcess ready")

    # --- Воркер рендеринга ---

    def _render_worker(self, stop_event, pause_event) -> None:
        """Воркер: receive → register_update → read SHM → service.render_frame()."""
        register_handlers = build_register_handlers(self._service)
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            msg = self.receive_message(timeout=0.1, channel_types=["data"])
            msg_dict = message_as_dict(msg)
            if msg_dict.get("data_type") == "register_update":
                apply_register_update(
                    msg_dict.get("data") or {}, RENDERER_REGISTER, register_handlers
                )
                continue

            if msg_dict.get("data_type") != "detection_result":
                continue
            data = msg_dict.get("data", {})

            # Оригинальный кадр уже прочитан receive middleware (FrameShmMiddleware.on_receive)
            original = msg_dict.get("frame")
            if original is None:
                # Fallback: прямое чтение из SHM
                original = self._read_original_frame(data)
            if original is None:
                continue
            mask = self._read_mask_frame(data, original.shape[1], original.shape[0])

            # Делегация бизнес-логики в сервис
            self._service.render_frame(original, mask, data)

    def _read_original_frame(self, data: dict) -> Optional[np.ndarray]:
        """Прочитать оригинальный кадр из SHM камеры через MemoryManager."""
        mm = self.memory_manager
        if not mm:
            return None
        images = mm.read_images("camera", "camera_frame", data.get("shm_index", 0), n=1)
        if images:
            return images[0].copy()
        return None

    def _read_mask_frame(self, data: dict, width: int, height: int) -> np.ndarray:
        """Прочитать маску из SHM процессора через MemoryManager."""
        mm = self.memory_manager
        if mm and data.get("mask_shm_actual_name"):
            images = mm.read_images(
                "processor", "processor_mask", data.get("mask_shm_index", 0), n=1
            )
            if images:
                return images[0].copy()
        return np.zeros((height, width, 3), dtype=np.uint8)

    # --- Shutdown ---

    def shutdown(self) -> bool:
        self._log_info("RendererProcess shutting down...")
        if self.memory_manager:
            self.memory_manager.close_all("renderer")
        self.is_initialized = False
        return super().shutdown()
