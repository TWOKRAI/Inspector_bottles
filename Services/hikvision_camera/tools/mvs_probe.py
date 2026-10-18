"""Зонд MVS (Task 0.4): запись дерева узлов камеры в JSON и опыты H1/H2/H5 на железе.

Только чтение по умолчанию. Запись узлов -- только с --write и с --orig <файл>: исходные значения
сохраняются в --orig ДО первой записи, после опыта узлы возвращаются в обратном порядке записи,
каждый читается обратно. Схема файла -- plans/2026-10-18_camera-device-service/recording-schema.md
(schema_version 1; --orig -- та же схема, states ["idle"], только писанные узлы).

Режимы (ровно один):
  --dump --out <файл.json>   снимок курируемых узлов: idle и во время захвата (grabbing).
  --experiment h1|h2|h5      H1: запись TriggerMode после StopGrabbing (--delay 0 и 1.0);
                             H2: запись TriggerMode до StartGrabbing, --mode same|split (потоки);
                             H5: запись Width во время захвата (ожидается 0x80000106), затем чтение.
  --restore <orig.json>      только возврат узлов из файла --orig (после оборванного опыта).

Строки опыта (stdout) -- это и есть данные:
  node=<имя> rc=0x........ read=<значение> ms=<мс записи> thread=<поток>
  restore node=<имя> rc=0x........ read=<значение> thread=<поток>
  RESTORE MISMATCH node=<имя> want=<..> got=<..>      (код выхода 2)

Коды выхода: 0 -- ок (отказ записи H5 -- данные, не ошибка); 1 -- отказ/камера не найдена/ошибка;
2 -- только RESTORE MISMATCH.

Запуск (из корня репозитория, закрыть IDMVS/MVS Client -- прибор отпускается ~10 с после их закрытия):
  PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe -m Services.hikvision_camera.tools.mvs_probe <аргументы>
  --fake : тот же код на FakeMvCamera (без железа). Без --serial/--ip на реальном приборе --
  только список камер (devices=<n>) и отказ.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from Services.hikvision_camera.sdk.bindings import MvCamera
from Services.hikvision_camera.sdk.constants import MV_GIGE_DEVICE, MV_USB_DEVICE
from Services.hikvision_camera.sdk.errors import MV_E_GC_ACCESS, MV_E_GC_ARGUMENT, MV_E_GC_GENERIC, MV_E_GC_RANGE
from Services.hikvision_camera.sdk.structures import (
    AM_NA,
    AM_NI,
    AM_RO,
    AM_RW,
    AM_WO,
    IFT_IBoolean,
    IFT_ICommand,
    IFT_IEnumeration,
    IFT_IFloat,
    IFT_IInteger,
    IFT_IString,
    MV_CC_DEVICE_INFO,
    MV_CC_DEVICE_INFO_LIST,
    MVCC_ENUMENTRY,
    MVCC_ENUMVALUE,
    MVCC_FLOATVALUE,
    MVCC_INTVALUE_EX,
    MVCC_STRINGVALUE,
)

SCHEMA_VERSION = 1
THREAD_JOIN_S = 60.0  # потолок ожидания потока опыта H2

CURATED_NODES = (
    "TriggerMode", "TriggerSource", "ExposureTime", "ExposureAuto", "Gain", "GainAuto",
    "AcquisitionFrameRate", "AcquisitionFrameRateEnable", "Width", "Height", "PixelFormat",
    "GevSCPSPacketSize", "GevSCPD", "DeviceSerialNumber", "DeviceModelName",
)  # fmt: skip

# опыт -> (узел, момент записи: pre_start | post_stop | during_grab)
EXPERIMENTS = {
    "h1": ("TriggerMode", "post_stop"),
    "h2": ("TriggerMode", "pre_start"),
    "h5": ("Width", "during_grab"),
}

# Методы камеры, которые зовёт зонд: фейк обязан иметь их все с теми же параметрами (тест сверяет с MvCamera).
USED_CAMERA_METHODS = (
    "MV_CC_CreateHandle", "MV_CC_DestroyHandle", "MV_CC_OpenDevice", "MV_CC_CloseDevice",
    "MV_CC_StartGrabbing", "MV_CC_StopGrabbing",
    "MV_CC_GetIntValueEx", "MV_CC_GetFloatValue", "MV_CC_GetEnumValue", "MV_CC_GetEnumEntrySymbolic",
    "MV_CC_GetBoolValue", "MV_CC_GetStringValue",
    "MV_XML_GetNodeAccessMode", "MV_XML_GetNodeInterfaceType",
    "MV_CC_SetEnumValue", "MV_CC_SetEnumValueByString", "MV_CC_SetIntValue", "MV_CC_SetFloatValue",
    "MV_CC_SetBoolValue",
)  # fmt: skip

_TYPE_BY_IFT = {
    IFT_IInteger: "int",
    IFT_IFloat: "float",
    IFT_IEnumeration: "enum",
    IFT_IBoolean: "bool",
    IFT_IString: "string",
    IFT_ICommand: "command",
}
# AM_Undefined / AM_CycleDetect -- внутренние значения SDK; в схеме их нет, пишем NI (узел недоступен для зонда)
_ACCESS_BY_AM = {AM_NI: "NI", AM_NA: "NA", AM_WO: "WO", AM_RO: "RO", AM_RW: "RW"}


class ProbeError(RuntimeError):
    """Отказ или сбой зонда с понятным текстом (код выхода 1)."""


def _hex(rc: int) -> str:
    return f"0x{rc & 0xFFFFFFFF:08X}"


def _show(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _tname() -> str:
    return threading.current_thread().name


# ----------------------------------------------------------------------------- устройства


@dataclass(frozen=True)
class DeviceEntry:
    serial: str
    ip: str
    model: str
    info: Any = None  # MV_CC_DEVICE_INFO для CreateHandle (на фейке -- None)


def _text(buf: Any) -> str:
    return bytes(buf).split(b"\0", 1)[0].decode("ascii", errors="replace")


def _ip_text(n: int) -> str:
    return f"{(n >> 24) & 0xFF}.{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"


def entry_from_info(info: MV_CC_DEVICE_INFO) -> DeviceEntry:
    """Серийный номер, IP и модель из структуры перечисления (chSerialNumber / nCurrentIp)."""
    if info.nTLayerType == MV_GIGE_DEVICE:
        gi = info.SpecialInfo.stGigEInfo
        return DeviceEntry(_text(gi.chSerialNumber), _ip_text(gi.nCurrentIp), _text(gi.chModelName), info)
    if info.nTLayerType == MV_USB_DEVICE:
        ui = info.SpecialInfo.stUsb3VInfo
        return DeviceEntry(_text(ui.chSerialNumber), "", _text(ui.chModelName), info)
    return DeviceEntry("", "", "", info)


class MvsBackend:
    """Настоящий SDK: перечисление и новый MvCamera."""

    def __init__(self) -> None:
        self._list: MV_CC_DEVICE_INFO_LIST | None = None  # держит память структур, на которые ссылаются entry.info

    def sdk_version(self) -> int:
        return int(MvCamera.MV_CC_GetSDKVersion())

    def enum_devices(self) -> list[DeviceEntry]:
        dev_list = MV_CC_DEVICE_INFO_LIST()
        rc = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, dev_list)
        if rc != 0:
            raise ProbeError(f"MV_CC_EnumDevices rc={_hex(rc)}")
        self._list = dev_list
        ptr = ctypes.POINTER(MV_CC_DEVICE_INFO)
        return [entry_from_info(ctypes.cast(dev_list.pDeviceInfo[i], ptr).contents) for i in range(dev_list.nDeviceNum)]

    def new_camera(self) -> MvCamera:
        return MvCamera()


# ----------------------------------------------------------------------------- фейк


def _enum_node(entries: dict[str, int], value: str, **kw: Any) -> dict:
    return {"type": "enum", "entries": entries, "value": entries[value], **kw}


def _default_nodes() -> dict[str, dict]:
    locked = {"locked": True}  # заперт при захвате: доступ RO, запись -> 0x80000106
    return {
        "TriggerMode": _enum_node({"Off": 0, "On": 1}, "Off"),
        "TriggerSource": _enum_node({"Line0": 0, "Line1": 1, "Software": 7}, "Line0"),
        "ExposureTime": {"type": "float", "value": 10000.0, "min": 15.0, "max": 9999500.0},
        "ExposureAuto": _enum_node({"Off": 0, "Once": 1, "Continuous": 2}, "Off"),
        "Gain": {"type": "float", "value": 0.0, "min": 0.0, "max": 16.0},
        "GainAuto": _enum_node({"Off": 0, "Once": 1, "Continuous": 2}, "Off"),
        "AcquisitionFrameRate": {"type": "float", "value": 20.0, "min": 1.0, "max": 100.0},
        "AcquisitionFrameRateEnable": {"type": "bool", "value": False},
        "Width": {"type": "int", "value": 2448, "min": 64, "max": 4096, "inc": 8, **locked},
        "Height": {"type": "int", "value": 2048, "min": 64, "max": 3000, "inc": 2, **locked},
        "PixelFormat": _enum_node({"Mono8": 17301505, "BayerRG8": 17301513}, "Mono8", **locked),
        "GevSCPSPacketSize": {"type": "int", "value": 1500, "min": 220, "max": 9000, "inc": 4},
        "GevSCPD": {"type": "int", "value": 0, "min": 0, "max": 100000, "inc": 1},
        "DeviceSerialNumber": {"type": "string", "value": "FAKE0001", "access": "RO"},
        "DeviceModelName": {"type": "string", "value": "FAKE-CAM", "access": "RO"},
    }


class FakeMvCamera:
    """Фейк MvCamera на уровне MV_CC_*: те же имена и параметры, журнал вызовов, состояние узлов.

    ``calls`` -- журнал ``(имя, args)`` (args -- входные аргументы без выходных структур).
    Запись узла, запираемого при захвате (Width, Height, PixelFormat), во время захвата -> 0x80000106.
    Параметры: ``start_rc`` -- код отказа StartGrabbing; ``swallow`` -- пары ``(узел, значение)``,
    запись которых принимается (rc 0), но не ложится; ``missing`` -- узлы, которых нет;
    ``values`` -- начальные значения узлов (для enum -- имя).
    """

    SDK_VERSION = 0x04020003

    def __init__(
        self,
        *,
        start_rc: int = 0,
        swallow: tuple[tuple[str, Any], ...] = (),
        missing: tuple[str, ...] = (),
        values: dict[str, Any] | None = None,
        serial: str = "FAKE0001",
        ip: str = "192.168.1.10",
        model: str = "FAKE-CAM",
    ) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.nodes = _default_nodes()
        for name in missing:
            self.nodes.pop(name, None)
        for name, value in (values or {}).items():
            node = self.nodes[name]
            node["value"] = node["entries"][value] if node["type"] == "enum" else value
        self.grabbing = False
        self.start_rc = start_rc
        self.swallow = {tuple(p) for p in swallow}
        self.serial, self.ip, self.model = serial, ip, model

    # -- служебное ----------------------------------------------------------------

    def _journal(self, name: str, args: tuple) -> None:
        self.calls.append((name, args))

    def value(self, name: str) -> Any:
        """Текущее значение узла (для enum -- имя)."""
        node = self.nodes[name]
        if node["type"] == "enum":
            return next(k for k, v in node["entries"].items() if v == node["value"])
        return node["value"]

    def _node(self, name: str, *types: str) -> tuple[dict | None, int]:
        node = self.nodes.get(name)
        if node is None:
            return None, MV_E_GC_GENERIC
        if types and node["type"] not in types:
            return None, 0x80000108  # MV_E_GC_DYNAMICCAST
        return node, 0

    def _access(self, node: dict) -> str:
        if node.get("locked") and self.grabbing:
            return "RO"
        return node.get("access", "RW")

    def _set(self, name: str, types: tuple[str, ...], raw: Any, store: Any) -> int:
        node, rc = self._node(name, *types)
        if node is None:
            return rc
        if self._access(node) != "RW":
            return MV_E_GC_ACCESS
        if node["type"] == "enum" and raw not in node["entries"].values():
            return MV_E_GC_RANGE
        if node["type"] in ("int", "float") and not node["min"] <= raw <= node["max"]:
            return MV_E_GC_RANGE
        if (name, raw) in self.swallow:
            return 0  # принято, но не ложится
        node["value"] = store
        return 0

    # -- жизненный цикл ------------------------------------------------------------

    def MV_CC_CreateHandle(self, stDevInfo):
        self._journal("MV_CC_CreateHandle", ())
        return 0

    def MV_CC_DestroyHandle(self):
        self._journal("MV_CC_DestroyHandle", ())
        return 0

    def MV_CC_OpenDevice(self, nAccessMode=1, nSwitchoverKey=0):
        self._journal("MV_CC_OpenDevice", (nAccessMode, nSwitchoverKey))
        return 0

    def MV_CC_CloseDevice(self):
        self._journal("MV_CC_CloseDevice", ())
        return 0

    def MV_CC_StartGrabbing(self):
        self._journal("MV_CC_StartGrabbing", ())
        if self.start_rc == 0:
            self.grabbing = True
        return self.start_rc

    def MV_CC_StopGrabbing(self):
        self._journal("MV_CC_StopGrabbing", ())
        self.grabbing = False
        return 0

    # -- чтение --------------------------------------------------------------------

    def MV_CC_GetIntValueEx(self, strKey, stIntValue):
        self._journal("MV_CC_GetIntValueEx", (strKey,))
        node, rc = self._node(strKey, "int")
        if node is None:
            return rc
        stIntValue.nCurValue, stIntValue.nMax = node["value"], node["max"]
        stIntValue.nMin, stIntValue.nInc = node["min"], node["inc"]
        return 0

    def MV_CC_GetFloatValue(self, strKey, stFloatValue):
        self._journal("MV_CC_GetFloatValue", (strKey,))
        node, rc = self._node(strKey, "float")
        if node is None:
            return rc
        stFloatValue.fCurValue, stFloatValue.fMax, stFloatValue.fMin = node["value"], node["max"], node["min"]
        return 0

    def MV_CC_GetEnumValue(self, strKey, stEnumValue):
        self._journal("MV_CC_GetEnumValue", (strKey,))
        node, rc = self._node(strKey, "enum")
        if node is None:
            return rc
        stEnumValue.nCurValue = node["value"]
        stEnumValue.nSupportedNum = len(node["entries"])
        for i, v in enumerate(node["entries"].values()):
            stEnumValue.nSupportValue[i] = v
        return 0

    def MV_CC_GetEnumEntrySymbolic(self, strKey, stEnumEntry):
        self._journal("MV_CC_GetEnumEntrySymbolic", (strKey, stEnumEntry.nValue))
        node, rc = self._node(strKey, "enum")
        if node is None:
            return rc
        for name, v in node["entries"].items():
            if v == stEnumEntry.nValue:
                stEnumEntry.chSymbolic = name.encode("ascii")
                return 0
        return MV_E_GC_ARGUMENT

    def MV_CC_GetBoolValue(self, strKey, pbValue):
        self._journal("MV_CC_GetBoolValue", (strKey,))
        node, rc = self._node(strKey, "bool")
        if node is None:
            return rc
        pbValue.value = node["value"]
        return 0

    def MV_CC_GetStringValue(self, strKey, stStringValue):
        self._journal("MV_CC_GetStringValue", (strKey,))
        node, rc = self._node(strKey, "string")
        if node is None:
            return rc
        stStringValue.chCurValue = node["value"].encode("ascii")
        return 0

    def MV_XML_GetNodeAccessMode(self, strName, penAccessMode):
        self._journal("MV_XML_GetNodeAccessMode", (strName,))
        node, rc = self._node(strName)
        if node is None:
            return rc
        penAccessMode.value = {"RW": AM_RW, "RO": AM_RO, "WO": AM_WO}[self._access(node)]
        return 0

    def MV_XML_GetNodeInterfaceType(self, strName, penInterfaceType):
        self._journal("MV_XML_GetNodeInterfaceType", (strName,))
        node, rc = self._node(strName)
        if node is None:
            return rc
        penInterfaceType.value = next(k for k, v in _TYPE_BY_IFT.items() if v == node["type"])
        return 0

    # -- запись --------------------------------------------------------------------

    def MV_CC_SetEnumValue(self, strKey, nValue):
        self._journal("MV_CC_SetEnumValue", (strKey, nValue))
        return self._set(strKey, ("enum",), nValue, nValue)

    def MV_CC_SetEnumValueByString(self, strKey, strValue):
        self._journal("MV_CC_SetEnumValueByString", (strKey, strValue))
        node, rc = self._node(strKey, "enum")
        if node is None:
            return rc
        if strValue not in node["entries"]:
            return MV_E_GC_RANGE
        n = node["entries"][strValue]
        return self._set(strKey, ("enum",), n, n)

    def MV_CC_SetIntValue(self, strKey, nValue):
        self._journal("MV_CC_SetIntValue", (strKey, nValue))
        return self._set(strKey, ("int",), nValue, nValue)

    def MV_CC_SetFloatValue(self, strKey, fValue):
        self._journal("MV_CC_SetFloatValue", (strKey, fValue))
        return self._set(strKey, ("float",), fValue, fValue)

    def MV_CC_SetBoolValue(self, strKey, bValue):
        self._journal("MV_CC_SetBoolValue", (strKey, bValue))
        return self._set(strKey, ("bool",), bValue, bValue)


class FakeBackend:
    """Фейк перечисления: одна камера."""

    def __init__(self, camera: FakeMvCamera | None = None) -> None:
        self.camera = camera or FakeMvCamera()

    def sdk_version(self) -> int:
        return self.camera.SDK_VERSION

    def enum_devices(self) -> list[DeviceEntry]:
        c = self.camera
        return [DeviceEntry(c.serial, c.ip, c.model, None)]

    def new_camera(self) -> FakeMvCamera:
        return self.camera


# ----------------------------------------------------------------------------- чтение узлов


def _enum_symbolic(cam: Any, name: str, value: int) -> tuple[str | None, int]:
    entry = MVCC_ENUMENTRY()
    entry.nValue = value
    rc = cam.MV_CC_GetEnumEntrySymbolic(name, entry)
    return (entry.chSymbolic.decode("ascii", errors="replace") if rc == 0 else None), rc


def _read_enum(cam: Any, name: str, out: dict) -> None:
    st = MVCC_ENUMVALUE()
    rc = cam.MV_CC_GetEnumValue(name, st)
    if rc != 0:
        out["rc"] = rc
        return
    values = [int(st.nSupportValue[i]) for i in range(min(st.nSupportedNum, len(st.nSupportValue)))]
    out["entry_values"] = values
    names = [_enum_symbolic(cam, name, v)[0] for v in values]
    out["entries"] = None if any(n is None for n in names) else names
    if out["entries"] is not None and st.nCurValue in values:
        out["value"] = out["entries"][values.index(st.nCurValue)]
        return
    cur, rc = _enum_symbolic(cam, name, st.nCurValue)
    out["value"], out["rc"] = cur, rc


def read_node(cam: Any, name: str) -> dict:
    """Одно чтение узла: тип, доступ, значение, границы (все поля схемы; ``rc`` -- число)."""
    out: dict[str, Any] = {
        "type": None, "min": None, "max": None, "inc": None, "entries": None, "entry_values": None,
        "access": "NI", "value": None, "rc": 0,
    }  # fmt: skip
    ift = ctypes.c_int()
    rc = cam.MV_XML_GetNodeInterfaceType(name, ift)
    if rc != 0:
        out["rc"] = rc  # узла нет
        return out
    out["type"] = _TYPE_BY_IFT.get(ift.value)
    am = ctypes.c_int()
    if cam.MV_XML_GetNodeAccessMode(name, am) == 0:
        out["access"] = _ACCESS_BY_AM.get(am.value, "NI")
    kind = out["type"]
    if kind == "int":
        st = MVCC_INTVALUE_EX()
        out["rc"] = cam.MV_CC_GetIntValueEx(name, st)
        if out["rc"] == 0:
            out["value"], out["min"], out["max"], out["inc"] = st.nCurValue, st.nMin, st.nMax, st.nInc
    elif kind == "float":
        st = MVCC_FLOATVALUE()
        out["rc"] = cam.MV_CC_GetFloatValue(name, st)
        if out["rc"] == 0:
            out["value"], out["min"], out["max"] = float(st.fCurValue), float(st.fMin), float(st.fMax)
    elif kind == "enum":
        _read_enum(cam, name, out)
    elif kind == "bool":
        flag = ctypes.c_bool()
        out["rc"] = cam.MV_CC_GetBoolValue(name, flag)
        if out["rc"] == 0:
            out["value"] = bool(flag.value)
    elif kind == "string":
        st = MVCC_STRINGVALUE()
        out["rc"] = cam.MV_CC_GetStringValue(name, st)
        if out["rc"] == 0:
            out["value"] = st.chCurValue.decode("utf-8", errors="replace")
    # command и неподдерживаемые типы: значения нет, rc 0
    return out


def snapshot(cam: Any, names: tuple[str, ...] | list[str]) -> dict[str, dict]:
    return {name: read_node(cam, name) for name in names}


# ----------------------------------------------------------------------------- запись узлов


def write_node(cam: Any, spec: dict, name: str, value: Any) -> int:
    """Записать узел по записанному описанию (``type``, ``entries``, ``entry_values``); вернуть rc SDK."""
    kind = spec["type"]
    if kind == "int":
        return cam.MV_CC_SetIntValue(name, int(value))
    if kind == "float":
        return cam.MV_CC_SetFloatValue(name, float(value))
    if kind == "bool":
        return cam.MV_CC_SetBoolValue(name, bool(value))
    if kind == "enum":
        entries, numbers = spec.get("entries"), spec.get("entry_values")
        if entries and numbers and value in entries:
            return cam.MV_CC_SetEnumValue(name, numbers[entries.index(value)])
        return cam.MV_CC_SetEnumValueByString(name, str(value))
    raise ValueError(f"запись узла типа {kind!r} не поддержана зондом")


def experiment_value(spec: dict, current: Any) -> Any:
    """Значение для опыта: enum -- другая запись списка; int -- на шаг меньше (или больше у нижней границы)."""
    if spec["type"] == "enum":
        pool = spec.get("entries") or spec.get("entry_values") or []
        other = [v for v in pool if v != current]
        if not other:
            raise ProbeError("у enum-узла нет второго значения для опыта")
        return other[0]
    if spec["type"] == "int":
        inc = spec.get("inc") or 1
        lower = current - inc
        return lower if spec.get("min") is None or lower >= spec["min"] else current + inc
    raise ProbeError(f"опыт не умеет писать узел типа {spec['type']!r}")


def restore_nodes(cam: Any, recording: dict, names: list[str]) -> int:
    """Вернуть узлы к ``idle.value`` из записи в обратном порядке; каждый читать обратно. 2 -- расхождение."""
    code = 0
    for name in reversed(names):
        spec = recording["nodes"][name]
        want = spec["idle"]["value"]
        try:
            rc = write_node(cam, spec, name, want)
            got = read_node(cam, name)["value"]
            print(f"restore node={name} rc={_hex(rc)} read={_show(got)} thread={_tname()}", flush=True)
        except Exception as exc:  # noqa: BLE001 -- сбой одного узла не должен пропустить остальные
            got = f"error:{type(exc).__name__}"
            print(f"restore node={name} FAILED {type(exc).__name__}: {exc} thread={_tname()}", flush=True)
        if got != want:
            print(f"RESTORE MISMATCH node={name} want={_show(want)} got={_show(got)}", flush=True)
            code = 2
    return code


# ----------------------------------------------------------------------------- запись JSON


def _state(node: dict) -> dict:
    return {"value": node["value"], "access": node["access"], "rc": _hex(node["rc"])}


def build_recording(
    entry: DeviceEntry,
    sdk_version: int,
    names: list[str] | tuple[str, ...],
    idle: dict[str, dict],
    grabbing: dict[str, dict] | None,
) -> dict:
    nodes: dict[str, dict] = {}
    for name in names:
        i = idle[name]
        node: dict[str, Any] = {k: i[k] for k in ("type", "min", "max", "inc", "entries")}
        if i["type"] == "enum":
            node["entry_values"] = i["entry_values"]
        node["idle"] = _state(i)
        if grabbing is not None:
            node["grabbing"] = _state(grabbing[name])
        nodes[name] = node
    return {
        "schema_version": SCHEMA_VERSION,
        "vendor": "mvs",
        "sdk_version": f"0x{sdk_version:08X}",
        "device": {"model": entry.model, "serial": entry.serial},
        "states": ["idle", "grabbing"] if grabbing is not None else ["idle"],
        "nodes": nodes,
    }


def save_json(path: str, doc: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_recording(path: str) -> dict:
    """Загрузчик --restore: неизвестный schema_version -> ValueError с именем ключа, без значения."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"ключ schema_version не поддержан (поддержан только {SCHEMA_VERSION})")
    if not isinstance(doc.get("nodes"), dict):
        raise ValueError("нет ключа nodes")
    return doc


