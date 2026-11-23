# -*- coding: utf-8 -*-
"""Драйвер `mvs` (Task 4.1): порт ядра камеры `camera_device` — тонкий адаптер над `MvCamera`.

`make_port()` строит `MvsPort` (`DevicePort`) со своим `MvsSdk` (`DeviceSdk`) в `port.sdk`.
Ядро вендоров не импортирует; драйвер подключается строкой реестра. Новых потоков нет: все вызовы
идут из потока-владельца сеанса, колбэк исключений SDK только кладёт код в `port.exceptions`.

Что драйвер НЕ делает (скрытые записи `HikvisionCamera.open`, A6): `open` не пишет ни `TriggerMode`,
ни `AcquisitionFrameRateEnable`, ни `GevSCPSPacketSize` — это поля и шаги плана run. Размер пакета
«оптимальный» запрашивается записью `packet_size = 0`.
`MV_CC_Initialize`/`Finalize` не зовутся: в `MvCameraControl.dll` 0x04020003 их нет (амендмент 2).
"""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from Services.camera_device.interface import (
    Binding,
    DeviceIdentity,
    ErrorKind,
    ParamInfo,
    PortError,
    RawFrame,
)
from Services.hikvision_camera.sdk import bindings as _bindings
from Services.hikvision_camera.sdk.bindings import EXCEPTION_CALLBACK, MvCamera
from Services.hikvision_camera.sdk.constants import MV_GIGE_DEVICE, MV_USB_DEVICE, PixelType
from Services.hikvision_camera.sdk.errors import (
    MV_E_ACCESS_DENIED,
    MV_E_BUSY,
    MV_E_GC_ACCESS,
    MV_E_GC_RANGE,
    MV_E_GC_TIMEOUT,
    MV_E_NETER,
    MV_E_NODATA,
    MV_E_PACKET,
    MV_E_WRITE_PROTECT,
)
from Services.hikvision_camera.sdk.structures import (
    AM_NA,
    AM_NI,
    AM_RO,
    AM_RW,
    AM_WO,
    MV_CC_DEVICE_INFO,
    MV_CC_DEVICE_INFO_LIST,
    MV_FRAME_OUT,
    MVCC_ENUMENTRY,
    MVCC_ENUMVALUE,
    MVCC_FLOATVALUE,
    MVCC_INTVALUE_EX,
)

logger = logging.getLogger("hikvision_camera.driver")

CAPABILITIES = frozenset({"read_back", "node_describe", "software_trigger", "exception_cb"})

# Ключ — имя поля register'а плагина (4.2a), значение — узел GenICam. `eps_abs` float-узлов — допуск
# чтения float32 прибора (шаг float32 при 1e7 мкс равен 1).
BINDINGS: dict[str, Binding] = {
    "trigger_mode": Binding("genicam", "TriggerMode", "enum"),
    "trigger_source": Binding("genicam", "TriggerSource", "enum"),
    "exposure_time": Binding("genicam", "ExposureTime", "float", eps_abs=1.0),
    "exposure_auto": Binding("genicam", "ExposureAuto", "enum"),
    "gain_auto": Binding("genicam", "GainAuto", "enum"),
    "gain": Binding("genicam", "Gain", "float", eps_abs=1e-3),
    "frame_rate": Binding("genicam", "AcquisitionFrameRate", "float", eps_abs=1e-3),
    "frame_rate_enable": Binding("genicam", "AcquisitionFrameRateEnable", "bool"),
    "packet_size": Binding("genicam", "GevSCPSPacketSize", "int"),
    "packet_delay": Binding("genicam", "GevSCPD", "int"),
}

PACKET_SIZE_KEY = "GevSCPSPacketSize"

