"""UnifiedCameraProcess — unified camera with switchable backends."""

import sys
import threading
import time

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.message_module import MessageAdapter
from multiprocess_framework.modules.worker_module import ThreadConfig, ExecutionMode

from Utils.fps_module import FrameFPS

from multiprocess_prototype_v3.registers.camera import (
    CAMERA_TYPES,
    DEFAULT_CAMERA_TYPE,
    SUPPORTS_ENUM,
)
from multiprocess_prototype_v3.registers import CAMERA_REGISTER
from multiprocess_prototype_v3.services.camera.backends import (
    CameraBackendParams,
    create_camera_backend,
)
from multiprocess_prototype_v3.app_config import CAMERA_SHM_HEIGHT, CAMERA_SHM_WIDTH
from multiprocess_prototype_v3.shared.frame_io import message_as_dict
from multiprocess_prototype_v3.shared.register_sync import apply_register_update


def _resize_frame_for_shm(frame, target_h: int, target_w: int):
    """Resize frame to SHM buffer size."""
    if frame.shape[0] == target_h and frame.shape[1] == target_w:
        return frame
    try:
        import cv2
        return cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
    except ImportError:
        return frame


class UnifiedCameraProcess(ProcessModule):
    """Unified camera process. Switches simulator/webcam/hikvision without restart."""

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
        self._hikvision_frame_rate = float(app_cfg.get("hikvision_frame_rate", 25.0))
        self._hikvision_exposure_time = float(app_cfg.get("hikvision_exposure_time", 10000.0))
        self._hikvision_gain = float(app_cfg.get("hikvision_gain", 0.0))
        self._simulator_image_path = app_cfg.get("simulator_image_path")

        self._backend_lock = threading.Lock()
        self._frame_id = 0
        self._fps_counter = FrameFPS(interval=1.0)

        initial_type = app_cfg.get("camera_type", DEFAULT_CAMERA_TYPE)
        if initial_type not in CAMERA_TYPES:
            initial_type = DEFAULT_CAMERA_TYPE
        self._current_type = initial_type

        self._handoff_camera_backend(DEFAULT_CAMERA_TYPE, initial_type)
        self._backend = self._create_backend(initial_type)

        # Register commands
        for cmd, handler in {
            "set_camera_type": self._cmd_set_camera_type,
            "get_camera_type": self._cmd_get_camera_type,
            "start_capture": self._cmd_start_capture,
            "stop_capture": self._cmd_stop_capture,
            "set_fps": self._cmd_set_fps,
            "set_resolution": self._cmd_set_resolution,
            "enum_devices": self._cmd_enum_devices,
            "open": self._cmd_open,
            "close": self._cmd_close,
            "start_grabbing": self._cmd_start_grabbing,
            "stop_grabbing": self._cmd_stop_grabbing,
            "get_parameters": self._cmd_get_parameters,
            "set_parameters": self._cmd_set_parameters,
            "set_device_id": self._cmd_set_device_id,
            "set_camera_index": self._cmd_set_camera_index,
            "set_hikvision_resolution": self._cmd_set_hikvision_resolution,
        }.items():
            self.command_manager.register_command(cmd, handler)

        config = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        self.worker_manager.create_worker("capture_worker", self._capture_worker, config, auto_start=False)
        self.worker_manager.pause_worker("capture_worker")

        self._log_info(f"UnifiedCameraProcess ready, camera_type={initial_type}")

    # --- Register sync handlers ---
    def _build_register_handlers(self) -> dict:
        return {
            "camera_type": lambda v: self._cmd_set_camera_type({"camera_type": v}),
            "fps": lambda v: self._cmd_set_fps({"fps": v}),
            "resolution_width": lambda v: self._cmd_set_resolution({"width": v}),
            "resolution_height": lambda v: self._cmd_set_resolution({"height": v}),
            "device_id": lambda v: self._cmd_set_device_id({"device_id": v}),
            "camera_index": lambda v: self._cmd_set_camera_index({"camera_index": v}),
            "hikvision_resolution_width": lambda v: self._cmd_set_hikvision_resolution({"width": v}),
            "hikvision_resolution_height": lambda v: self._cmd_set_hikvision_resolution({"height": v}),
            "hikvision_frame_rate": lambda v: self._patch_hikvision_register_params({"frame_rate": v}),
            "hikvision_exposure_time": lambda v: self._patch_hikvision_register_params({"exposure_time": v}),
            "hikvision_gain": lambda v: self._patch_hikvision_register_params({"gain": v}),
        }

    def _send_to_gui(self, msg_type: str, data: dict):
        msg = self._msg.data(targets=["gui"], data_type=msg_type, data=data)
        self.send_message("gui", msg.to_dict())

    def _backend_params(self) -> CameraBackendParams:
        return CameraBackendParams(
            width=self._width, height=self._height,
            device_id=self._device_id, camera_index=self._camera_index,
            hikvision_width=self._hikvision_width, hikvision_height=self._hikvision_height,
            simulator_image_path=self._simulator_image_path,
            send_to_gui=self._send_to_gui,
        )

    def _create_backend(self, camera_type: str):
        return create_camera_backend(camera_type, self._backend_params())

    def _handoff_camera_backend(self, old_type: str, new_type: str) -> None:
        if old_type == "webcam":
            from multiprocess_prototype_v3.services.camera.backends import _reset_webcam
            _reset_webcam(device_id=self._device_id, delay_after_ms=450)
        elif old_type == "hikvision":
            time.sleep(0.28)
        if new_type == "webcam":
            from multiprocess_prototype_v3.services.camera.backends import _reset_webcam
            _reset_webcam(device_id=self._device_id, delay_after_ms=300)
            time.sleep(0.1)

    def _cmd_set_camera_type(self, data: dict):
        new_type = data.get("camera_type", DEFAULT_CAMERA_TYPE)
        if new_type not in CAMERA_TYPES:
            return {"status": "error", "error": f"Unknown camera_type: {new_type}"}
        if new_type == "hikvision" and sys.platform != "win32":
            new_type = "simulator"
            self._send_to_gui("status", {"status": "Hikvision only on Windows, using Simulator"})
        with self._backend_lock:
            if self._current_type == new_type:
                self._send_to_gui("status", {"status": f"Already {new_type}"})
                return {"status": "ok"}
            old_type = self._current_type
            self.worker_manager.pause_worker("capture_worker")
            self._backend.stop()
            self._backend.close()
            self._handoff_camera_backend(old_type, new_type)
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
        if self.worker_manager:
            self.worker_manager.pause_worker("capture_worker")
        time.sleep(0.05)
        self._fps_counter.reset()
        self._send_to_gui("fps_update", {"fps": 0})
        with self._backend_lock:
            if self._current_type == "hikvision":
                result = self._backend.handle_command("stop_grabbing", data)
            else:
                self._backend.stop()
                if self._current_type == "webcam":
                    self._backend.close()
                result = {"status": "ok"}
        return result or {"status": "ok"}

    def _cmd_set_fps(self, data: dict):
        self._fps = max(1, min(120, data.get("fps", self._fps)))
        return {"status": "ok", "fps": self._fps}

    def _cmd_set_resolution(self, data: dict):
        self._width = data.get("width", self._width)
        self._height = data.get("height", self._height)
        if self._current_type in ("simulator", "webcam"):
            with self._backend_lock:
                self._backend.close()
                self._backend = self._create_backend(self._current_type)
        return {"status": "ok"}

    def _cmd_set_device_id(self, data: dict):
        self._device_id = data.get("device_id", self._device_id)
        return {"status": "ok", "device_id": self._device_id}

    def _cmd_set_camera_index(self, data: dict):
        self._camera_index = data.get("camera_index", self._camera_index)
        return {"status": "ok", "camera_index": self._camera_index}

    def _patch_hikvision_register_params(self, partial: dict) -> None:
        if "frame_rate" in partial:
            self._hikvision_frame_rate = float(partial["frame_rate"])
        if "exposure_time" in partial:
            self._hikvision_exposure_time = float(partial["exposure_time"])
        if "gain" in partial:
            self._hikvision_gain = float(partial["gain"])
        with self._backend_lock:
            if self._current_type == "hikvision":
                self._backend.handle_command("set_parameters", {
                    "frame_rate": self._hikvision_frame_rate,
                    "exposure_time": self._hikvision_exposure_time,
                    "gain": self._hikvision_gain,
                })

    def _cmd_set_hikvision_resolution(self, data: dict):
        self._hikvision_width = data.get("width", self._hikvision_width)
        self._hikvision_height = data.get("height", self._hikvision_height)
        return {"status": "ok"}

    def _cmd_enum_devices(self, data: dict):
        payload = dict(data or {})
        backend_hint = payload.get("backend")
        use_backend = backend_hint if backend_hint in ("webcam", "hikvision") else None
        with self._backend_lock:
            effective_type = use_backend or self._current_type
            if effective_type not in SUPPORTS_ENUM:
                self._send_to_gui("enum_devices_response", {"devices": []})
                return {"status": "ok", "devices": []}
            if use_backend and use_backend != self._current_type:
                result = self._enum_devices_for_backend(use_backend, payload)
            else:
                result = self._backend.handle_command("enum_devices", payload) or {}
            if isinstance(result, dict) and result.get("status") == "ok" and "devices" in result:
                self._send_to_gui("enum_devices_response", {"devices": result["devices"]})
            return result

    def _enum_devices_for_backend(self, backend: str, payload: dict) -> dict:
        if backend == "hikvision":
            if self._current_type == "webcam":
                self.worker_manager.pause_worker("capture_worker")
                try:
                    self._backend.stop()
                    self._backend.close()
                except Exception:
                    pass
                self._handoff_camera_backend("webcam", "hikvision")
            from hikvision_camera_module.core.capture import enum_devices
            result = enum_devices() or {}
            if isinstance(result, dict) and result.get("status") == "ok":
                for dev in result.get("devices") or []:
                    if isinstance(dev, dict):
                        dev.setdefault("source", "hikvision")
            if self._current_type == "webcam":
                self._handoff_camera_backend("hikvision", "webcam")
                self._backend = self._create_backend("webcam")
                self.worker_manager.resume_worker("capture_worker")
            return result
        if backend == "webcam":
            from multiprocess_prototype_v3.services.camera.backends import _enum_webcam_devices
            return _enum_webcam_devices(payload.get("max_index"))
        return {"status": "error", "devices": []}

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
        register_handlers = self._build_register_handlers()
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue

            msg = self.receive_message(timeout=0, channel_types=["data"])
            if msg:
                msg_dict = message_as_dict(msg)
                if msg_dict.get("data_type") == "register_update":
                    apply_register_update(msg_dict.get("data") or {}, CAMERA_REGISTER, register_handlers)
                    continue

            frame_start = time.perf_counter()
            with self._backend_lock:
                backend = self._backend
            frame = backend.capture_frame()
            if frame is None:
                time.sleep(0.01)
                continue

            self._frame_id = (self._frame_id + 1) % 121
            timestamp = time.time()
            frame = _resize_frame_for_shm(frame, CAMERA_SHM_HEIGHT, CAMERA_SHM_WIDTH)

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
                    fps = self._fps_counter.update()
                    if fps > 0:
                        self._send_to_gui("fps_update", {"fps": fps})

            if self._current_type != "hikvision":
                elapsed = time.perf_counter() - frame_start
                target_interval = 1.0 / max(1, self._fps)
                sleep_time = target_interval - elapsed
                if sleep_time > 0.001:
                    time.sleep(sleep_time)

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
            if self._current_type == "webcam":
                from multiprocess_prototype_v3.services.camera.backends import _reset_webcam
                _reset_webcam(device_id=self._device_id)
        if self.memory_manager:
            self.memory_manager.close_all("camera")
        self.is_initialized = False
        return super().shutdown()
