"""CameraProcess — инфраструктурный контейнер для CameraService.

Тонкий ProcessModule: управление воркерами, IPC, SHM, регистрация команд.
Вся бизнес-логика — в CameraService.
"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np

from multiprocess_framework.modules.message_module import MessageAdapter
from multiprocess_framework.modules.process_module import ProcessModule
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
        self._msg = MessageAdapter(sender=self.name)

        # Создать сервис с адаптером для IPC
        adapter = _CameraAdapter(self)
        app_cfg = self.get_config("config") or {}
        self._service = CameraService(output=adapter, config=app_cfg)

        # Регистрация команд (все делегируют в сервис)
        for cmd, handler in {
            "set_camera_type": self._cmd_set_camera_type,
            "get_camera_type": self._cmd_get_camera_type,
            "start_capture": self._cmd_start_capture,
            "stop_capture": self._cmd_stop_capture,
            "set_fps": self._cmd_set_fps,
            "set_resolution": self._cmd_set_resolution,
            "enum_devices": self._cmd_enum_devices,
            "set_device_id": self._cmd_set_device_id,
            "set_camera_index": self._cmd_set_camera_index,
            "set_hikvision_resolution": self._cmd_set_hikvision_resolution,
            "open": self._cmd_open,
            "close": self._cmd_close,
            "start_grabbing": self._cmd_start_grabbing,
            "stop_grabbing": self._cmd_stop_grabbing,
            "get_parameters": self._cmd_get_parameters,
            "set_parameters": self._cmd_set_parameters,
        }.items():
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

    # --- Register sync handlers ---

    def _build_register_handlers(self) -> dict:
        """Маппинг полей регистра на обработчики в сервисе."""
        return {
            "camera_type": lambda v: self._cmd_set_camera_type({"camera_type": v}),
            "fps": lambda v: self._cmd_set_fps({"fps": v}),
            "resolution_width": lambda v: self._cmd_set_resolution({"width": v}),
            "resolution_height": lambda v: self._cmd_set_resolution({"height": v}),
            "device_id": lambda v: self._cmd_set_device_id({"device_id": v}),
            "camera_index": lambda v: self._cmd_set_camera_index({"camera_index": v}),
            "hikvision_resolution_width": lambda v: self._cmd_set_hikvision_resolution(
                {"width": v}
            ),
            "hikvision_resolution_height": lambda v: self._cmd_set_hikvision_resolution(
                {"height": v}
            ),
            "hikvision_frame_rate": lambda v: self._service.patch_hikvision_params(
                {"frame_rate": v}
            ),
            "hikvision_exposure_time": lambda v: self._service.patch_hikvision_params(
                {"exposure_time": v}
            ),
            "hikvision_gain": lambda v: self._service.patch_hikvision_params({"gain": v}),
        }

    # --- Команды (делегация в сервис + управление воркером) ---

    def _cmd_set_camera_type(self, data: dict) -> dict:
        """Переключить тип камеры. Пауза воркера на время переключения."""
        self.worker_manager.pause_worker("capture_worker")
        result = self._service.switch_camera_type(
            data.get("camera_type", "simulator")
        )
        return result

    def _cmd_get_camera_type(self, data: dict) -> dict:
        return {"status": "ok", "camera_type": self._service.current_type}

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

    def _cmd_set_fps(self, data: dict) -> dict:
        return self._service.set_fps(data)

    def _cmd_set_resolution(self, data: dict) -> dict:
        return self._service.set_resolution(data)

    def _cmd_set_device_id(self, data: dict) -> dict:
        return self._service.set_device_id(data)

    def _cmd_set_camera_index(self, data: dict) -> dict:
        return self._service.set_camera_index(data)

    def _cmd_set_hikvision_resolution(self, data: dict) -> dict:
        return self._service.set_hikvision_resolution(data)

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

    def _cmd_open(self, data: dict) -> dict:
        return self._service.handle_hikvision_command("open", data)

    def _cmd_close(self, data: dict) -> dict:
        return self._service.handle_hikvision_command("close", data)

    def _cmd_start_grabbing(self, data: dict) -> dict:
        """Alias для start_capture (Hikvision SDK naming)."""
        return self._cmd_start_capture(data)

    def _cmd_stop_grabbing(self, data: dict) -> dict:
        """Alias для stop_capture (Hikvision SDK naming)."""
        return self._cmd_stop_capture(data)

    def _cmd_get_parameters(self, data: dict) -> dict:
        return self._service.handle_hikvision_command("get_parameters", data)

    def _cmd_set_parameters(self, data: dict) -> dict:
        return self._service.handle_hikvision_command("set_parameters", data)

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
    """Реализует CameraOutputPort через ProcessModule IPC.

    Связывает CameraService (бизнес-логика) с ProcessModule (инфраструктура):
    - send_frame_to_processor → send_message("processor", ...)
    - send_to_gui → send_message("gui", ...)
    - write_frame_to_shm → memory_manager.write_images(...)
    """

    def __init__(self, process: CameraProcess) -> None:
        self._p = process
        self._msg = MessageAdapter(sender=process.name)

    def send_frame_to_processor(self, data: dict) -> None:
        """Отправить уведомление о новом кадре процессору."""
        msg = self._msg.data(
            targets=["processor"],
            data_type="frame_ready",
            data=data,
        )
        self._p.send_message("processor", msg.to_dict())

    def send_to_gui(self, msg_type: str, data: dict) -> None:
        """Отправить сообщение в GUI (статус, fps, ошибки и т.д.)."""
        msg = self._msg.data(
            targets=["gui"],
            data_type=msg_type,
            data=data,
        )
        self._p.send_message("gui", msg.to_dict())

    def write_frame_to_shm(
        self, frame: np.ndarray, frame_id: int, timestamp: float
    ) -> Optional[dict]:
        """Записать кадр в SHM. Возвращает dict с shm_name/index или None."""
        mm = self._p.memory_manager
        if not mm:
            return None
        free_idx = mm.find_free_index("camera", "camera_frame")
        if free_idx is None:
            free_idx = 0
        shm_name = mm.write_images("camera", "camera_frame", [frame], free_idx)
        if not shm_name:
            return None
        return {
            "shm_name": "camera_frame",
            "shm_index": free_idx,
            "shm_actual_name": shm_name,
        }
