"""CameraProcess — инфраструктурный контейнер для CameraService.

Тонкий ProcessModule: управление воркерами, IPC, SHM.
Команды и register-хендлеры — в commands.py, адаптер — в adapter.py.
Вся бизнес-логика — в CameraService.
"""
from __future__ import annotations

import time

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.router_module.middleware import FrameShmMiddleware
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig
from multiprocess_prototype_v3.backend.helpers import apply_register_update, message_as_dict
from multiprocess_prototype_v3.registers import CAMERA_REGISTER
from multiprocess_prototype_v3.services.camera.service import CameraService

from .adapter import CameraAdapter
from .commands import build_command_table, build_register_handlers


class CameraProcess(ProcessModule):
    """Процесс камеры. Инфраструктура: воркеры, IPC, SHM, команды.

    Делегирует бизнес-логику в CameraService через adapter pattern.
    """

    def _init_application_threads(self) -> None:
        self._log_info("CameraProcess initializing...")

        # SHM middleware для отправки кадров (camera → processor)
        self._frame_mw = FrameShmMiddleware(
            self.memory_manager, owner="camera", slot="camera_frame"
        )
        self.router_manager.add_send_middleware(self._frame_mw.on_send)

        # Создать сервис с адаптером для IPC
        adapter = CameraAdapter(self)
        app_cfg = self.get_config("config") or {}
        self._service = CameraService(output=adapter, config=app_cfg)

        # Команды из таблицы
        cmd_table = build_command_table(self._service, self.worker_manager)
        for cmd, handler in cmd_table.items():
            self.command_manager.register_command(cmd, handler)

        # Воркер захвата (стартует в паузе — ждёт start_capture)
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "capture_worker", self._capture_worker, cfg, auto_start=False
        )
        self.worker_manager.pause_worker("capture_worker")

        self._log_info(
            f"CameraProcess ready, camera_type={self._service.current_type}"
        )

    # --- Воркер захвата ---

    def _capture_worker(self, stop_event, pause_event) -> None:
        """Основной цикл захвата: register_update → capture_and_publish."""
        cmd_table = build_command_table(self._service, self.worker_manager)
        register_handlers = build_register_handlers(
            self._service, cmd_table["set_camera_type"]
        )
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            # Обработка register_update сообщений
            msg = self.receive_message(timeout=0, channel_types=["data"])
            if msg:
                msg_dict = message_as_dict(msg)
                if msg_dict.get("data_type") == "register_update":
                    apply_register_update(
                        msg_dict.get("data") or {}, CAMERA_REGISTER, register_handlers
                    )
                    continue

            # Делегация захвата в сервис
            self._service.capture_and_publish()

    # --- Shutdown ---

    def shutdown(self) -> bool:
        """Корректное завершение: пауза воркера → shutdown сервиса → close SHM."""
        self._log_info("CameraProcess shutting down...")
        if self.worker_manager:
            self.worker_manager.pause_worker("capture_worker")
        self._service.shutdown()
        if self.memory_manager:
            self.memory_manager.close_all("camera")
        self.is_initialized = False
        return super().shutdown()