# Код MVS -> `PortError.kind`. 0x80000203 в errors.py назван ACCESS_DENIED: прибор уже открыт другим
# клиентом (docs GENICAM.md), для оператора это «занят». Незнакомый код -> "other".
_KIND_BY_CODE: dict[int, ErrorKind] = {
    MV_E_GC_ACCESS: "access",
    MV_E_WRITE_PROTECT: "access",
    MV_E_ACCESS_DENIED: "busy",
    MV_E_BUSY: "busy",
    MV_E_GC_RANGE: "range",
    MV_E_GC_TIMEOUT: "timeout",
    MV_E_PACKET: "network",
    MV_E_NETER: "network",
}

# enPixelType -> (каноническое имя, байт на пиксель). Форма кадра — по формату: RGB8 -> h*w*3.
_PIXEL_FORMATS: dict[int, tuple[str, int]] = {
    PixelType.MONO8: ("mono8", 1),
    PixelType.MONO8_SIGNED: ("mono8s", 1),
    PixelType.MONO16: ("mono16", 2),
    PixelType.BAYER_GR8: ("bayer_gr8", 1),
    PixelType.BAYER_RG8: ("bayer_rg8", 1),
    PixelType.BAYER_GB8: ("bayer_gb8", 1),
    PixelType.BAYER_BG8: ("bayer_bg8", 1),
    PixelType.BAYER_GR10: ("bayer_gr10", 2),
    PixelType.BAYER_RG10: ("bayer_rg10", 2),
    PixelType.BAYER_GR12: ("bayer_gr12", 2),
    PixelType.BAYER_RG12: ("bayer_rg12", 2),
    PixelType.RGB8: ("rgb8", 3),
    PixelType.BGR8: ("bgr8", 3),
    PixelType.RGBA8: ("rgba8", 4),
    PixelType.BGRA8: ("bgra8", 4),
    PixelType.YUV422: ("yuv422", 2),
    PixelType.YUV422_YUYV: ("yuv422_yuyv", 2),
}

_ACCESS_BY_AM = {AM_NI: "NI", AM_NA: "NA", AM_WO: "WO", AM_RO: "RO", AM_RW: "RW"}

# `MV_CC_GetImageBuffer` без кадра за таймаут: «нет данных» (None, не исключение).
_TIMEOUT_CODES = frozenset({MV_E_NODATA, MV_E_GC_TIMEOUT})


def _err(rc: int, where: str) -> PortError:
    """`PortError` по коду SDK: `kind` из `_KIND_BY_CODE`, `code` — беззнаковый rc."""
    code = int(rc) & 0xFFFFFFFF
    return PortError(_KIND_BY_CODE.get(code, "other"), where, code)


def _text(buf: Any) -> str:
    return bytes(buf).split(b"\0", 1)[0].decode("ascii", errors="replace")


def _ip_text(n: int) -> str:
    return f"{(n >> 24) & 0xFF}.{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"


@dataclass(frozen=True)
class _Entry:
    """Прибор из перечисления: серийный номер, IP (GigE), модель и структура для `CreateHandle`."""

    serial: str
    ip: str
    model: str
    info: MV_CC_DEVICE_INFO


def _entry_from_info(info: MV_CC_DEVICE_INFO) -> _Entry:
    if info.nTLayerType == MV_GIGE_DEVICE:
        gi = info.SpecialInfo.stGigEInfo
        return _Entry(_text(gi.chSerialNumber), _ip_text(gi.nCurrentIp), _text(gi.chModelName), info)
    if info.nTLayerType == MV_USB_DEVICE:
        ui = info.SpecialInfo.stUsb3VInfo
        return _Entry(_text(ui.chSerialNumber), "", _text(ui.chModelName), info)
    return _Entry("", "", "", info)


def _enumerate(cam_cls: Any, where: str) -> tuple[MV_CC_DEVICE_INFO_LIST, list[_Entry]]:
    """Перечислить приборы. Список структур возвращается тоже: `_Entry.info` живёт, пока жив он."""
    dev_list = MV_CC_DEVICE_INFO_LIST()
    rc = cam_cls.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, dev_list)
    if rc != 0:
        raise _err(rc, where)
    pointer_type = ctypes.POINTER(MV_CC_DEVICE_INFO)
    entries = [
        _entry_from_info(ctypes.cast(dev_list.pDeviceInfo[i], pointer_type).contents)
        for i in range(dev_list.nDeviceNum)
    ]
    return dev_list, entries


