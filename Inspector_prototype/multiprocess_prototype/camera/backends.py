# multiprocess_prototype/camera/backends.py
"""
Бэкенды захвата кадров: Simulator, Webcam, Hikvision.

Единый интерфейс: capture_frame() -> np.ndarray | None, start(), stop(), close().
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

import numpy as np


class BaseCaptureBackend(ABC):
    """Базовый класс бэкенда захвата."""

    @abstractmethod
    def capture_frame(self) -> Optional[np.ndarray]:
        """Захватить кадр. None = пропуск (например, нет захвата)."""
        pass

    def start(self) -> None:
        """Начать захват."""
        pass

    def stop(self) -> None:
        """Остановить захват."""
        pass

    def close(self) -> None:
        """Освободить ресурсы."""
        pass

    def handle_command(self, cmd: str, data: dict) -> Optional[dict]:
        """Обработать команду (backend-specific). None = не обработано."""
        return None


class SimulatorBackend(BaseCaptureBackend):
    """Имитация: FrameGenerator."""

    def __init__(self, width: int, height: int, image_path: Optional[str] = None):
        from multiprocess_prototype.utils.frame_generator import FrameGenerator

        self._generator = FrameGenerator(width, height, image_path=image_path)
        self._running = False

    def capture_frame(self) -> Optional[np.ndarray]:
        if not self._running:
            return None
        return self._generator.generate_frame()

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def close(self) -> None:
        self._running = False
        if hasattr(self._generator, "close"):
            self._generator.close()


class WebcamBackend(BaseCaptureBackend):
    """Веб-камера: WebcamCapture."""

    def __init__(self, width: int, height: int, device_id: int = 0):
        from multiprocess_prototype.utils.webcam_capture import WebcamCapture

        self._generator: Optional[WebcamCapture] = None
        self._width = width
        self._height = height
        self._device_id = device_id
        self._running = False
        try:
            self._generator = WebcamCapture(width, height, device_id=device_id)
        except (ImportError, RuntimeError):
            self._generator = None

    def capture_frame(self) -> Optional[np.ndarray]:
        if not self._running or not self._generator:
            return None
        return self._generator.generate_frame()

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def close(self) -> None:
        self._running = False
        if self._generator and hasattr(self._generator, "close"):
            self._generator.close()
        self._generator = None


class HikvisionBackend(BaseCaptureBackend):
    """Hikvision SDK: MvCamera."""

    def __init__(
        self,
        camera_index: int,
        target_width: int,
        target_height: int,
        send_to_gui: Callable[[str, dict], None],
    ):
        self._camera_index = camera_index
        self._target_width = target_width
        self._target_height = target_height
        self._send_to_gui = send_to_gui
        self._camera = None
        self._is_open = False
        self._is_grabbing = False
        self._buf_save_image = None
        self._st_frame_info = None
        self._buf_lock = __import__("threading").Lock()
        self._frame_id = 0
        self._original_image_size = None
        self._import_sdk()

    def _import_sdk(self) -> bool:
        self._sdk = None
        try:
            import sys
            import ctypes
            from ctypes import byref, sizeof, memset, cast, POINTER, c_ubyte

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

            self._MvCamera = MvCamera
            self._MV_CC_DEVICE_INFO_LIST = MV_CC_DEVICE_INFO_LIST
            self._MV_CC_DEVICE_INFO = MV_CC_DEVICE_INFO
            self._MV_FRAME_OUT = MV_FRAME_OUT
            self._MVCC_FLOATVALUE = MVCC_FLOATVALUE
            self._MV_GIGE_DEVICE = MV_GIGE_DEVICE
            self._MV_USB_DEVICE = MV_USB_DEVICE
            self._MV_TRIGGER_MODE_OFF = MV_TRIGGER_MODE_OFF
            self._ctypes = ctypes
            self._byref = byref
            self._sizeof = sizeof
            self._memset = memset
            self._cast = cast
            self._POINTER = POINTER
            self._c_ubyte = c_ubyte
            self._PIXEL_TYPE_BAYER_RG8 = 17301513

            def _buffer_copy(dst, src, size):
                if sys.platform == "win32":
                    ctypes.cdll.msvcrt.memcpy(byref(dst), src, size)
                else:
                    ctypes.CDLL(None).memcpy(byref(dst), src, size)

            self._buffer_copy = _buffer_copy
            self._sdk = True
            return True
        except ImportError as e:
            self._send_to_gui("error", {"error": f"Hikvision SDK not available: {e}"})
            return False

    def _open(self) -> bool:
        if not self._sdk or self._is_open:
            return self._is_open
        try:
            device_list = self._MV_CC_DEVICE_INFO_LIST()
            ret = self._MvCamera.MV_CC_EnumDevices(
                self._MV_GIGE_DEVICE | self._MV_USB_DEVICE, device_list
            )
            if ret != 0 or device_list.nDeviceNum == 0:
                self._send_to_gui("error", {"error": "No cameras found"})
                return False
            if self._camera_index >= device_list.nDeviceNum:
                self._send_to_gui("error", {"error": f"Camera index {self._camera_index} not available"})
                return False
            st_dev = self._cast(
                device_list.pDeviceInfo[self._camera_index],
                self._POINTER(self._MV_CC_DEVICE_INFO),
            ).contents
            self._camera = self._MvCamera()
            ret = self._camera.MV_CC_CreateHandle(st_dev)
            if ret != 0:
                self._send_to_gui("error", {"error": f"Create handle failed: {ret}"})
                return False
            ret = self._camera.MV_CC_OpenDevice()
            if ret != 0:
                self._camera.MV_CC_DestroyHandle()
                self._send_to_gui("error", {"error": f"Open device failed: {ret}"})
                return False
            if st_dev.nTLayerType == self._MV_GIGE_DEVICE:
                n_pkt = self._camera.MV_CC_GetOptimalPacketSize()
                if int(n_pkt) > 0:
                    self._camera.MV_CC_SetIntValue("GevSCPSPacketSize", n_pkt)
            self._camera.MV_CC_SetEnumValue("TriggerMode", self._MV_TRIGGER_MODE_OFF)
            self._camera.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
            self._is_open = True
            self._send_to_gui("status", {"status": "Camera opened successfully"})
            return True
        except Exception as e:
            self._send_to_gui("error", {"error": f"Open camera failed: {e}"})
            return False

    def _close(self) -> None:
        if self._is_grabbing and self._camera:
            self._camera.MV_CC_StopGrabbing()
        if self._is_open and self._camera:
            self._camera.MV_CC_CloseDevice()
            self._camera.MV_CC_DestroyHandle()
            self._camera = None
            self._is_open = False
        self._is_grabbing = False

    def capture_frame(self) -> Optional[np.ndarray]:
        if not self._sdk or not self._camera or not self._is_grabbing:
            return None
        try:
            st_out = self._MV_FRAME_OUT()
            self._memset(self._byref(st_out), 0, self._sizeof(st_out))
            ret = self._camera.MV_CC_GetImageBuffer(st_out, 1000)
            if ret != 0:
                return None
            if self._buf_save_image is None:
                self._buf_save_image = (
                    self._c_ubyte * st_out.stFrameInfo.nFrameLen
                )()
            self._st_frame_info = st_out.stFrameInfo
            self._buf_lock.acquire()
            try:
                self._buffer_copy(
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
                if pixel_type == self._PIXEL_TYPE_BAYER_RG8:
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
                    return None
            elif len(frame.shape) == 3 and frame.shape[2] == 4:
                try:
                    import cv2
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2RGB)
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                except Exception:
                    self._camera.MV_CC_FreeImageBuffer(st_out)
                    return None
            if len(frame.shape) != 3 or frame.shape[2] != 3:
                self._camera.MV_CC_FreeImageBuffer(st_out)
                return None
            self._camera.MV_CC_FreeImageBuffer(st_out)
            self._frame_id = (self._frame_id + 1) % 121
            if self._original_image_size is None:
                self._original_image_size = (frame.shape[0], frame.shape[1])
                self._send_to_gui(
                    "image_size",
                    {"height": frame.shape[0], "width": frame.shape[1]},
                )
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
                    pass
            return frame
        except Exception:
            return None

    def start(self) -> None:
        if not self._sdk:
            return
        if not self._is_open:
            self._open()
        if self._is_open and self._camera:
            ret = self._camera.MV_CC_StartGrabbing()
            if ret == 0:
                self._is_grabbing = True
                self._send_to_gui("status", {"status": "Grabbing started"})
            else:
                self._send_to_gui("error", {"error": f"Start grabbing failed: {ret}"})

    def stop(self) -> None:
        if self._is_grabbing and self._camera:
            self._camera.MV_CC_StopGrabbing()
        self._is_grabbing = False
        self._send_to_gui("status", {"status": "Grabbing stopped"})

    def close(self) -> None:
        self._close()

    def handle_command(self, cmd: str, data: dict) -> Optional[dict]:
        if not self._sdk:
            return {"status": "error"}
        if cmd == "enum_devices":
            return self._cmd_enum_devices(data)
        if cmd == "open":
            return self._cmd_open(data)
        if cmd == "close":
            return self._cmd_close(data)
        if cmd == "start_grabbing":
            return self._cmd_start_grabbing(data)
        if cmd == "stop_grabbing":
            return self._cmd_stop_grabbing(data)
        if cmd == "get_parameters":
            return self._cmd_get_parameters(data)
        if cmd == "set_parameters":
            return self._cmd_set_parameters(data)
        return None

    def _cmd_open(self, data: dict) -> dict:
        idx = data.get("camera_index", self._camera_index)
        self._camera_index = idx
        if self._is_open:
            self._send_to_gui("status", {"status": "Camera already open"})
            return {"status": "ok"}
        return {"status": "ok" if self._open() else "error"}

    def _cmd_close(self, data: dict) -> dict:
        self._close()
        self._send_to_gui("status", {"status": "Camera closed"})
        return {"status": "ok"}

    def _cmd_start_grabbing(self, data: dict) -> dict:
        if not self._is_open:
            self._open()
        if self._is_open:
            self.start()
        return {"status": "ok"}

    def _cmd_stop_grabbing(self, data: dict) -> dict:
        self.stop()
        return {"status": "ok"}

    def _cmd_enum_devices(self, data: dict) -> dict:
        try:
            device_list = self._MV_CC_DEVICE_INFO_LIST()
            ret = self._MvCamera.MV_CC_EnumDevices(
                self._MV_GIGE_DEVICE | self._MV_USB_DEVICE, device_list
            )
            if ret != 0:
                self._send_to_gui("error", {"error": f"Enum devices failed: {ret}"})
                return {"status": "error"}
            devices = []
            for i in range(device_list.nDeviceNum):
                mvcc = self._cast(
                    device_list.pDeviceInfo[i],
                    self._POINTER(self._MV_CC_DEVICE_INFO),
                ).contents
                info = {
                    "index": i,
                    "type": "Unknown",
                    "user_name": "",
                    "model_name": "",
                    "serial": "",
                }
                try:
                    if mvcc.nTLayerType == self._MV_GIGE_DEVICE:
                        info["type"] = "GigE"
                        try:
                            info["user_name"] = self._ctypes.cast(
                                mvcc.SpecialInfo.stGigEInfo.chUserDefinedName,
                                self._ctypes.c_char_p,
                            ).value.decode("gbk", errors="replace")
                        except Exception:
                            pass
                        try:
                            info["model_name"] = self._ctypes.cast(
                                mvcc.SpecialInfo.stGigEInfo.chModelName,
                                self._ctypes.c_char_p,
                            ).value.decode("gbk", errors="replace")
                        except Exception:
                            pass
                        nip = mvcc.SpecialInfo.stGigEInfo.nCurrentIp
                        info["serial"] = (
                            f"{(nip >> 24) & 0xff}.{(nip >> 16) & 0xff}."
                            f"{(nip >> 8) & 0xff}.{nip & 0xff}"
                        )
                        info["display_name"] = (
                            f"[{i}] GigE: {info['user_name']} {info['model_name']} "
                            f"({info['serial']})"
                        )
                    elif mvcc.nTLayerType == self._MV_USB_DEVICE:
                        info["type"] = "USB"
                        try:
                            info["user_name"] = self._ctypes.cast(
                                mvcc.SpecialInfo.stUsb3VInfo.chUserDefinedName,
                                self._ctypes.c_char_p,
                            ).value.decode("gbk", errors="replace")
                        except Exception:
                            pass
                        try:
                            info["model_name"] = self._ctypes.cast(
                                mvcc.SpecialInfo.stUsb3VInfo.chModelName,
                                self._ctypes.c_char_p,
                            ).value.decode("gbk", errors="replace")
                        except Exception:
                            pass
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
            self._send_to_gui("error", {"error": f"Enum devices exception: {e}"})
            return {"status": "error"}

    def _cmd_get_parameters(self, data: dict) -> dict:
        if not self._is_open or not self._camera:
            self._send_to_gui("error", {"error": "Camera not open"})
            return {}
        try:
            st_fr = self._MVCC_FLOATVALUE()
            self._memset(self._byref(st_fr), 0, self._sizeof(st_fr))
            st_exp = self._MVCC_FLOATVALUE()
            self._memset(self._byref(st_exp), 0, self._sizeof(st_exp))
            st_gain = self._MVCC_FLOATVALUE()
            self._memset(self._byref(st_gain), 0, self._sizeof(st_gain))
            if self._camera.MV_CC_GetFloatValue("AcquisitionFrameRate", st_fr) != 0:
                self._send_to_gui("error", {"error": "Get frame rate failed"})
                return {}
            if self._camera.MV_CC_GetFloatValue("ExposureTime", st_exp) != 0:
                self._send_to_gui("error", {"error": "Get exposure failed"})
                return {}
            if self._camera.MV_CC_GetFloatValue("Gain", st_gain) != 0:
                self._send_to_gui("error", {"error": "Get gain failed"})
                return {}
            params = {
                "frame_rate": st_fr.fCurValue,
                "exposure_time": st_exp.fCurValue,
                "gain": st_gain.fCurValue,
            }
            self._send_to_gui("parameters_response", {"parameters": params})
            return {"status": "ok"}
        except Exception as e:
            self._send_to_gui("error", {"error": f"Get parameters failed: {e}"})
            return {}

    def _cmd_set_parameters(self, data: dict) -> dict:
        if not self._is_open or not self._camera:
            self._send_to_gui("error", {"error": "Camera not open"})
            return {}
        fr = data.get("frame_rate")
        exp = data.get("exposure_time")
        gain = data.get("gain")
        if None in (fr, exp, gain):
            self._send_to_gui("error", {"error": "Missing parameters"})
            return {}
        try:
            import time
            self._camera.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
            self._camera.MV_CC_SetEnumValue("ExposureAuto", 0)
            time.sleep(0.2)
            if self._camera.MV_CC_SetFloatValue("ExposureTime", float(exp)) != 0:
                self._send_to_gui("error", {"error": "Set exposure failed"})
                return {}
            if self._camera.MV_CC_SetFloatValue("Gain", float(gain)) != 0:
                self._send_to_gui("error", {"error": "Set gain failed"})
                return {}
            if self._camera.MV_CC_SetFloatValue("AcquisitionFrameRate", float(fr)) != 0:
                self._send_to_gui("error", {"error": "Set frame rate failed"})
                return {}
            self._send_to_gui("status", {"status": "Parameters set successfully"})
            return {"status": "ok"}
        except Exception as e:
            self._send_to_gui("error", {"error": f"Set parameters failed: {e}"})
            return {}
