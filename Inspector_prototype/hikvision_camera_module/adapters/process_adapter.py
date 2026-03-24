# -*- coding: utf-8 -*-
"""
HikvisionCameraProcessAdapter — ProcessModule-адаптер для Hikvision камеры.

Тонкий слой над HikvisionCameraFacade. Команды делегируются в фасад.
Grab worker: capture_frame → cv2 (Bayer/Gray/RGBA→BGR) → SharedMemory → frame_ready.
"""

import time
from typing import Any, Dict

import numpy as np

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.message_module import MessageAdapter
from multiprocess_framework.modules.worker_module import (
    ThreadConfig,
    ExecutionMode,
)

from hikvision_camera_module.core.facade import HikvisionCameraFacade

_PIXEL_TYPE_BAYER_RG8 = 17301513


def _convert_frame_to_bgr(frame: np.ndarray, pixel_type: int) -> np.ndarray:
    """Конвертировать сырой кадр в BGR (3 канала)."""
    try:
        import cv2
    except ImportError:
        return frame
    if len(frame.shape) == 2:
        if pixel_type == _PIXEL_TYPE_BAYER_RG8:
            frame = cv2.cvtColor(frame, cv2.COLOR_BayerRG2RGB)
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        else:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    elif len(frame.shape) == 3 and frame.shape[2] == 4:
        frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2RGB)
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    elif len(frame.shape) == 3 and frame.shape[2] == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    return frame


def _resize_frame(frame: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    """Ресайз кадра под целевой размер."""
    if frame.shape[0] == target_h and frame.shape[1] == target_w:
        return frame
    try:
        import cv2
        return cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
    except ImportError:
        return frame


class HikvisionCameraProcessAdapter(ProcessModule):
    """
    Процесс захвата Hikvision камеры. Owner camera_frame в SharedMemory.
    Использует HikvisionCameraFacade — вся логика в модуле.
    """

    def _init_application_threads(self):
        self._log_info("HikvisionCameraProcessAdapter initializing...")
        self._msg = MessageAdapter(sender=self.name)
        app_cfg = self.get_config("config") or {}
        self._camera_index = app_cfg.get("camera_index", 0)
        self._target_width = app_cfg.get("hikvision_resolution_width", 1920)
        self._target_height = app_cfg.get("hikvision_resolution_height", 1080)
        self._frame_id = 0

        def _on_status(text: str):
            self._send_to_gui("status", {"status": text})

        def _on_error(text: str):
            self._send_to_gui("error", {"error": text})

        self._facade = HikvisionCameraFacade(on_status=_on_status, on_error=_on_error)

        self.command_manager.register_command("enum_devices", self._cmd_enum_devices)
        self.command_manager.register_command("open", self._cmd_open)
        self.command_manager.register_command("close", self._cmd_close)
        self.command_manager.register_command("start_grabbing", self._cmd_start_grabbing)
        self.command_manager.register_command("stop_grabbing", self._cmd_stop_grabbing)
        self.command_manager.register_command("start_capture", self._cmd_start_capture)
        self.command_manager.register_command("stop_capture", self._cmd_stop_capture)
        self.command_manager.register_command("get_parameters", self._cmd_get_parameters)
        self.command_manager.register_command("set_parameters", self._cmd_set_parameters)

        config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker(
            "grab_worker", self._grab_worker, config, auto_start=False
        )
        self.worker_manager.pause_worker("grab_worker")
        self._log_info("HikvisionCameraProcessAdapter ready")

    def _send_to_gui(self, msg_type: str, data: dict):
        msg = self._msg.data(targets=["gui"], data_type=msg_type, data=data)
        self.send_message("gui", msg.to_dict())

    def _cmd_enum_devices(self, data: dict) -> dict:
        r = self._facade.enum_devices()
        if r.get("status") == "ok" and "devices" in r:
            self._send_to_gui("enum_devices_response", {"devices": r["devices"]})
        return r

    def _cmd_open(self, data: dict) -> dict:
        idx = data.get("camera_index", self._camera_index)
        self._camera_index = idx
        return self._facade.open(idx)

    def _cmd_close(self, data: dict) -> dict:
        self._facade.close()
        self._send_to_gui("status", {"status": "Camera closed"})
        return {"status": "ok"}

    def _cmd_start_grabbing(self, data: dict) -> dict:
        r = self._facade.start_grabbing()
        if r.get("status") == "ok":
            if not self.worker_manager.is_worker_running("grab_worker"):
                self.worker_manager.start_worker("grab_worker")
            self.worker_manager.resume_worker("grab_worker")
        return r

    def _cmd_stop_grabbing(self, data: dict) -> dict:
        self._facade.stop_grabbing()
        self.worker_manager.pause_worker("grab_worker")
        return {"status": "ok"}

    def _cmd_start_capture(self, data: dict) -> dict:
        idx = data.get("camera_index", self._camera_index)
        self._camera_index = idx
        self._facade.open(idx)
        return self._cmd_start_grabbing(data)

    def _cmd_stop_capture(self, data: dict) -> dict:
        return self._cmd_stop_grabbing(data)

    def _cmd_get_parameters(self, data: dict) -> dict:
        r = self._facade.get_parameters()
        if r.get("status") == "ok" and "parameters" in r:
            self._send_to_gui("parameters_response", {"parameters": r["parameters"]})
        return r

    def _cmd_set_parameters(self, data: dict) -> dict:
        fr = data.get("frame_rate")
        exp = data.get("exposure_time")
        gain = data.get("gain")
        if None in (fr, exp, gain):
            self._send_to_gui("error", {"error": "Missing parameters"})
            return {"status": "error"}
        return self._facade.set_parameters(float(fr), float(exp), float(gain))

    def _grab_worker(self, stop_event, pause_event):
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue
            frame = self._facade.capture_frame(timeout_ms=1000)
            if frame is None:
                time.sleep(0.001)
                continue
            pixel_type = self._facade.last_pixel_type
            frame = _convert_frame_to_bgr(frame, pixel_type)
            if len(frame.shape) != 3 or frame.shape[2] != 3:
                continue
            self._frame_id = (self._frame_id + 1) % 121
            timestamp = time.time()
            frame = _resize_frame(frame, self._target_height, self._target_width)
            mm = self.memory_manager
            if mm:
                free_idx = mm.find_free_index("camera", "camera_frame")
                if free_idx is None:
                    free_idx = 0
                shm_name = mm.write_images("camera", "camera_frame", [frame], free_idx)
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

    def shutdown(self) -> bool:
        self._log_info("HikvisionCameraProcessAdapter shutting down...")
        self.worker_manager.pause_worker("grab_worker")
        self._facade.close()
        if self.memory_manager:
            self.memory_manager.close_all("camera")
        self.is_initialized = False
        return super().shutdown()
