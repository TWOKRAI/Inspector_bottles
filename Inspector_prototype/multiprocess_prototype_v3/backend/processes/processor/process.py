"""ProcessorProcess — инфраструктурный контейнер для ProcessorService."""
from __future__ import annotations

import time
from typing import Any, Optional

from multiprocess_framework.modules.message_module import MessageAdapter
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig
from multiprocess_prototype_v3.registers import PROCESSOR_REGISTER
from multiprocess_prototype_v3.services.processor.detection import ColorBlobDetector
from multiprocess_prototype_v3.services.processor.service import ProcessorService
from multiprocess_prototype_v3.shared.frame_io import message_as_dict, read_frame_from_msg
from multiprocess_prototype_v3.shared.register_sync import apply_register_update


class ProcessorProcess(ProcessModule):
    """Процесс обработки кадров. Инфраструктура: воркеры, IPC, SHM, команды."""

    def _init_application_threads(self) -> None:
        self._log_info("ProcessorProcess initializing...")
        app_cfg = self.get_config("config") or {}

        # Создаём адаптер (реализация порта)
        adapter = _ProcessorAdapter(self)

        # Создаём детектор (бизнес-зависимость)
        detector = ColorBlobDetector(
            app_cfg.get("color_lower", [0, 0, 150]),
            app_cfg.get("color_upper", [100, 100, 255]),
            app_cfg.get("min_area", 500),
            app_cfg.get("max_area", 50000),
        )

        # Создаём сервис с инжектированным портом
        self._service = ProcessorService(
            output=adapter,
            detector=detector,
            target_width=app_cfg.get("resolution_width", 640),
            target_height=app_cfg.get("resolution_height", 480),
        )

        # Регистрация команд — делегация в сервис
        self.command_manager.register_command("set_color_range", self._cmd_set_color_range)
        self.command_manager.register_command("set_min_area", self._cmd_set_min_area)
        self.command_manager.register_command("set_max_area", self._cmd_set_max_area)

        # Воркер
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "processing_worker", self._processing_worker, cfg, auto_start=True
        )
        self._log_info("ProcessorProcess ready")

    def _build_register_handlers(self) -> dict:
        """Маппинг register полей на команды сервиса."""
        return {
            "color_lower": lambda v: self._service.set_color_range(lower=v),
            "color_upper": lambda v: self._service.set_color_range(upper=v),
            "min_area": lambda v: self._service.set_min_area(v),
            "max_area": lambda v: self._service.set_max_area(v),
        }

    def _processing_worker(self, stop_event, pause_event) -> None:
        """Воркер: receive → register_update → read SHM → service.process_frame()."""
        register_handlers = self._build_register_handlers()
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            # Инфраструктура: получение сообщения
            msg = self.receive_message(timeout=0.1, channel_types=["data"])
            msg_dict = message_as_dict(msg)

            # Инфраструктура: обработка register_update
            if msg_dict.get("data_type") == "register_update":
                apply_register_update(
                    msg_dict.get("data") or {}, PROCESSOR_REGISTER, register_handlers
                )
                continue

            # Инфраструктура: чтение кадра из SHM
            frame, data = read_frame_from_msg(
                msg, self.memory_manager, expected_data_type="frame_ready"
            )
            if frame is None:
                continue

            # Делегация бизнес-логики в сервис
            self._service.process_frame(frame, data)

    # --- Команды (делегация в сервис) ---

    def _cmd_set_color_range(self, data: dict) -> dict:
        return self._service.set_color_range(data.get("color_lower"), data.get("color_upper"))

    def _cmd_set_min_area(self, data: dict) -> dict:
        value = self._service.set_min_area(
            data.get("min_area", self._service.detector.min_area)
        )
        return {"status": "ok", "min_area": value}

    def _cmd_set_max_area(self, data: dict) -> dict:
        value = self._service.set_max_area(
            data.get("max_area", self._service.detector.max_area)
        )
        return {"status": "ok", "max_area": value}

    def shutdown(self) -> bool:
        self._log_info("ProcessorProcess shutting down...")
        if self.memory_manager:
            self.memory_manager.close_all(self.name)
        self.is_initialized = False
        return super().shutdown()


class _ProcessorAdapter:
    """Реализует ProcessorOutputPort через ProcessModule IPC."""

    def __init__(self, process: ProcessorProcess) -> None:
        self._p = process
        self._msg = MessageAdapter(sender=process.name)

    def send_detection_to_renderer(self, result_data: dict) -> None:
        """Отправить результат детекции рендереру через IPC."""
        msg = self._msg.data(
            targets=["renderer"], data_type="detection_result", data=result_data
        )
        self._p.send_message("renderer", msg.to_dict())

    def send_detections_to_database(self, rows: list[dict]) -> None:
        """Отправить детекции в БД через IPC command."""
        msg = self._msg.command(
            targets=["database"],
            command="db.save_detections",
            args={"detections": rows},
            data={},
        )
        self._p.send_message("database", msg.to_dict())

    def send_feedback_to_camera(self, frame_id: int, processing_time: float) -> None:
        """Отправить feedback камере через IPC event."""
        feedback = self._msg.event(
            event_type="frame_processed",
            targets=["camera"],
            event_data={"frame_id": frame_id, "processing_time": processing_time},
        )
        self._p.send_message("camera", feedback.to_dict())

    def write_mask_to_shm(self, mask) -> tuple[Optional[str], int]:
        """Записать маску в SHM."""
        from multiprocess_prototype_v3.shared.frame_io import write_frame_to_shm
        return write_frame_to_shm(self._p.memory_manager, self._p.name, "processor_mask", mask)
