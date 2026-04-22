# -*- coding: utf-8 -*-
"""
Логика захвата кадров через Hikvision SDK.

Enum устройств, open/close, grab. capture_frame возвращает сырой np.ndarray
(2D Bayer/Gray, 3D RGB) без cv2-конвертации.
"""

import sys
import threading
from ctypes import byref, cast, memset, sizeof, POINTER, c_ubyte
from typing import Any, Callable, Dict, List, Optional

import ctypes
import numpy as np

try:
    from hikvision_camera_module.sdk.MvCameraControl_class import (
        MvCamera,
        MV_CC_DEVICE_INFO_LIST,
        MV_CC_DEVICE_INFO,
        MV_FRAME_OUT,
        MV_GIGE_DEVICE,
        MV_USB_DEVICE,
    )
    from hikvision_camera_module.sdk.CameraParams_header import (
        MV_TRIGGER_MODE_OFF,
    )

    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    MvCamera = None
    MV_CC_DEVICE_INFO_LIST = None
    MV_CC_DEVICE_INFO = None
    MV_FRAME_OUT = None
    MV_GIGE_DEVICE = None
    MV_USB_DEVICE = None
    MV_TRIGGER_MODE_OFF = None

def _buffer_copy(dst, src, size: int) -> None:
    """Копирование буфера через C memcpy."""
    if sys.platform == "win32":
        ctypes.cdll.msvcrt.memcpy(byref(dst), src, size)
    else:
        ctypes.CDLL(None).memcpy(byref(dst), src, size)


