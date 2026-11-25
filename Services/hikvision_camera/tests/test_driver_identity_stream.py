# -*- coding: utf-8 -*-
"""W1-a2: порт `mvs` — поля сети, выбор записи по подсети камеры, личность открытого прибора, поля кадра.

Фейк камеры — `conftest.make_fake_cam_cls` с локальным подклассом: свои структуры перечисления, `nNetExport` в
журнал теста (журнал фейка пишет только серийный номер, у дублей он один), `nLostPacket`/`nTriggerIndex` в кадре.
Числа литералами: камера 192.168.1.20/24; записи с картами хоста 169.254.49.100 и 192.168.1.100; MAC 00:11:1c:f6:a2:3b.
"""

from __future__ import annotations

import ctypes

import pytest

from Services.camera_device.interface import AmbiguousDeviceError, DeviceIdentity
from Services.hikvision_camera.driver import make_port
from Services.hikvision_camera.sdk.constants import MV_GIGE_DEVICE, MV_USB_DEVICE, PixelType
from Services.hikvision_camera.sdk.structures import MV_CC_DEVICE_INFO
from Services.hikvision_camera.tests.conftest import make_fake_cam_cls

SERIAL = "DA1689923"
IDENT = DeviceIdentity("serial", SERIAL)
CAMERA_IP = 0xC0A80114  # 192.168.1.20
MASK = 0xFFFFFF00
HOST_LINKLOCAL = 0xA9FE3164  # 169.254.49.100, вне подсети камеры
HOST_IN_NET = 0xC0A80164  # 192.168.1.100
HOST_OTHER = 0x0A000005  # 10.0.0.5, вне подсети камеры


def _gige(net_export: int) -> MV_CC_DEVICE_INFO:
    info = MV_CC_DEVICE_INFO()
    info.nTLayerType = MV_GIGE_DEVICE
    info.nMacAddrHigh = 0x0011
    info.nMacAddrLow = 0x1CF6A23B
    gige = info.SpecialInfo.stGigEInfo
    gige.nCurrentIp = CAMERA_IP
    gige.nCurrentSubNetMask = MASK
    gige.nNetExport = net_export
    gige.chSerialNumber[: len(SERIAL)] = list(SERIAL.encode("ascii"))
    gige.chModelName[:8] = list(b"FAKE-CAM")
    return info


def _usb() -> MV_CC_DEVICE_INFO:
    info = MV_CC_DEVICE_INFO()
    info.nTLayerType = MV_USB_DEVICE
    info.nMacAddrHigh = 0x0011  # у USB это не MAC: в личность не идёт
    info.nMacAddrLow = 0x1CF6A23B
    usb = info.SpecialInfo.stUsb3VInfo
    usb.chSerialNumber[: len(SERIAL)] = list(SERIAL.encode("ascii"))
    usb.chModelName[:8] = list(b"FAKE-USB")
    return info


def _cam_cls(
    infos: list[MV_CC_DEVICE_INFO],
    *,
    frame_meta: tuple[tuple[int, int], ...] = (),
    pixel: int = int(PixelType.BAYER_RG8),
    drop_nodes: tuple[str, ...] = (),
):
    """Класс-фейк с перечислением `infos`; `cls.handled` — `nNetExport` структур, ушедших в `CreateHandle`.

    `frame_meta` — `(nLostPacket, nTriggerIndex)` по кадрам; `cls.open_rc` меняется тестом между открытиями.
    """
    base = make_fake_cam_cls()

    class Cam(base):
        handled: list[int] = []
        open_rc = 0

        def __init__(self) -> None:
            super().__init__()
            self.nodes["PixelFormat"]["value"] = pixel
            self.nodes["Width"]["value"] = 640
            self.nodes["Height"]["value"] = 480
            for key in drop_nodes:
                del self.nodes[key]

        @staticmethod
        def MV_CC_EnumDevices(nTLayerType, stDevList) -> int:
            stDevList.nDeviceNum = len(infos)
            for i, info in enumerate(infos):
                stDevList.pDeviceInfo[i] = ctypes.pointer(info)
            return 0

        def MV_CC_CreateHandle(self, stDevInfo):
            Cam.handled.append(int(stDevInfo.SpecialInfo.stGigEInfo.nNetExport))
            self._journal("MV_CC_CreateHandle", ())
            return 0

        def MV_CC_OpenDevice(self, nAccessMode=1, nSwitchoverKey=0):
            self._journal("MV_CC_OpenDevice", ())
            return Cam.open_rc

        def MV_CC_GetImageBuffer(self, stFrame, nMsec):
            rc = super().MV_CC_GetImageBuffer(stFrame, nMsec)
            if self.frame_num <= len(frame_meta):
                lost, trigger = frame_meta[self.frame_num - 1]
                stFrame.stFrameInfo.nLostPacket = lost
                stFrame.stFrameInfo.nTriggerIndex = trigger
            return rc

    return Cam


