# -*- coding: utf-8 -*-
"""Живой путь `hikvision`: форма кадра (F4), запись рецепта (F10), коды узлов (F3).

Фейк MvCamera ведёт журнал вызовов; SDK и ctypes-перечисление подменены так же,
как в test_camera.py. Тесты плагина используют настоящий HikvisionCamera
(не MagicMock), чтобы цепочка плагин -> камера -> SDK проверялась целиком.
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


# ---------------------------------------------------------------------------
# F10: рецепт пишется в камеру после open и до StartGrabbing (плагин)
# ---------------------------------------------------------------------------


def _plugin_start(config: dict, fake: FakeMv):
    """Настроить плагин с настоящей HikvisionCamera и запустить захват."""
    from Services.hikvision_camera.plugin.plugin import HikvisionCameraPlugin

    ctx = MagicMock()
    ctx.config = config
    ctx.registers = None
    plugin = HikvisionCameraPlugin()
    plugin.configure(ctx)
    p1, p2, p3, p4 = _open_patches(fake)
    with p1, p2, p3, p4:
        result = plugin.cmd_start_capture({})
    return plugin, result


def test_рецепт_exposure_пишется_после_open():
    fake = FakeMv()
    _, result = _plugin_start({"exposure_time": 5000}, fake)
    assert result == {"status": "ok"}
    log = fake.log
    i_open = log.index(("OpenDevice",))
    i_auto = log.index(("SetEnumValue", "ExposureAuto", 0))
    i_exp = log.index(("SetFloatValue", "ExposureTime", 5000.0))
    i_start = log.index(("StartGrabbing",))
    assert i_open < i_auto < i_exp < i_start


def test_без_ключа_рецепта_exposure_не_пишется():
    fake = FakeMv()
    _, result = _plugin_start({}, fake)
    assert result == {"status": "ok"}
    assert [e for e in fake.log if e[0] == "SetFloatValue"] == []
    assert ("SetEnumValue", "ExposureAuto", 0) not in fake.log
    assert ("SetEnumValue", "GainAuto", 0) not in fake.log


def test_gain_рецепта_пишется_после_GainAuto():
    fake = FakeMv()
    _plugin_start({"gain": 7}, fake)
    log = fake.log
    assert (
        log.index(("OpenDevice",))
        < log.index(("SetEnumValue", "GainAuto", 0))
        < log.index(("SetFloatValue", "Gain", 7.0))
        < log.index(("StartGrabbing",))
    )


def test_fps_рецепта_пишется_как_frame_rate():
    fake = FakeMv()
    _plugin_start({"fps": 25}, fake)
    log = fake.log
    assert log.index(("SetFloatValue", "AcquisitionFrameRate", 25.0)) < log.index(("StartGrabbing",))


def test_frame_rate_приоритетнее_fps():
    fake = FakeMv()
    _plugin_start({"fps": 25, "frame_rate": 10}, fake)
    writes = [e for e in fake.log if e[:2] == ("SetFloatValue", "AcquisitionFrameRate")]
    assert writes == [("SetFloatValue", "AcquisitionFrameRate", 10.0)]


def test_get_parameters_отдаёт_param_errors():
    fake = FakeMv(rc={("Enum", "TriggerMode"): 0x80000106})
    plugin, result = _plugin_start({}, fake)
    assert result == {"status": "ok"}
    with patch("Services.hikvision_camera.core.parameters.SDK_AVAILABLE", True):
        answer = plugin.cmd_get_parameters({})
    assert answer["status"] == "ok"
    assert answer["param_errors"] == {"TriggerMode": "0x80000106"}


def test_get_parameters_ошибка_тоже_несёт_param_errors():
    fake = FakeMv(rc={("Enum", "TriggerMode"): 0x80000106})
    plugin, _ = _plugin_start({}, fake)
    # SDK_AVAILABLE=False в parameters -> get_parameters возвращает None
    with patch("Services.hikvision_camera.core.parameters.SDK_AVAILABLE", False):
        answer = plugin.cmd_get_parameters({})
    assert answer["status"] == "error"
    assert answer["param_errors"] == {"TriggerMode": "0x80000106"}
