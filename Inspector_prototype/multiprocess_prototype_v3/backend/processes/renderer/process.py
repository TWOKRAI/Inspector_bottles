"""RendererProcess — инфраструктурный контейнер для RendererService."""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from multiprocess_framework.modules.process_module import ProcessIO, ProcessModule
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig
from multiprocess_prototype_v3.registers import RENDERER_REGISTER
from multiprocess_prototype_v3.services.renderer.service import RendererService
from multiprocess_prototype_v3.shared.frame_io import message_as_dict, read_frame_from_shm
from multiprocess_prototype_v3.shared.register_sync import apply_register_update


class RendererProcess(ProcessModule):
    """Процесс рендеринга. Инфраструктура: воркеры, IPC, SHM, команды."""

    # Флаги сервиса, управляемые через команды и register_update
    _SERVICE_FLAGS: tuple[str, ...] = (
        "show_original",
        "show_mask",
        "draw_contours",
        "draw_bboxes",
        "save_frames",
    )

    def _init_application_threads(self) -> None:
        self._log_info("RendererProcess initializing...")

        adapter = _RendererAdapter(self)
        self._service = RendererService(
            output=adapter,
            output_dir=self.get_config("output_dir", "./output_frames"),
            save_frames=self.get_config("save_frames", False),
            draw_bboxes=self.get_config("draw_bboxes", True),
            draw_contours=self.get_config("draw_contours", True),
            show_original=self.get_config("show_original", True),
            show_mask=self.get_config("show_mask", True),
        )

        self._register_commands()

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "render_worker", self._render_worker, cfg, auto_start=True
        )
        self._log_info("RendererProcess ready")

    def _register_commands(self) -> None:
        """Регистрация IPC-команд. Все — чистые setter'ы флагов сервиса."""
        for flag in self._SERVICE_FLAGS:
            self.command_manager.register_command(
                f"set_{flag}", self._make_flag_setter(flag)
            )

    def _make_flag_setter(self, flag: str):
        """Factory: setter для флага сервиса. Возвращает {"status": "ok"}."""
        def handler(data: dict) -> dict:
            setattr(self._service, flag, data.get(flag, getattr(self._service, flag)))
            return {"status": "ok"}
        return handler

    def _build_register_handlers(self) -> dict:
        """Адаптер register_update: field_name → setattr на сервисе."""
        def make(flag: str):
            return lambda v: setattr(self._service, flag, v)
        return {flag: make(flag) for flag in self._SERVICE_FLAGS}

    def _render_worker(self, stop_event, pause_event) -> None:
        """Воркер: receive → register_update → read SHM → service.render_frame()."""
        register_handlers = self._build_register_handlers()
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

            # Инфраструктура: чтение кадров из SHM
            original = self._read_original_frame(data)
            if original is None:
                continue
            mask = self._read_mask_frame(data, original.shape[1], original.shape[0])

            # Делегация бизнес-логики в сервис
            self._service.render_frame(original, mask, data)

    def _read_original_frame(self, data: dict) -> Optional[np.ndarray]:
        """Прочитать оригинальный кадр из SHM камеры."""
        mm = self.memory_manager
        frame = None
        if mm:
            images = mm.read_images("camera", "camera_frame", data.get("shm_index", 0), n=1)
            if images:
                frame = images[0].copy()
        if frame is None and data.get("shm_actual_name"):
            frame = read_frame_from_shm(
                data["shm_actual_name"], data.get("width", 640), data.get("height", 480)
            )
            if frame is not None:
                frame = frame.copy()
        return frame

    def _read_mask_frame(self, data: dict, width: int, height: int) -> np.ndarray:
        """Прочитать маску из SHM процессора."""
        mm = self.memory_manager
        mask = None
        if mm and data.get("mask_shm_actual_name"):
            images = mm.read_images(
                "processor", "processor_mask", data.get("mask_shm_index", 0), n=1
            )
            if images:
                mask = images[0].copy()
        if mask is None and data.get("mask_shm_actual_name"):
            mask = read_frame_from_shm(data["mask_shm_actual_name"], width, height)
            if mask is not None:
                mask = mask.copy()
        if mask is None:
            mask = np.zeros((height, width, 3), dtype=np.uint8)
        return mask

    def shutdown(self) -> bool:
        self._log_info("RendererProcess shutting down...")
        if self.memory_manager:
            self.memory_manager.close_all("renderer")
        self.is_initialized = False
        return super().shutdown()


class _RendererAdapter:
    """Реализует RendererOutputPort через ProcessIO (IPC + SHM facade)."""

    def __init__(self, process: RendererProcess) -> None:
        self._io = ProcessIO(process)

    def send_rendered_to_gui(self, notification_data: dict) -> None:
        self._io.send_data("gui", "rendered_frame_ready", notification_data)

    def send_reject_to_robot(self, frame_id: int, defects: list[dict]) -> None:
        payload = {"frame_id": frame_id, "defects": defects}
        self._io.send_command("robot", "reject_item", args=payload, data=payload)

    def write_rendered_to_shm(self, frame: np.ndarray, mask: np.ndarray) -> Optional[dict]:
        """Записать rendered frame и mask в SHM (два отдельных слота)."""
        rendered = self._io.write_frames_to_shm("renderer", "rendered_frame", [frame])
        if rendered is None:
            return None
        mask_info = self._io.write_frames_to_shm("renderer", "mask_frame", [mask])
        if mask_info is not None:
            rendered["mask_shm_name"] = mask_info["shm_name"]
            rendered["mask_shm_index"] = mask_info["shm_index"]
            rendered["mask_shm_actual_name"] = mask_info["shm_actual_name"]
        return rendered