def _names(cam_cls) -> list[str]:
    return [entry[0] for entry in cam_cls.journal]


def test_gige_fields_mask_host_ip_mac():
    port = make_port(_cam_cls([_gige(HOST_LINKLOCAL)]))
    port.open(IDENT)
    info = port.device_info
    assert info.mask == "255.255.255.0"
    assert info.host_ip == "169.254.49.100"
    assert info.mac == "00:11:1c:f6:a2:3b"


def test_usb_entry_has_empty_net_fields():
    """USB: сетевых полей нет, все три пустые, даже если в структуре лежат биты MAC."""
    port = make_port(_cam_cls([_usb()]))
    port.open(IDENT)
    info = port.device_info
    assert (info.ip, info.mask, info.host_ip, info.mac) == ("", "", "", "")
    assert info.enum_matches == 1


def test_create_handle_gets_entry_in_camera_subnet():
    cam_cls = _cam_cls([_gige(HOST_LINKLOCAL), _gige(HOST_IN_NET)])
    port = make_port(cam_cls)
    port.open(IDENT)
    assert cam_cls.handled == [0xC0A80164]
    assert port.device_info.enum_matches == 2
    assert port.device_info.host_ip == "192.168.1.100"


def test_ambiguous_refused_before_create_handle():
    cam_cls = _cam_cls([_gige(HOST_LINKLOCAL), _gige(HOST_OTHER)])
    port = make_port(cam_cls)
    with pytest.raises(AmbiguousDeviceError) as exc_info:
        port.open(IDENT)
    assert exc_info.value.kind == "not_found"
    assert "MV_CC_CreateHandle" not in _names(cam_cls)
    assert port.device_info is None


def test_device_info_lifecycle():
    port = make_port(_cam_cls([_gige(HOST_IN_NET)]))
    assert port.device_info is None
    port.open(IDENT)
    assert (port.device_info.serial, port.device_info.model, port.device_info.ip) == (
        "DA1689923",
        "FAKE-CAM",
        "192.168.1.20",
    )
    port.close()
    assert port.device_info is None


def test_refused_reopen_leaves_device_info_none():
    """Отказ повторного открытия не оставляет личность прошлого цикла."""
    cam_cls = _cam_cls([_gige(HOST_IN_NET)])
    port = make_port(cam_cls)
    port.open(IDENT)
    port.close()
    cam_cls.open_rc = 0x80000203  # MV_E_ACCESS_DENIED: прибор занят
    with pytest.raises(Exception) as exc_info:
        port.open(IDENT)
    assert exc_info.value.kind == "busy"
    assert port.device_info is None


def test_open_reads_format_and_size_once():
    cam_cls = _cam_cls([_gige(HOST_IN_NET)])
    port = make_port(cam_cls)
    port.open(IDENT)
    assert (port.device_info.pixel_format, port.device_info.width, port.device_info.height) == ("bayer_rg8", 640, 480)
    reads = ["MV_CC_GetEnumValue", "MV_CC_GetIntValueEx", "MV_CC_GetIntValueEx"]
    assert [n for n in _names(cam_cls) if n.startswith("MV_CC_Get")] == reads
    assert [args for n, args, _ in cam_cls.journal if n.startswith("MV_CC_Get")] == [
        ("PixelFormat",),
        ("Width",),
        ("Height",),
    ]
    port.start_grabbing()
    cam_cls.journal.clear()
    port.get_frame(100)
    port.get_frame(100)
    assert [n for n in _names(cam_cls) if n in ("MV_CC_GetEnumValue", "MV_CC_GetIntValueEx")] == []


def test_open_read_failures_leave_blank_and_open_succeeds():
    """Ненулевой rc чтения не роняет `open`: поле остаётся пустым, остальные читаются."""
    cam_cls = _cam_cls([_gige(HOST_IN_NET)], drop_nodes=("PixelFormat", "Width"))
    port = make_port(cam_cls)
    port.open(IDENT)
    assert (port.device_info.pixel_format, port.device_info.width, port.device_info.height) == ("", 0, 480)
    assert port.device_info.host_ip == "192.168.1.100"


def test_open_unknown_pixel_value_named_by_hex():
    cam_cls = _cam_cls([_gige(HOST_IN_NET)], pixel=0x02180020)  # значение не из таблицы `_PIXEL_FORMATS`
    port = make_port(cam_cls)
    port.open(IDENT)
    assert port.device_info.pixel_format == "pixel_0x02180020"


def test_get_frame_passes_lost_packets_and_trigger_index():
    cam_cls = _cam_cls([_gige(HOST_IN_NET)], frame_meta=((3, 0), (0, 7)))
    port = make_port(cam_cls)
    port.open(IDENT)
    port.start_grabbing()
    first = port.get_frame(100)
    assert first.lost_packets == 3
    assert first.trigger_index is None
    second = port.get_frame(100)
    assert second.lost_packets == 0
    assert second.trigger_index == 7
