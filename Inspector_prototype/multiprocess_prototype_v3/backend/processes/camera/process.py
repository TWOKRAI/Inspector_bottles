"""CameraProcess — инфраструктурный контейнер для CameraService.

Тонкий ProcessModule: управление воркерами, IPC, SHM, регистрация команд.
Вся бизнес-логика — в CameraService.
"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np

from multiprocess_framework.modules.process_module import ProcessIO, ProcessModule
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig
from multiprocess_prototype_v3.registers import CAMERA_REGISTER
from multiprocess_prototype_v3.services.camera.service import CameraService
from multiprocess_prototype_v3.shared.frame_io import message_as_dict
from multiprocess_prototype_v3.shared.register_sync import apply_register_update


class CameraProcess(ProcessModule):
    """Процесс камеры. Инфраструктура: воркеры, IPC, SHM, команды.

    Делегирует бизнес-логику в CameraService через adapter pattern.
    """

    def _init_application_threads(self) -> None:
        self._log_info("CameraProcess initializing...")

        # Создать сервис с адаптером для IPC
        adapter = _CameraAdapter(self)
        app_cfg = self.get_config("config") or {}
        self._service = CameraService(output=adapter, config=app_cfg)

        self._register_commands()

        # Воркер захвата (стартует в паузе — ждёт start_capture)
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "capture_worker", self._capture_worker, cfg, auto_start=False
        )
        self.worker_manager.pause_worker("capture_worker")

        self._log_info(
            f"CameraProcess ready, camera_type={self._service.current_type}"
        )

    def _register_commands(self) -> None:
        """Регистрация IPC-команд.

        Команды с доп. логикой (управление воркером, cross-backend) — идут
        через _cmd_* обёртки. Чистая делегация — напрямую в метод сервиса.
        """
        svc = self._service
        commands = {
            # С доп. логикой (пауза/resume воркера, cross-backend)
            "set_camera_type": self._cmd_set_camera_type,
            "start_capture": self._cmd_start_capture,
            "stop_capture": self._cmd_stop_capture,
            "enum_devices": self._cmd_enum_devices,
            "start_grabbing": self._cmd_start_capture,  # alias (Hikvision SDK)
            "stop_grabbing": self._cmd_stop_capture,    # alias (Hikvision SDK)
            # Чистая делегация в сервис
            "get_camera_type": lambda _: {"status": "ok", "camera_type": svc.current_type},
            "set_fps": svc.set_fps,
            "set_resolution": svc.set_resolution,
            "set_device_id": svc.set_device_id,
            "set_camera_index": svc.set_camera_index,
            "set_hikvision_resolution": svc.set_hikvision_resolution,
            "open": lambda d: svc.handle_hikvision_command("open", d),
            "close": lambda d: svc.handle_hikvision_command("close", d),
            "get_parameters": lambda d: svc.handle_hikvision_command("get_parameters", d),
            "set_parameters": lambda d: svc.handle_hikvision_command("set_parameters", d),
        }
        for cmd, handler in commands.items():
            self.command_manager.register_command(cmd, handler)

    # --- Register sync handlers ---

    def _build_register_handlers(self) -> dict:
        """Маппинг полей регистра на обработчики.

        Адаптер асинхронных register_update сообщений из GUI: имя_поля →
        handler(value). Имена полей не совпадают с именами команд, payload —
        одно значение (а не dict), несколько полей могут маппиться в один
        метод сервиса (resolution_width + resolution_height → set_resolution).
        """
        svc = self._service
        return {
            "camera_type": lambda v: self._cmd_set_camera_type({"camera_type": v}),
            "fps": lambda v: svc.set_fps({"fps": v}),
            "resolution_width": lambda v: svc.set_resolution({"width": v}),
            "resolution_height": lambda v: svc.set_resolution({"height": v}),
            "device_id": lambda v: svc.set_device_id({"device_id": v}),
            "camera_index": lambda v: svc.set_camera_index({"camera_index": v}),
            "hikvision_resolution_width": lambda v: svc.set_hikvision_resolution(
                {"width": v}
            ),
            "hikvision_resolution_height": lambda v: svc.set_hikvision_resolution(
                {"height": v}
            ),
            "hikvision_frame_rate": lambda v: svc.patch_hikvision_params(
                {"frame_rate": v}
            ),
            "hikvision_exposure_time": lambda v: svc.patch_hikvision_params(
                {"exposure_time": v}
            ),
            "hikvision_gain": lambda v: svc.patch_hikvision_params({"gain": v}),
        }

    # --- Команды (делегация в сервис + управление воркером) ---

    def _cmd_set_camera_type(self, data: dict) -> dict:
        """Переключить тип камеры. Пауза воркера на время переключения."""
        self.worker_manager.pause_worker("capture_worker")
        result = self._service.switch_camera_type(
            data.get("camera_type", "simulator")
        )
        return result

    def _cmd_start_capture(self, data: dict) -> dict:
        """Запустить захват: делегация в сервис + resume воркера."""
        result = self._service.start_capture(data)
        if result and result.get("status") != "error":
            if not self.worker_manager.is_worker_running("capture_worker"):
                self.worker_manager.start_worker("capture_worker")
            self.worker_manager.resume_worker("capture_worker")
        return result or {"status": "error"}

    def _cmd_stop_capture(self, data: dict) -> dict:
        """Остановить захват: пауза воркера + делегация в сервис."""
        if self.worker_manager:
            self.worker_manager.pause_worker("capture_worker")
        time.sleep(0.05)
        return self._service.stop_capture(data)

    def _cmd_enum_devices(self, data: dict) -> dict:
        """Перечисление устройств. Для cross-backend enum может паузить воркер."""
        payload = dict(data or {})
        backend_hint = payload.get("backend")
        # Если cross-backend enum hikvision при активном webcam — паузим воркер
        if (
            backend_hint == "hikvision"
            and self._service.current_type == "webcam"
        ):
            self.worker_manager.pause_worker("capture_worker")
            result = self._service.enumerate_devices(payload)
            self.worker_manager.resume_worker("capture_worker")
            return result
        return self._service.enumerate_devices(payload)

    # --- Воркер захвата ---

    def _capture_worker(self, stop_event, pause_event) -> None:
        """Основной цикл захвата: register_update → capture_and_publish."""
        register_handlers = self._build_register_handlers()
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


class _CameraAdapter:
    """Реализует CameraOutputPort через ProcessIO (IPC + SHM facade)."""

    def __init__(self, process: CameraProcess) -> None:
        self._io = ProcessIO(process)

    def send_frame_to_processor(self, data: dict) -> None:
        self._io.send_data("processor", "frame_ready", data)

    def send_to_gui(self, msg_type: str, data: dict) -> None:
        self._io.send_data("gui", msg_type, data)

    def write_frame_to_shm(
        self, frame: np.ndarray, frame_id: int, timestamp: float
    ) -> Optional[dict]:
        return self._io.write_frames_to_shm("camera", "camera_frame", [frame])