class MvsSdk:
    """`DeviceSdk` MVS: счётчик ссылок и перечисление. DLL не инициализируется (в ней нет `MV_CC_Initialize`).

    `available` — вызываемое, говорящее «DLL загружена» (для настоящего `MvCamera`); у фейка `None`.
    """

    def __init__(self, cam_cls: Any = MvCamera, available: Callable[[], bool] | None = None) -> None:
        self._cam_cls = cam_cls
        self._available = available
        self._lock = threading.Lock()
        self.refs = 0

    def acquire(self) -> None:
        if self._available is not None and not self._available():
            raise PortError("other", "acquire")
        with self._lock:
            self.refs += 1

    def release(self) -> None:
        with self._lock:
            if self.refs <= 0:
                raise RuntimeError("release without acquire")
            self.refs -= 1

    def enum_devices(self) -> list[DeviceIdentity]:
        _, entries = _enumerate(self._cam_cls, "enum_devices")
        return [
            DeviceIdentity("serial", e.serial, e.model) if e.serial else DeviceIdentity("ip", e.ip, e.model)
            for e in entries
        ]


class MvsPort:
    """`DevicePort` над одним `MvCamera`. Состояния: `closed -> opened -> grabbing -> opened -> closed`."""

    def __init__(self, cam_cls: Any = MvCamera, available: Callable[[], bool] | None = None) -> None:
        self._cam_cls = cam_cls
        self.sdk = MvsSdk(cam_cls, available)
        self.capabilities: frozenset[str] = CAPABILITIES
        self.exceptions: queue.SimpleQueue[int] = queue.SimpleQueue()  # коды `nMsgType` из потока SDK
        self._cam: Any = None
        self._state = "closed"
        self._exception_cb: Any = None  # ссылка на CFUNCTYPE: без неё GC освободит thunk

    # -- служебное -----------------------------------------------------------------------------

    def _require_opened(self, where: str) -> None:
        if self._state == "closed":
            raise PortError("closed", where)

    def _on_exception(self, msg_type: int, _user: object) -> None:
        # Поток SDK: только очередь владельца, ни логов, ни обращений к порту.
        self.exceptions.put(int(msg_type))

    def _enum_symbolic(self, key: str, value: int, where: str) -> str:
        entry = MVCC_ENUMENTRY()
        entry.nValue = value
        rc = self._cam.MV_CC_GetEnumEntrySymbolic(key, entry)
        if rc != 0:
            raise _err(rc, where)
        return entry.chSymbolic.decode("ascii", errors="replace")

    # -- DevicePort ----------------------------------------------------------------------------

    def open(self, ident: DeviceIdentity) -> None:
        if self._state != "closed":
            raise PortError("other", "open")
        dev_list, entries = _enumerate(self._cam_cls, "open")
        entry = self._select(ident, entries)
        cam = self._cam_cls()
        rc = cam.MV_CC_CreateHandle(entry.info)
        if rc != 0:
            raise _err(rc, "create_handle")
        rc = cam.MV_CC_OpenDevice()
        if rc != 0:
            cam.MV_CC_DestroyHandle()
            raise _err(rc, "open")
        self._cam = cam
        self._state = "opened"
        del dev_list  # структуры больше не нужны: handle создан
        if "exception_cb" in self.capabilities:
            callback = EXCEPTION_CALLBACK(self._on_exception)
            rc = cam.MV_CC_RegisterExceptionCallBack(callback, None)
            if rc == 0:
                self._exception_cb = callback
            else:
                logger.warning(
                    "RegisterExceptionCallBack rc=0x%08X: события прибора не будут доходить", rc & 0xFFFFFFFF
                )

    @staticmethod
    def _select(ident: DeviceIdentity, entries: list[_Entry]) -> _Entry:
        if ident.kind == "serial":
            found = [e for e in entries if e.serial == ident.value]
        elif ident.kind == "ip":
            found = [e for e in entries if e.ip == ident.value]
        elif ident.kind == "index":
            logger.warning("open по index=%s: порядок перечисления не стабилен, используйте serial или ip", ident.value)
            try:
                position = int(ident.value)
            except ValueError:
                raise PortError("not_found", "open") from None
            found = entries[position : position + 1] if position >= 0 else []
        else:
            found = []
        if not found:
            raise PortError("not_found", "open")
        return found[0]

    def get_param(self, b: Binding) -> object:
        self._require_opened("get_param")
        cam, key = self._cam, b.key
        if b.vtype == "int":
            st = MVCC_INTVALUE_EX()
            rc = cam.MV_CC_GetIntValueEx(key, st)
            value: object = int(st.nCurValue)
        elif b.vtype == "float":
            st = MVCC_FLOATVALUE()
            rc = cam.MV_CC_GetFloatValue(key, st)
            value = float(st.fCurValue)
        elif b.vtype == "bool":
            flag = ctypes.c_bool()
            rc = cam.MV_CC_GetBoolValue(key, flag)
            value = bool(flag.value)
        elif b.vtype == "enum":
            st = MVCC_ENUMVALUE()
            rc = cam.MV_CC_GetEnumValue(key, st)
            if rc == 0:
                value = self._enum_symbolic(key, int(st.nCurValue), "get_param")
        else:
            raise PortError("other", "get_param")
        if rc != 0:
            raise _err(rc, "get_param")
        return value

    def set_param(self, b: Binding, value: object) -> None:
        self._require_opened("set_param")
        cam, key = self._cam, b.key
        if b.vtype == "int":
            number = int(value)  # type: ignore[call-overload]
            if key == PACKET_SIZE_KEY and number == 0:
                number = self._optimal_packet_size()
            rc = cam.MV_CC_SetIntValue(key, number)
        elif b.vtype == "float":
            rc = cam.MV_CC_SetFloatValue(key, float(value))  # type: ignore[arg-type]
        elif b.vtype == "bool":
            rc = cam.MV_CC_SetBoolValue(key, bool(value))
        elif b.vtype == "enum":
            if isinstance(value, str):
                rc = cam.MV_CC_SetEnumValueByString(key, value)
            else:
                rc = cam.MV_CC_SetEnumValue(key, int(value))  # type: ignore[call-overload]
        else:
            raise PortError("other", "set_param")
        if rc != 0:
            raise _err(rc, "set_param")

    def _optimal_packet_size(self) -> int:
        """`packet_size = 0` -> оптимальный размер пакета прибора (GigE); отказ -> `PortError`."""
        size = int(self._cam.MV_CC_GetOptimalPacketSize())
        if size >= 0x80000000:
            raise _err(size, "set_param")
        if size <= 0:
            raise PortError("other", "set_param")
        return size

    def describe_param(self, b: Binding) -> ParamInfo | None:
        self._require_opened("describe_param")
        cam, key = self._cam, b.key
        am = ctypes.c_int()
        if cam.MV_XML_GetNodeAccessMode(key, am) != 0:
            return ParamInfo(None, None, None, None, "NI")
        access = _ACCESS_BY_AM.get(am.value, "NI")
        if access not in ("RW", "RO"):
            return ParamInfo(None, None, None, None, access)  # закрытый узел не читаем: границ нет, не бросаем
        lo = hi = inc = None
        entries: tuple[str, ...] | None = None
        if b.vtype == "int":
            st = MVCC_INTVALUE_EX()
            if cam.MV_CC_GetIntValueEx(key, st) == 0:
                lo, hi, inc = int(st.nMin), int(st.nMax), int(st.nInc)
        elif b.vtype == "float":
            fst = MVCC_FLOATVALUE()
            if cam.MV_CC_GetFloatValue(key, fst) == 0:
                lo, hi = float(fst.fMin), float(fst.fMax)
        elif b.vtype == "enum":
            est = MVCC_ENUMVALUE()
            if cam.MV_CC_GetEnumValue(key, est) == 0:
                count = min(int(est.nSupportedNum), len(est.nSupportValue))
                entries = tuple(
                    self._enum_symbolic(key, int(est.nSupportValue[i]), "describe_param") for i in range(count)
                )
        return ParamInfo(lo, hi, inc, entries, access)

    def execute(self, b: Binding) -> None:
        self._require_opened("execute")
        if "software_trigger" not in self.capabilities:
            raise PortError("access", "execute")
        rc = self._cam.MV_CC_SetCommandValue(b.key)
        if rc != 0:
            raise _err(rc, "execute")

    def start_grabbing(self) -> None:
        self._require_opened("start_grabbing")
        if self._state == "grabbing":
            return
        rc = self._cam.MV_CC_StartGrabbing()
        if rc != 0:
            raise _err(rc, "start_grabbing")
        self._state = "grabbing"

    def get_frame(self, timeout_ms: int) -> RawFrame | None:
        if self._state != "grabbing":
            raise PortError("closed", "get_frame")
        cam = self._cam
        out = MV_FRAME_OUT()
        ctypes.memset(ctypes.byref(out), 0, ctypes.sizeof(out))
        rc = cam.MV_CC_GetImageBuffer(out, timeout_ms)
        if int(rc) & 0xFFFFFFFF in _TIMEOUT_CODES:
            return None
        if rc != 0:
            raise _err(rc, "get_frame")
        try:
            info = out.stFrameInfo
            width, height, frame_len = int(info.nWidth), int(info.nHeight), int(info.nFrameLen)
            name, bpp = _PIXEL_FORMATS.get(
                int(info.enPixelType), (f"pixel_0x{int(info.enPixelType) & 0xFFFFFFFF:08x}", 0)
            )
            pixels = width * height
            size = pixels * bpp if bpp else frame_len
            if size <= 0 or frame_len < size:
                raise PortError("other", "get_frame")
            # Копия до освобождения буфера; хвост дополнения кадра (frame_len > h*w*bpp) отрезается.
            data = bytearray(ctypes.string_at(out.pBufAddr, size))
            frame_num = int(info.nFrameNum)
        finally:
            free_rc = cam.MV_CC_FreeImageBuffer(out)
            if free_rc != 0:
                logger.warning("FreeImageBuffer rc=0x%08X", int(free_rc) & 0xFFFFFFFF)
        return RawFrame(data=data, width=width, height=height, pixel_format=name, frame_num=frame_num, extras={})

    def stop_grabbing(self) -> None:
        if self._state != "grabbing":
            return
        rc = self._cam.MV_CC_StopGrabbing()
        if rc != 0:
            logger.warning("StopGrabbing rc=0x%08X", int(rc) & 0xFFFFFFFF)
        self._state = "opened"

    def close(self) -> None:
        self.stop_grabbing()
        cam, self._cam = self._cam, None
        self._state = "closed"
        if cam is None:
            return
        rc = cam.MV_CC_CloseDevice()
        if rc != 0:
            logger.warning("CloseDevice rc=0x%08X", int(rc) & 0xFFFFFFFF)
        rc = cam.MV_CC_DestroyHandle()
        if rc != 0:
            logger.warning("DestroyHandle rc=0x%08X", int(rc) & 0xFFFFFFFF)
        self._exception_cb = None


def make_port(cam_cls: Any = None) -> MvsPort:
    """Свежий порт `mvs`. `cam_cls` — класс с интерфейсом `MvCamera` (фейк в тестах); по умолчанию настоящий."""
    if cam_cls is None:
        return MvsPort(MvCamera, available=lambda: _bindings.SDK_AVAILABLE)
    return MvsPort(cam_cls)