# ----------------------------------------------------------------------------- камера


def open_camera(backend: Any, entry: DeviceEntry) -> Any:
    cam = backend.new_camera()
    rc = cam.MV_CC_CreateHandle(entry.info)
    if rc != 0:
        raise ProbeError(f"MV_CC_CreateHandle rc={_hex(rc)}")
    rc = cam.MV_CC_OpenDevice()
    if rc != 0:
        cam.MV_CC_DestroyHandle()
        raise ProbeError(
            f"MV_CC_OpenDevice rc={_hex(rc)} (камеру держит другой клиент? IDMVS закрыть, подождать ~10 с)"
        )
    return cam


def _step(label: str, fn: Any) -> int:
    """Вызов, не прерывающий уборку: сбой печатается, код возвращается."""
    try:
        rc = fn()
    except Exception as exc:  # noqa: BLE001
        print(f"{label} FAILED {type(exc).__name__}: {exc}", flush=True)
        return -1
    if rc:
        print(f"{label} rc={_hex(rc)}", flush=True)
    return rc


def close_camera(cam: Any) -> None:
    _step("close_device", cam.MV_CC_CloseDevice)
    _step("destroy_handle", cam.MV_CC_DestroyHandle)


def _run_in_thread(name: str, fn: Any) -> None:
    """Единственный поток зонда (опыт H2): выполнить fn в потоке name, присоединить, пробросить ошибку."""
    errors: list[BaseException] = []

    def target() -> None:
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001 -- ошибка потока уходит в главный
            errors.append(exc)

    worker = threading.Thread(target=target, name=name, daemon=True)
    worker.start()
    worker.join(THREAD_JOIN_S)
    if worker.is_alive():
        raise ProbeError(f"поток {name} не завершился за {THREAD_JOIN_S:g} с")
    if errors:
        raise errors[0]


