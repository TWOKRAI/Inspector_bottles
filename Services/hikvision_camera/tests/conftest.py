# -*- coding: utf-8 -*-
"""Фикстуры для тестов hikvision_camera."""

from __future__ import annotations

import ctypes
import threading
from unittest.mock import patch

import numpy as np
import pytest

from Services.hikvision_camera.sdk.constants import MV_GIGE_DEVICE, PixelType
from Services.hikvision_camera.sdk.structures import MV_CC_DEVICE_INFO, MV_CC_DEVICE_INFO_LIST
from Services.hikvision_camera.tools import mvs_probe


@pytest.fixture
def mock_sdk_available():
    """Мокаем SDK как доступный."""
    with patch("Services.hikvision_camera.sdk.bindings.SDK_AVAILABLE", True):
        yield


@pytest.fixture
def mock_sdk_unavailable():
    """Мокаем SDK как недоступный."""
    with patch("Services.hikvision_camera.sdk.bindings.SDK_AVAILABLE", False):
        yield


@pytest.fixture
def sample_bayer_frame():
    """Тестовый Bayer RG8 кадр (2D, одноканальный)."""
    return np.random.randint(0, 255, (480, 640), dtype=np.uint8)


@pytest.fixture
def sample_bgr_frame():
    """Тестовый BGR кадр (3 канала)."""
    return np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)


@pytest.fixture
def sample_rgba_frame():
    """Тестовый RGBA кадр (4 канала)."""
    return np.random.randint(0, 255, (480, 640, 4), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Фейковый MvCamera для тестов драйвера `mvs` (Task 4.1)
# ---------------------------------------------------------------------------


def _gige_info(serial: str, ip: int) -> MV_CC_DEVICE_INFO:
    info = MV_CC_DEVICE_INFO()
    info.nTLayerType = MV_GIGE_DEVICE
    gige = info.SpecialInfo.stGigEInfo
    gige.nCurrentIp = ip
    gige.chSerialNumber[: len(serial)] = list(serial.encode("ascii"))
    gige.chModelName[:8] = list(b"FAKE-CAM")
    return info


def make_fake_cam_cls(
    devices: tuple[tuple[str, int], ...] = (("SN1", 0xC0A80101),),
    *,
    width: int = 4,
    height: int = 2,
    pixel_type: int = PixelType.MONO8,
    data: bytes = bytes(range(8)),
    frame_len: int | None = None,
    frame_rc: int = 0,
    open_rc: int = 0,
):
    """Класс-фейк `MvCamera` (интерфейс `cam_cls` драйвера) поверх `mvs_probe.FakeMvCamera`.

    Журнал `cls.journal` общий для всех экземпляров: `(имя, args, id потока)`, пишется и для статического
    `MV_CC_EnumDevices`. `devices` — `(серийный номер, IPv4 как int)`. Кадр: `data` кладётся в буфер при
    каждом `GetImageBuffer`; `FreeImageBuffer` забивает буфер 0xEE (чтение после освобождения видно).
    """
    infos = [_gige_info(serial, ip) for serial, ip in devices]
    journal: list[tuple[str, tuple, int]] = []

    class FakeMvsCamera(mvs_probe.FakeMvCamera):
        optimal_packet = 9000

        def __init__(self) -> None:
            super().__init__()
            self.frame_num = 0
            self.exception_cb = None
            self._buf = (ctypes.c_ubyte * max(len(data), frame_len or 0, 1))()
            FakeMvsCamera.instances.append(self)

        def _journal(self, name: str, args: tuple) -> None:
            super()._journal(name, args)
            journal.append((name, args, threading.get_ident()))

        @staticmethod
        def MV_CC_EnumDevices(nTLayerType, stDevList: MV_CC_DEVICE_INFO_LIST) -> int:
            journal.append(("MV_CC_EnumDevices", (), threading.get_ident()))
            stDevList.nDeviceNum = len(infos)
            for i, info in enumerate(infos):
                stDevList.pDeviceInfo[i] = ctypes.pointer(info)
            return 0

        def MV_CC_CreateHandle(self, stDevInfo):
            serial = bytes(stDevInfo.SpecialInfo.stGigEInfo.chSerialNumber).split(b"\0", 1)[0].decode("ascii")
            self._journal("MV_CC_CreateHandle", (serial,))
            return 0

        def MV_CC_OpenDevice(self, nAccessMode=1, nSwitchoverKey=0):
            self._journal("MV_CC_OpenDevice", ())
            return open_rc

        def MV_CC_GetImageBuffer(self, stFrame, nMsec):
            self._journal("MV_CC_GetImageBuffer", (nMsec,))
            if frame_rc != 0:
                return frame_rc
            self.frame_num += 1
            ctypes.memmove(self._buf, data, len(data))
            stFrame.pBufAddr = ctypes.cast(self._buf, ctypes.POINTER(ctypes.c_ubyte))
            info = stFrame.stFrameInfo
            info.nWidth, info.nHeight, info.enPixelType = width, height, int(pixel_type)
            info.nFrameLen = frame_len if frame_len is not None else len(data)
            info.nFrameNum = self.frame_num
            return 0

        def MV_CC_FreeImageBuffer(self, stFrame):
            self._journal("MV_CC_FreeImageBuffer", ())
            ctypes.memset(self._buf, 0xEE, len(self._buf))
            return 0

        def MV_CC_GetOptimalPacketSize(self):
            self._journal("MV_CC_GetOptimalPacketSize", ())
            return self.optimal_packet

        def MV_CC_SetCommandValue(self, strKey):
            self._journal("MV_CC_SetCommandValue", (strKey,))
            return 0

        def MV_CC_RegisterExceptionCallBack(self, cbException, pUser=None):
            self._journal("MV_CC_RegisterExceptionCallBack", ())
            self.exception_cb = cbException
            return 0

    FakeMvsCamera.journal = journal
    FakeMvsCamera.instances = []
    return FakeMvsCamera