def enum_devices() -> Dict[str, Any]:
    """
    Перечислить устройства GigE/USB.
    Returns: {status: "ok"|"error", devices: [{index, type, display_name, ...}]}
    """
    if not _SDK_AVAILABLE:
        return {"status": "error", "error": "Hikvision SDK not available", "devices": []}
    try:
        device_list = MV_CC_DEVICE_INFO_LIST()
        ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, device_list)
        if ret != 0:
            return {"status": "error", "error": f"Enum devices failed: {ret}", "devices": []}
        if device_list.nDeviceNum == 0:
            return {"status": "ok", "devices": []}
        devices: List[Dict[str, Any]] = []
        for i in range(device_list.nDeviceNum):
            mvcc = cast(
                device_list.pDeviceInfo[i],
                POINTER(MV_CC_DEVICE_INFO),
            ).contents
            info: Dict[str, Any] = {
                "index": i,
                "type": "Unknown",
                "user_name": "",
                "model_name": "",
                "serial": "",
                "display_name": f"[{i}] Unknown",
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
                        pass
                    try:
                        info["model_name"] = ctypes.cast(
                            mvcc.SpecialInfo.stGigEInfo.chModelName,
                            ctypes.c_char_p,
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
                elif mvcc.nTLayerType == MV_USB_DEVICE:
                    info["type"] = "USB"
                    try:
                        info["user_name"] = ctypes.cast(
                            mvcc.SpecialInfo.stUsb3VInfo.chUserDefinedName,
                            ctypes.c_char_p,
                        ).value.decode("gbk", errors="replace")
                    except Exception:
                        pass
                    try:
                        info["model_name"] = ctypes.cast(
                            mvcc.SpecialInfo.stUsb3VInfo.chModelName,
                            ctypes.c_char_p,
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
                pass
            devices.append(info)
        return {"status": "ok", "devices": devices}
    except Exception as e:
        return {"status": "error", "error": str(e), "devices": []}


class HikvisionCapture:
    """
    Низкоуровневый захват через Hikvision SDK.
    Возвращает сырые кадры (2D/3D) без cv2.
    """

    def __init__(
        self,
        on_status: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self._on_status = on_status or (lambda _: None)
        self._on_error = on_error or (lambda _: None)
        self._camera = None
        self._is_open = False
        self._is_grabbing = False
        self._buf_save_image = None
        self._st_frame_info = None
        self._buf_lock = threading.Lock()
        self._camera_index = 0
        self._last_pixel_type = 0

    @property
    def last_pixel_type(self) -> int:
        """Последний pixel_type кадра (для cv2-конвертации в вызывающем коде)."""
        return getattr(self, "_last_pixel_type", 0)

    @property
    def camera(self):
        """Экземпляр MvCamera для get/set parameters."""
        return self._camera

    @property
    def sdk_available(self) -> bool:
        return _SDK_AVAILABLE

    def open(self, camera_index: int = 0) -> bool:
        """Открыть камеру по индексу."""
        if not _SDK_AVAILABLE:
            self._on_error("Hikvision SDK not available")
            return False
        if self._is_open:
            return True
        try:
            device_list = MV_CC_DEVICE_INFO_LIST()
            ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, device_list)
            if ret != 0 or device_list.nDeviceNum == 0:
                self._on_error("No cameras found")
                return False
            if camera_index >= device_list.nDeviceNum:
                self._on_error(f"Camera index {camera_index} not available")
                return False
            self._camera_index = camera_index
            st_dev = cast(
                device_list.pDeviceInfo[camera_index],
                POINTER(MV_CC_DEVICE_INFO),
            ).contents
            self._camera = MvCamera()
            ret = self._camera.MV_CC_CreateHandle(st_dev)
            if ret != 0:
                self._on_error(f"Create handle failed: {ret}")
                return False
            ret = self._camera.MV_CC_OpenDevice()
            if ret != 0:
                self._camera.MV_CC_DestroyHandle()
                self._on_error(f"Open device failed: {ret}")
                return False
            if st_dev.nTLayerType == MV_GIGE_DEVICE:
                n_pkt = self._camera.MV_CC_GetOptimalPacketSize()
                if int(n_pkt) > 0:
                    self._camera.MV_CC_SetIntValue("GevSCPSPacketSize", n_pkt)
            self._camera.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
            self._camera.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
            self._is_open = True
            self._on_status("Camera opened successfully")
            return True
        except Exception as e:
            self._on_error(f"Open camera failed: {e}")
            return False

    def close(self) -> None:
        """Закрыть камеру."""
        if self._is_grabbing and self._camera:
            self._camera.MV_CC_StopGrabbing()
        if self._is_open and self._camera:
            self._camera.MV_CC_CloseDevice()
            self._camera.MV_CC_DestroyHandle()
            self._camera = None
            self._is_open = False
        self._is_grabbing = False
        self._buf_save_image = None

    def start_grabbing(self) -> bool:
        """Начать захват."""
        if not _SDK_AVAILABLE or not self._camera:
            return False
        if not self._is_open:
            if not self.open(self._camera_index):
                return False
        ret = self._camera.MV_CC_StartGrabbing()
        if ret == 0:
            self._is_grabbing = True
            self._on_status("Grabbing started")
            return True
        self._on_error(f"Start grabbing failed: {ret}")
        return False

    def stop_grabbing(self) -> None:
        """Остановить захват."""
        if self._is_grabbing and self._camera:
            self._camera.MV_CC_StopGrabbing()
        self._is_grabbing = False
        self._on_status("Grabbing stopped")

    def capture_frame(self, timeout_ms: int = 1000) -> Optional[np.ndarray]:
        """
        Захватить один кадр. Сырой массив (2D Bayer/Gray, 3D RGB) без cv2.
        """
        if not _SDK_AVAILABLE or not self._camera or not self._is_grabbing:
            return None
        try:
            st_out = MV_FRAME_OUT()
            memset(byref(st_out), 0, sizeof(st_out))
            ret = self._camera.MV_CC_GetImageBuffer(st_out, timeout_ms)
            if ret != 0:
                return None
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
            self._camera.MV_CC_FreeImageBuffer(st_out)
            self._last_pixel_type = pixel_type
            return frame
        except Exception:
            return None