# ----------------------------------------------------------------------------- режимы


def run_dump(backend: Any, entry: DeviceEntry, args: argparse.Namespace) -> int:
    cam = open_camera(backend, entry)
    grabbing = False
    idle: dict[str, dict] = {}
    grab: dict[str, dict] | None = None
    try:
        idle = snapshot(cam, CURATED_NODES)
        rc = cam.MV_CC_StartGrabbing()
        if rc == 0:
            grabbing = True
            grab = snapshot(cam, CURATED_NODES)
        else:
            print(f"start_grabbing rc={_hex(rc)}: состояние grabbing не записано", flush=True)
    finally:
        if grabbing:
            _step("stop_grabbing", cam.MV_CC_StopGrabbing)
        close_camera(cam)
    doc = build_recording(entry, backend.sdk_version(), CURATED_NODES, idle, grab)
    save_json(args.out, doc)
    print(f"dump saved nodes={len(doc['nodes'])} states={doc['states']}", flush=True)
    return 0


def run_restore(backend: Any, entry: DeviceEntry, recording: dict) -> int:
    cam = open_camera(backend, entry)
    try:
        return restore_nodes(cam, recording, list(recording["nodes"]))
    finally:
        close_camera(cam)


class Session:
    """Опыт H1/H2/H5: фаза A (открыть, прочитать исходные, сохранить --orig, старт), фаза B (стоп, возврат, закрыть)."""

    def __init__(self, backend: Any, entry: DeviceEntry, args: argparse.Namespace) -> None:
        self.backend, self.entry, self.a = backend, entry, args
        self.node, self.stage = EXPERIMENTS[args.experiment]
        self.cam: Any = None
        self.grabbing = False
        self.recording: dict = {}
        self.written: list[str] = []
        self.finished = False
        self.code = 0

    def phase_a(self) -> None:
        print(f"[phase_a thread={_tname()}]", flush=True)
        self.cam = open_camera(self.backend, self.entry)
        idle = snapshot(self.cam, [self.node])
        n = idle[self.node]
        print(f"orig node={self.node} value={_show(n['value'])} access={n['access']} rc={_hex(n['rc'])}", flush=True)
        self.recording = build_recording(self.entry, self.backend.sdk_version(), [self.node], idle, None)
        if self.a.write:
            if n["type"] not in ("int", "enum") or n["value"] is None:
                raise ProbeError(f"узел {self.node} не читается или не того типа: без исходного значения не пишу")
            save_json(self.a.orig, self.recording)  # ДО первой записи
            print(f"orig saved; вручную (IDMVS): {self.node}={_show(n['value'])}", flush=True)
        if self.stage == "pre_start":
            self.write_experiment()
        rc = self.cam.MV_CC_StartGrabbing()
        if rc != 0:
            raise ProbeError(f"MV_CC_StartGrabbing rc={_hex(rc)}")
        self.grabbing = True

    def phase_b(self) -> None:
        print(f"[phase_b thread={_tname()}]", flush=True)
        if self.a.seconds:
            time.sleep(self.a.seconds)
        if self.stage == "during_grab":
            self.write_experiment()
        self.stop()
        if self.a.delay:
            time.sleep(self.a.delay)
        if self.stage == "post_stop":
            self.write_experiment()
        self.finish()

    def stop(self) -> None:
        if self.grabbing:
            self.grabbing = False
            _step("stop_grabbing", self.cam.MV_CC_StopGrabbing)

    def write_experiment(self) -> None:
        name = self.node
        if not self.a.write:
            print(f"skip write node={name} (нет --write)", flush=True)
            return
        spec = self.recording["nodes"][name]
        value = experiment_value(spec, spec["idle"]["value"])
        self.written.append(name)  # до записи: возврат нужен и при отказе, и при исключении
        print(f"write node={name} value={_show(value)} thread={_tname()}", flush=True)
        t0 = time.perf_counter()
        rc = write_node(self.cam, spec, name, value)
        ms = (time.perf_counter() - t0) * 1000
        back = read_node(self.cam, name)["value"]
        print(f"node={name} rc={_hex(rc)} read={_show(back)} ms={ms:.2f} thread={_tname()}", flush=True)

    def finish(self) -> int:
        """Стоп (если идёт захват) -> возврат -> закрыть. Идемпотентно; безопасно вызывать из любого потока."""
        if self.finished or self.cam is None:
            return self.code
        self.finished = True
        self.stop()
        if self.written:
            self.code = restore_nodes(self.cam, self.recording, self.written)
        close_camera(self.cam)
        return self.code


