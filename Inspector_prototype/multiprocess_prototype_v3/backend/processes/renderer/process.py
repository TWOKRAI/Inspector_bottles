"""RendererProcess — инфраструктурный контейнер для RendererService."""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from multiprocess_framework.modules.message_module import MessageAdapter
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig
from multiprocess_prototype_v3.registers import RENDERER_REGISTER
from multiprocess_prototype_v3.services.renderer.service import RendererService
from multiprocess_prototype_v3.shared.frame_io import message_as_dict, read_frame_from_shm
from multiprocess_prototype_v3.shared.register_sync import apply_register_update


class RendererProcess(ProcessModule):
    """Процесс рендеринга. Инфраструктура: воркеры, IPC, SHM, команды."""

    def _init_application_threads(self) -> None:
        self._log_info("RendererProcess initializing...")
        self._msg = MessageAdapter(sender=self.name)

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

        for cmd, handler in {
            "set_draw_contours": self._cmd_set_draw_contours,
            "set_show_original": self._cmd_set_show_original,
            "set_show_mask": self._cmd_set_show_mask,
            "set_draw_bboxes": self._cmd_set_draw_bboxes,
            "set_save_frames": self._cmd_set_save_frames,
        }.items():
            self.command_manager.register_command(cmd, handler)

        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "render_worker", self._render_worker, cfg, auto_start=True
        )
        self._log_info("RendererProcess ready")

    def _build_register_handlers(self) -> dict:
        return {
            "show_original": lambda v: self._cmd_set_show_original({"show_original": v}),
            "show_mask": lambda v: self._cmd_set_show_mask({"show_mask": v}),
            "draw_contours": lambda v: self._cmd_set_draw_contours({"draw_contours": v}),
            "draw_bboxes": lambda v: self._cmd_set_draw_bboxes({"draw_bboxes": v}),
            "save_frames": lambda v: self._cmd_set_save_frames({"save_frames": v}),
        }

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

    # --- Команды (делегация в сервис) ---

    def _cmd_set_draw_contours(self, data: dict) -> dict:
        self._service.draw_contours = data.get("draw_contours", self._service.draw_contours)
        return {"status": "ok"}

    def _cmd_set_show_original(self, data: dict) -> dict:
        self._service.show_original = data.get("show_original", self._service.show_original)
        return {"status": "ok"}

    def _cmd_set_show_mask(self, data: dict) -> dict:
        self._service.show_mask = data.get("show_mask", self._service.show_mask)
        return {"status": "ok"}

    def _cmd_set_draw_bboxes(self, data: dict) -> dict:
        self._service.draw_bboxes = data.get("draw_bboxes", self._service.draw_bboxes)
        return {"status": "ok"}

    def _cmd_set_save_frames(self, data: dict) -> dict:
        self._service.save_frames = data.get("save_frames", self._service.save_frames)
        return {"status": "ok"}

    def shutdown(self) -> bool:
        self._log_info("RendererProcess shutting down...")
        if self.memory_manager:
            self.memory_manager.close_all("renderer")
        self.is_initialized = False
        return super().shutdown()


class _RendererAdapter:
    """Реализует RendererOutputPort через ProcessModule IPC."""

    def __init__(self, process: RendererProcess) -> None:
        self._p = process
        self._msg = MessageAdapter(sender=process.name)

    def send_rendered_to_gui(self, notification_data: dict) -> None:
        """Отправить уведомление о готовом кадре в GUI."""
        msg = self._msg.data(
            targets=["gui"], data_type="rendered_frame_ready", data=notification_data
        )
        self._p.send_message("gui", msg.to_dict())

    def send_reject_to_robot(self, frame_id: int, defects: list[dict]) -> None:
        """Отправить команду отбраковки роботу."""
        msg = self._msg.command(
            targets=["robot"],
            command="reject_item",
            args={"frame_id": frame_id, "defects": defects},
            data={"frame_id": frame_id, "defects": defects},
        )
        self._p.send_message("robot", msg.to_dict())

    def write_rendered_to_shm(self, frame: np.ndarray, mask: np.ndarray) -> Optional[dict]:
        """Записать rendered frame и mask в SHM."""
        mm = self._p.memory_manager
        if not mm:
            return None

        free_idx_rendered = mm.find_free_index("renderer", "rendered_frame") or 0
        shm_rendered_name = mm.write_images("renderer", "rendered_frame", [frame], free_idx_rendered)

        free_idx_mask = mm.find_free_index("renderer", "mask_frame") or 0
        shm_mask_name = mm.write_images("renderer", "mask_frame", [mask], free_idx_mask)

        if not shm_rendered_name:
            return None

        result = {
            "shm_name": "rendered_frame",
            "shm_index": free_idx_rendered,
            "shm_actual_name": shm_rendered_name,
        }
        if shm_mask_name:
            result["mask_shm_name"] = "mask_frame"
            result["mask_shm_index"] = free_idx_mask
            result["mask_shm_actual_name"] = shm_mask_name
        return result
