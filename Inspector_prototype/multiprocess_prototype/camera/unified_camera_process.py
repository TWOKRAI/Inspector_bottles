# multiprocess_prototype/camera/unified_camera_process.py
"""
UnifiedCameraProcess — единый процесс камеры с переключением бэкендов без перезапуска.

Бэкенды: Simulator, Webcam, Hikvision. Команда set_camera_type переключает на лету.
"""

import time
from typing import Optional

import numpy as np
import cv2

from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.message_module import MessageAdapter
from multiprocess_framework.refactored.modules.worker_module import (
    ThreadConfig,
    ExecutionMode,
)

from .backends import SimulatorBackend, WebcamBackend, HikvisionBackend


def _resize_frame(frame: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    """Ресайз кадра под целевой размер (для записи в SharedMemory)."""
    if frame.shape[0] == target_h and frame.shape[1] == target_w:
        return frame
    try:
        import cv2
        return cv2.resize(
            frame,
            (target_w, target_h),
            interpolation=cv2.INTER_LINEAR,
        )
    except ImportError:
        return frame


class UnifiedCameraProcess(ProcessModule):
    """
    Единый процесс камеры. Переключение simulator/webcam/hikvision без перезапуска.
    """

    # Размер памяти — максимум для всех режимов
    MEMORY_HEIGHT = 1080
    MEMORY_WIDTH = 1920

    def _init_application_threads(self):
        self._log_info("UnifiedCameraProcess initializing...")

        self._msg = MessageAdapter(sender=self.name)
        app_cfg = self.get_config("config") or {}

        self._fps = app_cfg.get("fps", 30)
        self._width = app_cfg.get("resolution_width", 640)
        self._height = app_cfg.get("resolution_height", 480)
        self._device_id = app_cfg.get("device_id", 0)
        self._camera_index = app_cfg.get("camera_index", 0)
        self._hikvision_width = app_cfg.get("hikvision_resolution_width", 1920)
        self._hikvision_height = app_cfg.get("hikvision_resolution_height", 1080)
        self._simulator_image_path = app_cfg.get("simulator_image_path")

        self._backend_lock = __import__("threading").Lock()
        self._frame_id = 0

        # Начальный бэкенд из конфига
        initial_type = app_cfg.get("camera_type", "simulator")
        self._current_type = initial_type

        # Сброс веб-камеры перед открытием (отключить/включить — чистое состояние)
        if initial_type == "webcam":
            from multiprocess_prototype.utils.webcam_capture import reset_webcam
            reset_webcam(device_id=self._device_id)
            time.sleep(0.2)  # Пауза после reset перед открытием (MSMF)

        self._backend = self._create_backend(initial_type)

        # Команды
        self.command_manager.register_command("set_camera_type", self._cmd_set_camera_type)
        self.command_manager.register_command("get_camera_type", self._cmd_get_camera_type)
        self.command_manager.register_command("start_capture", self._cmd_start_capture)
        self.command_manager.register_command("stop_capture", self._cmd_stop_capture)
        self.command_manager.register_command("set_fps", self._cmd_set_fps)
        self.command_manager.register_command("set_resolution", self._cmd_set_resolution)
        self.command_manager.register_command("enum_devices", self._cmd_enum_devices)
        self.command_manager.register_command("open", self._cmd_open)
        self.command_manager.register_command("close", self._cmd_close)
        self.command_manager.register_command("start_grabbing", self._cmd_start_grabbing)
        self.command_manager.register_command("stop_grabbing", self._cmd_stop_grabbing)
        self.command_manager.register_command("get_parameters", self._cmd_get_parameters)
        self.command_manager.register_command("set_parameters", self._cmd_set_parameters)

        config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "capture_worker", self._capture_worker, config, auto_start=False
        )
        self.worker_manager.pause_worker("capture_worker")

        self._log_info(f"UnifiedCameraProcess ready, camera_type={initial_type}")

    def _send_to_gui(self, msg_type: str, data: dict):
        msg = self._msg.data(targets=["gui"], data_type=msg_type, data=data)
        self.send_message("gui", msg.to_dict())

    def _create_backend(self, camera_type: str):
        if camera_type == "simulator":
            return SimulatorBackend(
                self._width, self._height, image_path=self._simulator_image_path
            )
        if camera_type == "webcam":
            return WebcamBackend(self._width, self._height, device_id=self._device_id)
        if camera_type == "hikvision":
            return HikvisionBackend(
                self._camera_index,
                self._hikvision_width,
                self._hikvision_height,
                send_to_gui=self._send_to_gui,
            )
        return SimulatorBackend(self._width, self._height)

    def _cmd_set_camera_type(self, data: dict):
        """Переключение типа камеры без перезапуска."""
        new_type = data.get("camera_type", "simulator")
        if new_type not in ("simulator", "webcam", "hikvision"):
            return {"status": "error", "error": f"Unknown camera_type: {new_type}"}
        with self._backend_lock:
            if self._current_type == new_type:
                self._send_to_gui("status", {"status": f"Already {new_type}"})
                return {"status": "ok"}  # Уже выбран

            # Остановить текущий бэкенд
            self.worker_manager.pause_worker("capture_worker")
            self._backend.stop()
            self._backend.close()

            # Создать новый
            self._current_type = new_type
            self._backend = self._create_backend(new_type)

            self._send_to_gui("camera_type_changed", {"camera_type": new_type})
            self._send_to_gui("status", {"status": f"Switched to {new_type}"})
            return {"status": "ok", "camera_type": new_type}

    def _cmd_get_camera_type(self, data: dict):
        return {"status": "ok", "camera_type": self._current_type}

    def _cmd_start_capture(self, data: dict):
        with self._backend_lock:
            if self._current_type == "hikvision":
                result = self._backend.handle_command("start_grabbing", data)
                if result:
                    if not self.worker_manager.is_worker_running("capture_worker"):
                        self.worker_manager.start_worker("capture_worker")
                    self.worker_manager.resume_worker("capture_worker")
                    return result
            else:
                self._backend.start()
                if not self.worker_manager.is_worker_running("capture_worker"):
                    self.worker_manager.start_worker("capture_worker")
                self.worker_manager.resume_worker("capture_worker")
                return {"status": "ok"}
        return {"status": "error"}

    def _cmd_stop_capture(self, data: dict):
        # Сначала приостановить воркер — иначе grabFrame во время close() даёт MSMF error
        if self.worker_manager:
            self.worker_manager.pause_worker("capture_worker")
        time.sleep(0.05)  # Дать воркеру завершить текущий capture_frame
        with self._backend_lock:
            if self._current_type == "hikvision":
                result = self._backend.handle_command("stop_grabbing", data)
            else:
                self._backend.stop()
                # Webcam: close() освобождает устройство (гаснет LED)
                if self._current_type == "webcam":
                    self._backend.close()
                result = {"status": "ok"}
        return result or {"status": "ok"}

    def _cmd_set_fps(self, data: dict):
        """Только для simulator/webcam."""
        new_fps = data.get("fps", self._fps)
        self._fps = max(1, min(120, new_fps))
        return {"status": "ok", "fps": self._fps}

    def _cmd_set_resolution(self, data: dict):
        """Только для simulator/webcam."""
        self._width = data.get("width", self._width)
        self._height = data.get("height", self._height)
        if self._current_type in ("simulator", "webcam"):
            with self._backend_lock:
                self._backend.close()
                self._backend = self._create_backend(self._current_type)
        return {"status": "ok"}

    def _cmd_enum_devices(self, data: dict):
        with self._backend_lock:
            if self._current_type == "hikvision":
                return self._backend.handle_command("enum_devices", data) or {}
        return {"status": "error", "error": "Only for Hikvision"}

    def _cmd_open(self, data: dict):
        with self._backend_lock:
            if self._current_type == "hikvision":
                return self._backend.handle_command("open", data) or {}
        return {"status": "error"}

    def _cmd_close(self, data: dict):
        with self._backend_lock:
            if self._current_type == "hikvision":
                return self._backend.handle_command("close", data) or {}
        return {"status": "ok"}

    def _cmd_start_grabbing(self, data: dict):
        return self._cmd_start_capture(data)

    def _cmd_stop_grabbing(self, data: dict):
        return self._cmd_stop_capture(data)

    def _cmd_get_parameters(self, data: dict):
        with self._backend_lock:
            if self._current_type == "hikvision":
                return self._backend.handle_command("get_parameters", data) or {}
        return {}

    def _cmd_set_parameters(self, data: dict):
        with self._backend_lock:
            if self._current_type == "hikvision":
                return self._backend.handle_command("set_parameters", data) or {}
        return {"status": "error"}

    def _capture_worker(self, stop_event, pause_event):
        frame_count = 0
        stats_start = time.time()
        delay = 1.0 / max(1, self._fps)

        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            with self._backend_lock:
                backend = self._backend

            frame = backend.capture_frame()

            if frame is None:
                time.sleep(0.01)
                continue

            frame_count += 1
            self._frame_id = (self._frame_id + 1) % 121
            timestamp = time.time()

            # Ресайз под память (1920x1080)
            frame = _resize_frame(frame, self.MEMORY_HEIGHT, self.MEMORY_WIDTH)
                            
            # cv2.imwrite(f"frame.png", frame)

            mm = self.memory_manager
            if mm:
                free_idx = mm.find_free_index("camera", "camera_frame")
                if free_idx is None:
                    free_idx = 0
                shm_name = mm.write_images(
                    "camera", "camera_frame", [frame], free_idx
                )
                if shm_name:
                    notification = self._msg.data(
                        targets=["processor"],
                        data_type="frame_ready",
                        data={
                            "frame_id": self._frame_id,
                            "timestamp": timestamp,
                            "shm_name": "camera_frame",
                            "shm_index": free_idx,
                            "shm_actual_name": shm_name,
                            "width": frame.shape[1],
                            "height": frame.shape[0],
                        },
                    )
                    self.send_message("processor", notification.to_dict())

            # FPS для simulator/webcam
            if self._current_type != "hikvision":
                time.sleep(delay)

    def shutdown(self) -> bool:
        self._log_info("UnifiedCameraProcess shutting down...")
        if self.worker_manager:
            self.worker_manager.pause_worker("capture_worker")
        with self._backend_lock:
            if self._backend:
                try:
                    self._backend.stop()
                    self._backend.close()
                finally:
                    self._backend = None
            # Сброс веб-камеры при остановке — полное освобождение устройства
            if self._current_type == "webcam":
                from multiprocess_prototype.utils.webcam_capture import reset_webcam
                reset_webcam(device_id=self._device_id)
        if self.memory_manager:
            self.memory_manager.close_all("camera")
        self.is_initialized = False
        return super().shutdown()