def run_experiment(backend: Any, entry: DeviceEntry, args: argparse.Namespace) -> int:
    session = Session(backend, entry, args)
    failure: BaseException | None = None
    try:
        if args.mode == "split":
            _run_in_thread("A-open", session.phase_a)
            _run_in_thread("B-capture", session.phase_b)
        else:
            session.phase_a()
            session.phase_b()
    except Exception as exc:  # noqa: BLE001 -- сначала возврат, потом отчёт
        failure = exc
    finally:
        session.finish()  # возврат и при Ctrl+C
    if failure is not None:
        print(f"ОШИБКА опыта: {type(failure).__name__}: {failure}", flush=True)
    if session.code == 2:
        return 2
    return 1 if failure is not None else 0


# ----------------------------------------------------------------------------- CLI


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # код 2 зарезервирован под RESTORE MISMATCH
        self.print_usage(sys.stderr)
        print(f"ОТКАЗ: {message}", file=sys.stderr)
        sys.exit(1)


def _bounded(lo: float, hi: float, flag: str) -> Any:
    def parse(s: str) -> float:
        v = float(s)
        if not lo <= v <= hi:
            raise argparse.ArgumentTypeError(f"{flag} должен быть от {lo:g} до {hi:g}")
        return v

    return parse


def build_parser() -> argparse.ArgumentParser:
    ap = _Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dump", action="store_true", help="снимок курируемых узлов в --out")
    mode.add_argument("--experiment", choices=sorted(EXPERIMENTS), help="опыт H1 / H2 / H5")
    mode.add_argument("--restore", metavar="ORIG_JSON", help="только вернуть узлы из файла --orig")
    ap.add_argument("--serial", help="серийный номер камеры (chSerialNumber)")
    ap.add_argument("--ip", help="IP камеры (nCurrentIp)")
    ap.add_argument("--out", help="файл снимка для --dump")
    ap.add_argument("--write", action="store_true", help="разрешить запись узлов (нужен --orig)")
    ap.add_argument("--orig", help="куда сохранить исходные значения ДО первой записи")
    ap.add_argument("--mode", choices=("same", "split"), default="same", help="H2: потоки same|split")
    ap.add_argument("--delay", type=_bounded(0, 60, "--delay"), default=0.0, help="пауза после StopGrabbing, с")
    ap.add_argument("--seconds", type=_bounded(0, 30, "--seconds"), default=1.0, help="захват до стопа, с")
    ap.add_argument("--fake", action="store_true", help="без железа: FakeMvCamera")
    return ap


