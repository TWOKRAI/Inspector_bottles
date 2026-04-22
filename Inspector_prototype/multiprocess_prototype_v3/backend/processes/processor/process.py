"""ProcessorProcess — инфраструктурный контейнер для ProcessorService.

Тонкий ProcessModule: управление воркерами, IPC, SHM.
Команды и register-хендлеры — в commands.py, адаптер — в adapter.py.
"""
from __future__ import annotations

import time

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.router_module.middleware import FrameShmMiddleware
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig
from multiprocess_prototype_v3.backend.helpers import apply_register_update, message_as_dict
from multiprocess_prototype_v3.registers import PROCESSOR_REGISTER
from multiprocess_prototype_v3.services.processor.detection import ColorBlobDetector
from multiprocess_prototype_v3.services.processor.service import ProcessorService

from .adapter import ProcessorAdapter
from .commands import build_command_table, build_register_handlers


class ProcessorProcess(ProcessModule):
    """Процесс обработки кадров. Инфраструктура: воркеры, IPC, SHM, команды."""

    def _init_application_threads(self) -> None:
        self._log_info("ProcessorProcess initializing...")
        app_cfg = self.get_config("config") or {}

        # SHM middleware: приём кадров от камеры (camera/camera_frame)
        self._recv_frame_mw = FrameShmMiddleware(
            self.memory_manager, owner="camera", slot="camera_frame"
        )
        self.router_manager.add_receive_middleware(self._recv_frame_mw.on_receive)

        # SHM middleware: отправка масок (processor/processor_mask)
        self._send_mask_mw = FrameShmMiddleware(
            self.memory_manager, owner=self.name, slot="processor_mask"
        )
        self.router_manager.add_send_middleware(self._send_mask_mw.on_send)

        # Создаём адаптер (реализация порта)
        adapter = ProcessorAdapter(self)

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

        # Команды из таблицы
        cmd_table = build_command_table(self._service)
        for cmd, handler in cmd_table.items():
            self.command_manager.register_command(cmd, handler)

        # Воркер
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "processing_worker", self._processing_worker, cfg, auto_start=True
        )
        self._log_info("ProcessorProcess ready")

    # --- Воркер обработки ---

    def _processing_worker(self, stop_event, pause_event) -> None:
        """Воркер: receive → register_update → middleware frame → service.process_frame()."""
        register_handlers = build_register_handlers(self._service)
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            # Инфраструктура: получение сообщения (receive middleware уже читает frame из SHM)
            msg = self.receive_message(timeout=0.1, channel_types=["data"])
            msg_dict = message_as_dict(msg)

            # Инфраструктура: обработка register_update
            if msg_dict.get("data_type") == "register_update":
                apply_register_update(
                    msg_dict.get("data") or {}, PROCESSOR_REGISTER, register_handlers
                )
                continue

            # Проверка типа сообщения
            if msg_dict.get("data_type") != "frame_ready":
                continue

            # Кадр уже прочитан из SHM receive middleware (FrameShmMiddleware.on_receive)
            frame = msg_dict.get("frame")
            if frame is None:
                continue

            data = msg_dict.get("data", {})

            # Делегация бизнес-логики в сервис
            self._service.process_frame(frame, data)

    # --- Shutdown ---

    def shutdown(self) -> bool:
        self._log_info("ProcessorProcess shutting down...")
        if self.memory_manager:
            self.memory_manager.close_all(self.name)
        self.is_initialized = False
        return super().shutdown()
