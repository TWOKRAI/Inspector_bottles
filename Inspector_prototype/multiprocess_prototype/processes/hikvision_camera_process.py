# multiprocess_prototype/processes/hikvision_camera_process.py
"""
HikvisionCameraProcess — адаптер Hikvision SDK к multiprocess framework.

Портирован с camera_proc_2.py (Services/.../camera_process/) на новую архитектуру.
Использует SDK напрямую: MvCamera, MV_CC_* — без дублирования методов.
Owner camera_frame в SharedMemory. Отправляет frame_ready в Processor.
Команды: enum_devices, open, close, start_grabbing, stop_grabbing,
start_capture, stop_capture, get_parameters, set_parameters.
"""

import sys
import time
import threading
import ctypes
from ctypes import byref, sizeof, memset, cast, POINTER, c_ubyte
from typing import Optional

import numpy as np

from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.message_module import MessageAdapter
from multiprocess_framework.refactored.modules.worker_module import (
    ThreadConfig,
    ExecutionMode,
)

try:
    from Services.hikvision_camera.hikvision_camera.camera_process.MvCameraControl_class import (
        MvCamera,
        MV_CC_DEVICE_INFO_LIST,
        MV_CC_DEVICE_INFO,
        MV_FRAME_OUT,
        MVCC_FLOATVALUE,
        MV_GIGE_DEVICE,
        MV_USB_DEVICE,
    )
    from Services.hikvision_camera.hikvision_camera.camera_process.CameraParams_header import (
        MV_TRIGGER_MODE_OFF,
    )
    from Services.hikvision_camera.hikvision_camera.camera_process.MvErrorDefine_const import (
        MV_OK,
    )

    HIKVISION_AVAILABLE = True
except ImportError as e:
    HIKVISION_AVAILABLE = False
    _import_error = str(e)
    MvCamera = None
    MV_CC_DEVICE_INFO_LIST = None
    MV_CC_DEVICE_INFO = None
    MV_FRAME_OUT = None
    MVCC_FLOATVALUE = None
    MV_GIGE_DEVICE = None
    MV_USB_DEVICE = None
    MV_TRIGGER_MODE_OFF = None
    MV_OK = None

# PixelType_Gvsp_BayerRG8 из camera_proc_2 / PixelType_header
_PIXEL_TYPE_BAYER_RG8 = 17301513


def _buffer_copy(dst, src, size: int) -> None:
    """Копирование буфера через C memcpy. Windows: msvcrt, иначе: libc."""
    if sys.platform == "win32":
        ctypes.cdll.msvcrt.memcpy(byref(dst), src, size)
    else:
        ctypes.CDLL(None).memcpy(byref(dst), src, size)