def _validate(a: argparse.Namespace) -> str | None:
    if a.dump and not a.out:
        return "--dump требует --out"
    if a.write and not (a.experiment and a.orig):
        return "--write требует --experiment и --orig (исходные сохраняются до первой записи)"
    if a.orig and not a.write:
        return "--orig имеет смысл только с --write"
    if a.mode == "split" and a.experiment != "h2":
        return "--mode split только для --experiment h2"
    return None


def _select(entries: list[DeviceEntry], a: argparse.Namespace) -> DeviceEntry:
    if not a.serial and not a.ip:
        if a.fake and entries:
            return entries[0]
        raise ProbeError("укажи --serial или --ip (чтобы не взять чужую камеру)")
    found = [e for e in entries if (not a.serial or e.serial == a.serial) and (not a.ip or e.ip == a.ip)]
    if len(found) != 1:
        raise ProbeError(f"камера serial={a.serial or '-'} ip={a.ip or '-'}: подходит {len(found)} из {len(entries)}")
    return found[0]


def main(argv: list[str] | None = None, *, backend: Any = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = build_parser().parse_args(argv)
    bad = _validate(a)
    if bad:
        print(f"ОТКАЗ: {bad}", flush=True)
        return 1
    if a.fake:
        backend = backend or FakeBackend()
    elif backend is None:
        backend = MvsBackend()
    try:
        entries = backend.enum_devices()  # перечислить до вопроса
    except Exception as exc:  # noqa: BLE001
        print("devices=0", flush=True)
        print(f"ОТКАЗ: перечисление не удалось: {type(exc).__name__}: {exc}", flush=True)
        return 1
    print(f"devices={len(entries)}", flush=True)
    for e in entries:
        print(f"device serial={e.serial} ip={e.ip or '-'} model={e.model}", flush=True)
    try:
        recording = load_recording(a.restore) if a.restore else None
        entry = _select(entries, a)
        if a.dump:
            return run_dump(backend, entry, a)
        if recording is not None:
            return run_restore(backend, entry, recording)
        return run_experiment(backend, entry, a)
    except (ProbeError, ValueError, OSError) as exc:
        print(f"ОТКАЗ: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
