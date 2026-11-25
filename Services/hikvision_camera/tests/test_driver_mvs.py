# -*- coding: utf-8 -*-
"""Task 4.1: драйвер `mvs` (порт ядра над `MvCamera`) на фейковом `MvCamera`.

Ожидаемые значения — литералы: коды из MvErrorDefine.h (0x80000106 = MV_E_GC_ACCESS, 0x80000203 =
MV_E_ACCESS_DENIED, 0x80000007 = MV_E_NODATA), размеры кадра из задачи (RGB8 4x2 = 24 байта).
Контрактный набор порта (`PortContractSuite`) идёт на четырёх источниках: фейк по умолчанию, запись
`mvs`, запись `mvcr` (дерево другого вендора) и сам драйвер `mvs` на фейковом `MvCamera`.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest

from Services.camera_device.interface import Binding, DeviceIdentity, DevicePort, DeviceSdk, ParamInfo, PortError
from Services.camera_device.testing.fake_port import from_recording
from Services.camera_device.testing.fake_port import make_port as make_fake_port
from Services.camera_device.tests.port_contract import PortCase, PortContractSuite
from Services.hikvision_camera.driver import BINDINGS, MvsSdk, make_port
from Services.hikvision_camera.sdk.constants import PixelType
from Services.hikvision_camera.tests.conftest import make_fake_cam_cls

RECORDINGS = Path(__file__).resolve().parents[2] / "camera_device" / "testing" / "recordings"
TWO_DEVICES = (("SN1", 0xC0A80101), ("SN2", 0xC0A80102))
SN1 = DeviceIdentity("serial", "SN1")


def names(cam_cls) -> list[str]:
    return [entry[0] for entry in cam_cls.journal]


def opened(cam_cls=None, ident: DeviceIdentity = SN1):
    cam_cls = cam_cls or make_fake_cam_cls()
    port = make_port(cam_cls)
    port.open(ident)
    return port, cam_cls


# --------------------------------------------------------------------------- выбор прибора


def test_выбор_по_serial():
    cam_cls = make_fake_cam_cls(TWO_DEVICES)
    port = make_port(cam_cls)
    port.open(DeviceIdentity("serial", "SN2"))
    created = [args for name, args, _ in cam_cls.journal if name == "MV_CC_CreateHandle"]
    assert created == [("SN2",)]


def test_выбор_по_ip():
    cam_cls = make_fake_cam_cls(TWO_DEVICES)
    port = make_port(cam_cls)
    port.open(DeviceIdentity("ip", "192.168.1.2"))
    created = [args for name, args, _ in cam_cls.journal if name == "MV_CC_CreateHandle"]
    assert created == [("SN2",)]


def test_index_с_warning(caplog):
    cam_cls = make_fake_cam_cls(TWO_DEVICES)
    port = make_port(cam_cls)
    with caplog.at_level(logging.WARNING, logger="hikvision_camera.driver"):
        port.open(DeviceIdentity("index", "1"))
    created = [args for name, args, _ in cam_cls.journal if name == "MV_CC_CreateHandle"]
    assert created == [("SN2",)]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "index=1" in warnings[0]


@pytest.mark.parametrize(
    "ident",
    [
        DeviceIdentity("serial", "NOPE"),
        DeviceIdentity("index", "5"),
        DeviceIdentity("index", "x"),
        DeviceIdentity("url", "rtsp://h"),
    ],
)
def test_нет_прибора_not_found(ident):
    port = make_port(make_fake_cam_cls(TWO_DEVICES))
    with pytest.raises(PortError) as exc_info:
        port.open(ident)
    assert exc_info.value.kind == "not_found"


def test_open_занят_busy_с_кодом():
    port = make_port(make_fake_cam_cls(open_rc=0x80000203))
    with pytest.raises(PortError) as exc_info:
        port.open(SN1)
    assert exc_info.value.kind == "busy"
    assert exc_info.value.code == 0x80000203
    assert "0x80000203" in str(exc_info.value)


def test_open_после_отказа_handle_уничтожен():
    cam_cls = make_fake_cam_cls(open_rc=0x80000203)
    with pytest.raises(PortError):
        make_port(cam_cls).open(SN1)
    assert names(cam_cls)[-1] == "MV_CC_DestroyHandle"


# --------------------------------------------------------------------------- скрытые записи (A6)


def test_open_не_пишет_узлы():
    port, cam_cls = opened()
    names_after_open = names(cam_cls)[names(cam_cls).index("MV_CC_OpenDevice") + 1 :]
    # после открытия — колбэк и три чтения (W1-a2); ни одного Set*/Command (TriggerMode, FrameRateEnable, пакет)
    assert names_after_open == [
        "MV_CC_RegisterExceptionCallBack",
        "MV_CC_GetEnumValue",
        "MV_CC_GetIntValueEx",
        "MV_CC_GetIntValueEx",
    ]


# --------------------------------------------------------------------------- кадр


def test_rgb8_форма():
    cam_cls = make_fake_cam_cls(pixel_type=PixelType.RGB8, data=bytes(range(24)))
    port, _ = opened(cam_cls)
    port.start_grabbing()
    frame = port.get_frame(100)
    assert (frame.width, frame.height, frame.pixel_format) == (4, 2, "rgb8")
    assert len(frame.data) == 24
    assert frame.frame_num == 1


def test_хвост_дополнения_кадра_отрезается():
    cam_cls = make_fake_cam_cls(data=bytes(range(10)), frame_len=10)  # mono8 4x2 = 8 байт + 2 байта дополнения
    port, _ = opened(cam_cls)
    port.start_grabbing()
    assert bytes(port.get_frame(100).data) == bytes(range(8))


def test_короткий_кадр_ошибка_и_буфер_освобождён():
    cam_cls = make_fake_cam_cls(pixel_type=PixelType.RGB8, data=bytes(range(10)))  # RGB8 4x2 требует 24
    port, _ = opened(cam_cls)
    port.start_grabbing()
    with pytest.raises(PortError) as exc_info:
        port.get_frame(100)
    assert exc_info.value.kind == "other"
    assert names(cam_cls)[-1] == "MV_CC_FreeImageBuffer"


def test_буфер_освобождён_до_возврата():
    cam_cls = make_fake_cam_cls(data=bytes(range(8)))
    port, _ = opened(cam_cls)
    port.start_grabbing()
    cam_cls.journal.clear()
    frame = port.get_frame(100)
    # на момент возврата в журнале уже есть Free, из того же потока, и он последний
    assert [n for n in names(cam_cls)] == ["MV_CC_GetImageBuffer", "MV_CC_FreeImageBuffer"]
    assert {tid for _, _, tid in cam_cls.journal} == {threading.get_ident()}
    # буфер SDK после Free забит 0xEE; кадр — копия, значит данные целы
    assert bytes(frame.data) == bytes(range(8))


def test_таймаут_кадра_это_None():
    cam_cls = make_fake_cam_cls(frame_rc=0x80000007)
    port, _ = opened(cam_cls)
    port.start_grabbing()
    assert port.get_frame(10) is None
    assert "MV_CC_FreeImageBuffer" not in names(cam_cls)  # буфер не выдавался — освобождать нечего


def test_ошибка_кадра_сетевая():
    cam_cls = make_fake_cam_cls(frame_rc=0x80000205)
    port, _ = opened(cam_cls)
    port.start_grabbing()
    with pytest.raises(PortError) as exc_info:
        port.get_frame(10)
    assert (exc_info.value.kind, exc_info.value.code) == ("network", 0x80000205)


# --------------------------------------------------------------------------- параметры


def test_enum_наружу_символьное_имя():
    port, _ = opened()
    assert port.get_param(BINDINGS["trigger_mode"]) == "Off"
    port.set_param(BINDINGS["trigger_source"], "Software")
    assert port.get_param(BINDINGS["trigger_source"]) == "Software"


def test_enum_неизвестное_имя_range():
    port, _ = opened()
    with pytest.raises(PortError) as exc_info:
        port.set_param(BINDINGS["trigger_source"], "Nope")
    assert (exc_info.value.kind, exc_info.value.code) == ("range", 0x80000102)
    assert "Nope" not in str(exc_info.value)


def test_float_bool_int_запись_и_чтение():
    port, _ = opened()
    port.set_param(BINDINGS["exposure_time"], 12345.0)
    port.set_param(BINDINGS["frame_rate_enable"], True)
    port.set_param(BINDINGS["packet_delay"], 400)
    assert port.get_param(BINDINGS["exposure_time"]) == 12345.0
    assert port.get_param(BINDINGS["frame_rate_enable"]) is True
    assert port.get_param(BINDINGS["packet_delay"]) == 400


def test_packet_size_0_оптимальный():
    port, cam_cls = opened()
    port.set_param(BINDINGS["packet_size"], 0)
    assert port.get_param(BINDINGS["packet_size"]) == 9000  # optimal_packet фейка
    assert "MV_CC_GetOptimalPacketSize" in names(cam_cls)


def test_packet_size_явный_без_запроса_оптимального():
    port, cam_cls = opened()
    port.set_param(BINDINGS["packet_size"], 1500)
    assert port.get_param(BINDINGS["packet_size"]) == 1500
    assert "MV_CC_GetOptimalPacketSize" not in names(cam_cls)


def test_запись_заблокированного_узла_при_захвате_access():
    port, _ = opened()
    port.start_grabbing()
    with pytest.raises(PortError) as exc_info:
        port.set_param(Binding("genicam", "Width", "int"), 64)
    assert (exc_info.value.kind, exc_info.value.code) == ("access", 0x80000106)


def test_describe_границы_и_enum():
    port, _ = opened()
    assert port.describe_param(BINDINGS["exposure_time"]) == ParamInfo(15.0, 9999500.0, None, None, "RW")
    assert port.describe_param(BINDINGS["trigger_mode"]) == ParamInfo(None, None, None, ("Off", "On"), "RW")
    assert port.describe_param(BINDINGS["packet_size"]) == ParamInfo(220, 9000, 4, None, "RW")


def test_describe_нет_узла_не_бросает():
    port, _ = opened()
    info = port.describe_param(Binding("genicam", "NoSuchNode", "int"))
    assert info == ParamInfo(None, None, None, None, "NI")


def test_execute_команда_идёт_в_SetCommandValue():
    port, cam_cls = opened()
    port.execute(Binding("genicam", "TriggerSoftware", "command"))
    assert [a for n, a, _ in cam_cls.journal if n == "MV_CC_SetCommandValue"] == [("TriggerSoftware",)]


def test_вне_open_closed():
    port = make_port(make_fake_cam_cls())
    for call in (lambda: port.get_param(BINDINGS["gain"]), lambda: port.start_grabbing(), lambda: port.get_frame(1)):
        with pytest.raises(PortError) as exc_info:
            call()
        assert exc_info.value.kind == "closed"


def test_capabilities_по_факту():
    assert make_port(make_fake_cam_cls()).capabilities == frozenset(
        {"read_back", "node_describe", "software_trigger", "exception_cb"}
    )


# --------------------------------------------------------------------------- колбэк исключений


def test_колбэк_исключений_кладёт_код_в_очередь():
    port, cam_cls = opened()
    callback = cam_cls.instances[0].exception_cb
    assert callback is not None
    callback(0x00008001, None)  # как из потока SDK
    assert port.exceptions.get_nowait() == 0x8001


# --------------------------------------------------------------------------- DeviceSdk


def test_sdk_счётчик_ссылок_без_инициализации_dll():
    cam_cls = make_fake_cam_cls(TWO_DEVICES)
    sdk = MvsSdk(cam_cls)
    assert isinstance(sdk, DeviceSdk)
    sdk.acquire()
    sdk.acquire()
    sdk.release()
    sdk.release()
    with pytest.raises(RuntimeError):
        sdk.release()
    assert names(cam_cls) == []  # acquire/release не трогают SDK


def test_sdk_enum_devices():
    sdk = MvsSdk(make_fake_cam_cls(TWO_DEVICES))
    sdk.acquire()
    assert sdk.enum_devices() == [
        DeviceIdentity("serial", "SN1", "FAKE-CAM"),
        DeviceIdentity("serial", "SN2", "FAKE-CAM"),
    ]


def test_acquire_без_dll_PortError(monkeypatch):
    monkeypatch.setattr("Services.hikvision_camera.sdk.bindings.SDK_AVAILABLE", False)
    with pytest.raises(PortError) as exc_info:
        make_port().sdk.acquire()
    assert exc_info.value.kind == "other"


def test_bindings_набор_ключей():
    assert {k: b.key for k, b in BINDINGS.items()} == {
        "trigger_mode": "TriggerMode",
        "trigger_source": "TriggerSource",
        "exposure_time": "ExposureTime",
        "exposure_auto": "ExposureAuto",
        "gain_auto": "GainAuto",
        "gain": "Gain",
        "frame_rate": "AcquisitionFrameRate",
        "frame_rate_enable": "AcquisitionFrameRateEnable",
        "packet_size": "GevSCPSPacketSize",
        "packet_delay": "GevSCPD",
    }


# --------------------------------------------------------------------------- контрактный набор порта


class TestMvsContract(PortContractSuite):
    """Сам драйвер на фейковом `MvCamera`."""

    @pytest.fixture
    def port_case(self) -> PortCase:
        return PortCase(
            id="mvs",
            make=lambda: make_port(make_fake_cam_cls()),
            ident=SN1,
            rw_binding=BINDINGS["exposure_time"],
            frame_byte0=0,
        )

    def test_isinstance_device_port_mvs(self):
        assert isinstance(make_port(make_fake_cam_cls()), DevicePort) is True


class TestFakeDefaultContract(PortContractSuite):
    """Источник 1 (амендмент 5): фейк ядра с узлами по умолчанию."""

    @pytest.fixture
    def port_case(self) -> PortCase:
        return PortCase(
            id="fake",
            make=make_fake_port,
            ident=DeviceIdentity("serial", "FAKE-0001"),
            rw_binding=Binding("genicam", "ExposureTime", "float"),
            frame_byte0=0,
        )


class TestMvsRecordingContract(PortContractSuite):
    """Источник 2: дерево узлов MVS из записи 0.5."""

    @pytest.fixture
    def port_case(self) -> PortCase:
        return PortCase(
            id="rec-mvs",
            make=lambda: from_recording(RECORDINGS / "mvs_MV-CS020-10GC.json"),
            ident=DeviceIdentity("serial", "FAKE-0001"),
            rw_binding=Binding("genicam", "ExposureTime", "float"),
            frame_byte0=0,
        )


class TestMvcrRecordingContract(PortContractSuite):
    """Источник 3: дерево узлов другого вендора (MvCodeReader ID3013, запись 6.2)."""

    @pytest.fixture
    def port_case(self) -> PortCase:
        return PortCase(
            id="rec-mvcr",
            make=lambda: from_recording(RECORDINGS / "mvcr_ID3013.json"),
            ident=DeviceIdentity("serial", "FAKE-0001"),
            rw_binding=Binding("genicam", "ExposureTime", "float"),
            frame_byte0=0,
        )