class HikvisionCameraProcess(ProcessModule):
    """
    Процесс захвата Hikvision камеры. Owner camera_frame в SharedMemory.

    Команды: enum_devices, open, close, start_grabbing, stop_grabbing,
    get_parameters, set_parameters.
    """

    def _init_application_threads(self):
        """Инициализация: команды, grab_worker."""
        self._log_info("HikvisionCameraProcess initializing...")

        if not HIKVISION_AVAILABLE:
            self._log_error(f"Hikvision SDK not available: {_import_error}")
            return

        self._msg = MessageAdapter(sender=self.name)
        app_cfg = self.get_config("config") or {}
        self._camera_index = app_cfg.get("camera_index", 0)
        # Размер памяти camera_frame — кадр ресайзится под него (SDK может давать 1240x1624 и т.д.)
        self._target_width = app_cfg.get("hikvision_resolution_width", 1920)
        self._target_height = app_cfg.get("hikvision_resolution_height", 1080)

        self._camera = None
        self._is_open = False
        self._is_grabbing = False
        self._buf_save_image = None
        self._st_frame_info = None
        self._buf_lock = threading.Lock()
        self._frame_counter = 0
        self._frame_id = 0
        self._original_image_size = None

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

        self._log_info("HikvisionCameraProcess ready (SDK available)")

    def _send_to_gui(self, msg_type: str, data: dict):
        """Отправить сообщение в GUI."""
        msg = self._msg.data(targets=["gui"], data_type=msg_type, data=data)
        self.send_message("gui", msg.to_dict())

    def _send_status(self, text: str):
        self._send_to_gui("status", {"status": text})

    def _send_error(self, text: str):
        self._send_to_gui("error", {"error": text})

    def _cmd_enum_devices(self, data):
        if not HIKVISION_AVAILABLE:
            self._send_error("Hikvision SDK not available")
            return {}
        try:
            device_list = MV_CC_DEVICE_INFO_LIST()
            ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, device_list)
            if ret != 0:
                self._send_error(f"Enum devices failed: {ret}")
                return {}
            devices = []
            for i in range(device_list.nDeviceNum):
                mvcc = cast(
                    device_list.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)
                ).contents
                info = {
                    "index": i,
                    "type": "Unknown",
                    "user_name": "",
                    "model_name": "",
                    "serial": "",
                }
                try:
                    if mvcc.nTLayerType == MV_GIGE_DEVICE:
                        info["type"] = "GigE"
                        try:
                            info["user_name"] = ctypes.cast(
                                mvcc.SpecialInfo.stGigEInfo.chUserDefinedName,
                                ctypes.c_char_p,
                            ).value.decode("gbk", errors="replace")
                        except Exception:
                            info["user_name"] = ""
                        try:
                            info["model_name"] = ctypes.cast(
                                mvcc.SpecialInfo.stGigEInfo.chModelName,
                                ctypes.c_char_p,
                            ).value.decode("gbk", errors="replace")
                        except Exception:
                            info["model_name"] = ""
                        nip = mvcc.SpecialInfo.stGigEInfo.nCurrentIp
                        info["serial"] = (
                            f"{(nip >> 24) & 0xff}.{(nip >> 16) & 0xff}."
                            f"{(nip >> 8) & 0xff}.{nip & 0xff}"
                        )
                        info["display_name"] = (
                            f"[{i}] GigE: {info['user_name']} {info['model_name']} "
                            f"({info['serial']})"
                        )
                    elif mvcc.nTLayerType == MV_USB_DEVICE:
                        info["type"] = "USB"
                        try:
                            info["user_name"] = ctypes.cast(
                                mvcc.SpecialInfo.stUsb3VInfo.chUserDefinedName,
                                ctypes.c_char_p,
                            ).value.decode("gbk", errors="replace")
                        except Exception:
                            info["user_name"] = ""
                        try:
                            info["model_name"] = ctypes.cast(
                                mvcc.SpecialInfo.stUsb3VInfo.chModelName,
                                ctypes.c_char_p,
                            ).value.decode("gbk", errors="replace")
                        except Exception:
                            info["model_name"] = ""
                        serial = "".join(
                            chr(b)
                            for b in mvcc.SpecialInfo.stUsb3VInfo.chSerialNumber
                            if b
                        )
                        info["serial"] = serial
                        info["display_name"] = (
                            f"[{i}] USB: {info['user_name']} {info['model_name']} "
                            f"({serial})"
                        )
                except Exception:
                    info["display_name"] = f"[{i}] Unknown"
                devices.append(info)
            self._send_to_gui("enum_devices_response", {"devices": devices})
            return {"status": "ok"}
        except Exception as e:
            self._send_error(f"Enum devices exception: {str(e)}")
            return {"status": "error"}

    def _cmd_open(self, data):
        if not HIKVISION_AVAILABLE:
            self._send_error("Hikvision SDK not available")
            return {}
        idx = data.get("camera_index", self._camera_index)
        self._camera_index = idx
        if self._is_open:
            self._send_status("Camera already open")
            return {"status": "ok"}
        try:
            device_list = MV_CC_DEVICE_INFO_LIST()
            ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, device_list)
            if ret != 0 or device_list.nDeviceNum == 0:
                self._send_error("No cameras found")
                return {"status": "error"}
            if idx >= device_list.nDeviceNum:
                self._send_error(f"Camera index {idx} not available")
                return {"status": "error"}
            st_dev = cast(
                device_list.pDeviceInfo[idx], POINTER(MV_CC_DEVICE_INFO)
            ).contents
            self._camera = MvCamera()
            ret = self._camera.MV_CC_CreateHandle(st_dev)
            if ret != 0:
                self._send_error(f"Create handle failed: {ret}")
                return {"status": "error"}
            ret = self._camera.MV_CC_OpenDevice()
            if ret != 0:
                self._camera.MV_CC_DestroyHandle()
                self._send_error(f"Open device failed: {ret}")
                return {"status": "error"}
            if st_dev.nTLayerType == MV_GIGE_DEVICE:
                n_pkt = self._camera.MV_CC_GetOptimalPacketSize()
                if int(n_pkt) > 0:
                    self._camera.MV_CC_SetIntValue("GevSCPSPacketSize", n_pkt)
            self._camera.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
            self._camera.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
            self._is_open = True
            self._send_status("Camera opened successfully")
            return {"status": "ok"}
        except Exception as e:
            self._send_error(f"Open camera failed: {str(e)}")
            return {"status": "error"}

    def _cmd_close(self, data):
        try:
            if self._is_grabbing:
                self._cmd_stop_grabbing({})
            if self._is_open and self._camera:
                self._camera.MV_CC_CloseDevice()
                self._camera.MV_CC_DestroyHandle()
                self._camera = None
                self._is_open = False
            self._send_status("Camera closed")
            return {"status": "ok"}
        except Exception as e:
            self._send_error(f"Close camera failed: {str(e)}")
            return {"status": "error"}

    def _cmd_start_grabbing(self, data):
        if not self._is_open or not self._camera:
            self._send_error("Camera not open")
            return {"status": "error"}
        if self._is_grabbing:
            self._send_status("Already grabbing")
            return {"status": "ok"}
        try:
            ret = self._camera.MV_CC_StartGrabbing()
            if ret != 0:
                self._send_error(f"Start grabbing failed: {ret}")
                return {"status": "error"}
            self._is_grabbing = True

            if not self.worker_manager.is_worker_running("grab_worker"):
                self.worker_manager.start_worker("grab_worker")
            self.worker_manager.resume_worker("grab_worker")
            self._send_status("Grabbing started")
            return {"status": "ok"}
        except Exception as e:
            self._send_error(f"Start grabbing failed: {str(e)}")
            return {"status": "error"}

    def _cmd_stop_grabbing(self, data):
        try:
            if not self._is_grabbing:
                self._send_status("Not grabbing")
                return {"status": "ok"}
            self.worker_manager.pause_worker("grab_worker")
            if self._is_open and self._camera:
                self._camera.MV_CC_StopGrabbing()
            self._is_grabbing = False
            self._send_status("Grabbing stopped")
            return {"status": "ok"}
        except Exception as e:
            self._send_error(f"Stop grabbing failed: {str(e)}")
            return {"status": "error"}

    def _cmd_start_capture(self, data):
        """Совместимость с GUI: Start → open (если нужно) + start_grabbing."""
        if not self._is_open:
            r = self._cmd_open({"camera_index": self._camera_index})
            if r.get("status") == "error":
                return r
        return self._cmd_start_grabbing(data)

    def _cmd_stop_capture(self, data):
        """Совместимость с GUI: Stop → stop_grabbing."""
        return self._cmd_stop_grabbing(data)

    def _cmd_get_parameters(self, data):
        if not self._is_open or not self._camera:
            self._send_error("Camera not open")
            return {}
        try:
            st_fr = MVCC_FLOATVALUE()
            memset(byref(st_fr), 0, sizeof(st_fr))
            st_exp = MVCC_FLOATVALUE()
            memset(byref(st_exp), 0, sizeof(st_exp))
            st_gain = MVCC_FLOATVALUE()
            memset(byref(st_gain), 0, sizeof(st_gain))
            if self._camera.MV_CC_GetFloatValue("AcquisitionFrameRate", st_fr) != 0:
                self._send_error("Get frame rate failed")
                return {}
            if self._camera.MV_CC_GetFloatValue("ExposureTime", st_exp) != 0:
                self._send_error("Get exposure failed")
                return {}
            if self._camera.MV_CC_GetFloatValue("Gain", st_gain) != 0:
                self._send_error("Get gain failed")
                return {}
            params = {
                "frame_rate": st_fr.fCurValue,
                "exposure_time": st_exp.fCurValue,
                "gain": st_gain.fCurValue,
            }
            self._send_to_gui("parameters_response", {"parameters": params})
            return {"status": "ok"}
        except Exception as e:
            self._send_error(f"Get parameters failed: {str(e)}")
            return {}

    def _cmd_set_parameters(self, data):
        if not self._is_open or not self._camera:
            self._send_error("Camera not open")
            return {}
        fr = data.get("frame_rate")
        exp = data.get("exposure_time")
        gain = data.get("gain")
        if None in (fr, exp, gain):
            self._send_error("Missing parameters")
            return {}
        try:
            self._camera.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
            self._camera.MV_CC_SetEnumValue("ExposureAuto", 0)
            time.sleep(0.2)
            if self._camera.MV_CC_SetFloatValue("ExposureTime", float(exp)) != 0:
                self._send_error("Set exposure failed")
                return {}
            if self._camera.MV_CC_SetFloatValue("Gain", float(gain)) != 0:
                self._send_error("Set gain failed")
                return {}
            if (
                self._camera.MV_CC_SetFloatValue(
                    "AcquisitionFrameRate", float(fr)
                )
                != 0
            ):
                self._send_error("Set frame rate failed")
                return {}
            self._send_status("Parameters set successfully")
            return {"status": "ok"}
        except Exception as e:
            self._send_error(f"Set parameters failed: {str(e)}")
            return {}

    def _grab_worker(self, stop_event, pause_event):
        """Цикл захвата кадров через Hikvision SDK."""
        if not HIKVISION_AVAILABLE:
            while not stop_event.is_set():
                time.sleep(0.1)
            return
        st_out = MV_FRAME_OUT()
        memset(byref(st_out), 0, sizeof(st_out))
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue
            if not self._is_grabbing:
                time.sleep(0.05)
                continue
            try:
                ret = self._camera.MV_CC_GetImageBuffer(st_out, 1000)
                if ret != 0:
                    time.sleep(0.001)
                    continue
                if self._buf_save_image is None:
                    self._buf_save_image = (c_ubyte * st_out.stFrameInfo.nFrameLen)()
                self._st_frame_info = st_out.stFrameInfo
                self._buf_lock.acquire()
                try:
                    _buffer_copy(
                        self._buf_save_image,
                        st_out.pBufAddr,
                        self._st_frame_info.nFrameLen,
                    )
                finally:
                    self._buf_lock.release()
                frame = np.array(self._buf_save_image)
                h, w = self._st_frame_info.nHeight, self._st_frame_info.nWidth
                pixel_type = self._st_frame_info.enPixelType
                if len(frame.shape) == 1:
                    frame = frame.reshape(h, w)
                    if pixel_type == _PIXEL_TYPE_BAYER_RG8:
                        try:
                            import cv2

                            frame = cv2.cvtColor(frame, cv2.COLOR_BayerRG2RGB)
                            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                        except Exception:
                            pass
                if len(frame.shape) == 2:
                    try:
                        import cv2

                        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    except Exception:
                        self._camera.MV_CC_FreeImageBuffer(st_out)
                        continue
                elif len(frame.shape) == 3 and frame.shape[2] == 4:
                    try:
                        import cv2

                        frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2RGB)
                        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    except Exception:
                        self._camera.MV_CC_FreeImageBuffer(st_out)
                        continue
                if len(frame.shape) != 3 or frame.shape[2] != 3:
                    self._camera.MV_CC_FreeImageBuffer(st_out)
                    continue
                self._camera.MV_CC_FreeImageBuffer(st_out)
                self._frame_counter += 1
                self._frame_id = (self._frame_id + 1) % 121
                timestamp = time.time()
                if self._original_image_size is None:
                    self._original_image_size = (frame.shape[0], frame.shape[1])
                    self._send_to_gui(
                        "image_size",
                        {"height": frame.shape[0], "width": frame.shape[1]},
                    )
                # Ресайз под camera_frame (pack требует h<=max_h, w<=max_w; SDK даёт 1240x1624 и т.д.)
                if (
                    frame.shape[0] != self._target_height
                    or frame.shape[1] != self._target_width
                ):
                    try:
                        import cv2

                        frame = cv2.resize(
                            frame,
                            (self._target_width, self._target_height),
                            interpolation=cv2.INTER_LINEAR,
                        )
                    except ImportError:
                        pass  # без cv2 — запись может упасть при несовпадении размера
                mm = self.memory_manager
                if not mm and self._frame_counter <= 3:
                    self._log_warning("[Hikvision] memory_manager is None, cannot write frames")
                if mm:
                    free_idx = mm.find_free_index("camera", "camera_frame")
                    if free_idx is None:
                        free_idx = 0
                    shm_name = mm.write_images(
                        "camera", "camera_frame", [frame], free_idx
                    )
                    if not shm_name and self._frame_counter <= 5:
                        self._log_warning(
                            f"[Hikvision] write_images returned None (frame={self._frame_counter}), "
                            "check camera_frame memory init"
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
                        if self._frame_counter <= 3 or self._frame_counter % 50 == 0:
                            self._log_info(
                                f"[Hikvision] frame_ready sent to processor frame_id={self._frame_id}"
                            )
            except Exception as e:
                self._log_error(f"Grab loop error: {e}")
                time.sleep(0.01)

    def shutdown(self) -> bool:
        self._log_info("HikvisionCameraProcess shutting down...")
        if self._is_grabbing and self.worker_manager:
            self.worker_manager.pause_worker("grab_worker")
        if self._is_open and self._camera:
            try:
                self._camera.MV_CC_StopGrabbing()
                self._camera.MV_CC_CloseDevice()
                self._camera.MV_CC_DestroyHandle()
            except Exception:
                pass
            self._camera = None
            self._is_open = False
        if self.memory_manager:
            self.memory_manager.close_all("camera")
        self.is_initialized = False
        return super().shutdown()
