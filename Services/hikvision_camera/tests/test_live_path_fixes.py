# -*- coding: utf-8 -*-
"""Живой путь `hikvision`: форма кадра (F4), коды узлов (F3) на уровне `HikvisionCamera`/`FrameConverter`.

Фейк MvCamera ведёт журнал вызовов; SDK и ctypes-перечисление подменены так же,
как в test_camera.py. Плагинные случаи (запись рецепта F10, `get_parameters`) ушли в Task 4.2b:
плагин работает на ядре `camera_device`, смысл покрыт test_plugin_on_core.py.
"""

from __future__ import annotations

from ctypes import POINTER, c_ubyte, cast
from unittest.mock import MagicMock, patch

from Services.hikvision_camera.core.camera import CameraState, HikvisionCamera

_MONO8 = 17301505
_RGB8 = 35127316


class FakeMv:
    """Фейк MvCamera: журнал вызовов, настраиваемые коды ответа, готовый кадр."""

    def __init__(self, rc: dict | None = None, frame: tuple | None = None) -> None:
        self.log: list[tuple] = []
        self._rc = rc or {}
        self._frame = frame  # (bytes, width, height, pixel_type)
        self._keep = None

    def _set(self, kind: str, node: str, value) -> int:
        self.log.append((f"Set{kind}Value", node, value))
        return self._rc.get((kind, node), 0)

    def MV_CC_SetEnumValue(self, node, value):
        return self._set("Enum", node, value)

    def MV_CC_SetBoolValue(self, node, value):
        return self._set("Bool", node, value)

    def MV_CC_SetIntValue(self, node, value):
        return self._set("Int", node, value)

    def MV_CC_SetFloatValue(self, node, value):
        return self._set("Float", node, value)

    def MV_CC_GetFloatValue(self, node, st):
        self.log.append(("GetFloatValue", node))
        return 0

    def MV_CC_CreateHandle(self, _info):
        return 0

    def MV_CC_OpenDevice(self):
        self.log.append(("OpenDevice",))
        return 0

    def MV_CC_StartGrabbing(self):
        self.log.append(("StartGrabbing",))
        return 0

    def MV_CC_StopGrabbing(self):
        return 0

    def MV_CC_CloseDevice(self):
        return 0

    def MV_CC_DestroyHandle(self):
        return 0

    def MV_CC_FreeImageBuffer(self, _st):
        return 0

    def MV_CC_GetImageBuffer(self, st_out, _timeout):
        data, width, height, pixel_type = self._frame
        self._keep = (c_ubyte * len(data))(*data)
        st_out.pBufAddr = cast(self._keep, POINTER(c_ubyte))
        st_out.stFrameInfo.nFrameLen = len(data)
        st_out.stFrameInfo.nWidth = width
        st_out.stFrameInfo.nHeight = height
        st_out.stFrameInfo.enPixelType = pixel_type
        return 0


def _grabbing_camera(frame: tuple):
    """Камера в GRABBING с фейком, отдающим один кадр."""
    errors: list[str] = []
    cam = HikvisionCamera(on_error=errors.append)
    cam._camera = FakeMv(frame=frame)
    cam._state = CameraState.GRABBING
    return cam, errors


def _open_patches(fake: FakeMv):
    """Патчи для open(): SDK доступен, одно устройство, не GigE."""
    device_list = MagicMock()
    device_list.nDeviceNum = 1
    device_list.pDeviceInfo = [MagicMock()]
    dev_info = MagicMock()
    dev_info.nTLayerType = 0
    mv_class = MagicMock(return_value=fake)
    mv_class.MV_CC_EnumDevices.return_value = 0
    return (
        patch("Services.hikvision_camera.core.camera.SDK_AVAILABLE", True),
        patch("Services.hikvision_camera.core.camera.MvCamera", mv_class),
        patch("Services.hikvision_camera.core.camera.MV_CC_DEVICE_INFO_LIST", return_value=device_list),
        patch("ctypes.cast", return_value=MagicMock(contents=dev_info)),
    )


def _open_camera(cam: HikvisionCamera, fake: FakeMv) -> bool:
    p1, p2, p3, p4 = _open_patches(fake)
    with p1, p2, p3, p4:
        return cam.open(0)


# ---------------------------------------------------------------------------
# F4: форма кадра по формату пикселя
# ---------------------------------------------------------------------------


def test_rgb8_кадр_не_теряется():
    cam, _ = _grabbing_camera((bytes(range(24)), 4, 2, _RGB8))
    frame, pixel_type = cam.capture_frame()
    assert frame is not None
    assert frame.shape == (2, 4, 3)
    assert pixel_type == _RGB8


def test_mono8_форма_прежняя():
    cam, _ = _grabbing_camera((bytes(range(8)), 4, 2, _MONO8))
    frame, pixel_type = cam.capture_frame()
    assert frame is not None
    assert frame.shape == (2, 4)
    assert pixel_type == _MONO8


def test_rgb8_с_дополнением_в_хвосте():
    data = bytes(range(24)) + b"\xff\xff\xff\xff"
    cam, _ = _grabbing_camera((data, 4, 2, _RGB8))
    frame, _ = cam.capture_frame()
    assert frame is not None
    assert frame.shape == (2, 4, 3)
    assert frame.ravel().tolist() == list(range(24))


def test_неизвестная_раскладка_даёт_none_и_warning():
    # 4x2 пикселя, 16 байт = 2 канала на пиксель: не поддерживается
    cam, errors = _grabbing_camera((bytes(16), 4, 2, _MONO8))
    frame, pixel_type = cam.capture_frame()
    assert frame is None
    assert pixel_type == 0
    assert len(errors) == 1
    assert "frame_len=16" in errors[0] and "w=4" in errors[0] and "h=2" in errors[0]
    assert "pixel_type=0x" in errors[0]


# ---------------------------------------------------------------------------
# F3: коды узлов open()
# ---------------------------------------------------------------------------


def test_отказ_TriggerMode_виден():
    errors: list[str] = []
    cam = HikvisionCamera(on_error=errors.append)
    fake = FakeMv(rc={("Enum", "TriggerMode"): 0x80000106})
    assert _open_camera(cam, fake) is True
    assert cam.state == CameraState.OPEN
    assert cam.param_errors == {"TriggerMode": "0x80000106"}
    assert any("node=TriggerMode rc=0x80000106" in e for e in errors)


def test_param_errors_сброс_на_повторном_open():
    cam = HikvisionCamera(on_error=lambda _: None)
    assert _open_camera(cam, FakeMv(rc={("Enum", "TriggerMode"): 0x80000106})) is True
    assert cam.param_errors == {"TriggerMode": "0x80000106"}
    cam.close()
    assert _open_camera(cam, FakeMv()) is True
    assert cam.param_errors == {}


def test_отказ_FrameRateEnable_виден():
    cam = HikvisionCamera(on_error=lambda _: None)
    fake = FakeMv(rc={("Bool", "AcquisitionFrameRateEnable"): 0x80000007})
    assert _open_camera(cam, fake) is True
    assert cam.param_errors == {"AcquisitionFrameRateEnable": "0x80000007"}
