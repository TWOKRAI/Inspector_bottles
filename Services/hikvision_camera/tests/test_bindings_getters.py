# -*- coding: utf-8 -*-
"""Task 0.3: обёртки MvCamera над геттерами/командами MVS на фейковой DLL.

Фейк записывает ``argtypes``, ``restype`` и аргументы вызова. Ожидаемые значения -- литералы
из заголовков SDK (CameraParams.h / MvCameraControl.h на машине), не выводятся из кода.
"""

from __future__ import annotations

import ctypes
from ctypes import byref, c_bool, c_int, c_uint
from unittest.mock import patch

import pytest

from Services.hikvision_camera.sdk import bindings, structures
from Services.hikvision_camera.sdk.bindings import EXCEPTION_CALLBACK, MvCamera
from Services.hikvision_camera.sdk.structures import (
    MVCC_ENUMENTRY,
    MVCC_ENUMVALUE,
    MVCC_INTVALUE,
    MVCC_INTVALUE_EX,
    MVCC_STRINGVALUE,
)

ERR = 0x80000106  # произвольный код ошибки SDK (старший бит -- признак ошибки)


class FakeFunc:
    """Функция фейковой DLL: пишет argtypes/restype/вызовы."""

    def __init__(self, ret: int) -> None:
        self.argtypes = None
        self.restype = None
        self.calls: list[tuple] = []
        self._ret = ret

    def __call__(self, *args):
        self.calls.append(args)
        return self._ret


class FakeDll:
    def __init__(self, ret: int = 0) -> None:
        self._ret = ret
        self._funcs: dict[str, FakeFunc] = {}

    def __getattr__(self, name: str) -> FakeFunc:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._funcs.setdefault(name, FakeFunc(self._ret))


@pytest.fixture
def dll():
    fake = FakeDll(ret=ERR)
    with patch.object(bindings, "_MvCamCtrldll", fake):
        yield fake


def _obj(arg):
    """Объект, на который указывает byref-аргумент."""
    return arg._obj


# (имя метода, фабрика аргументов); первый аргумент -- строковое имя узла
def _cases():
    return [
        ("MV_CC_GetIntValue", lambda: ("Width", MVCC_INTVALUE())),
        ("MV_CC_GetIntValueEx", lambda: ("Width", MVCC_INTVALUE_EX())),
        ("MV_CC_GetEnumValue", lambda: ("TriggerMode", MVCC_ENUMVALUE())),
        ("MV_CC_GetBoolValue", lambda: ("AcquisitionFrameRateEnable", c_bool())),
        ("MV_CC_SetEnumValueByString", lambda: ("TriggerSource", "Line0")),
        ("MV_CC_SetCommandValue", lambda: ("TriggerSoftware",)),
        ("MV_CC_GetEnumEntrySymbolic", lambda: ("TriggerMode", MVCC_ENUMENTRY())),
        ("MV_CC_GetStringValue", lambda: ("DeviceSerialNumber", MVCC_STRINGVALUE())),
        ("MV_XML_GetNodeAccessMode", lambda: ("Width", c_int())),
        ("MV_XML_GetNodeInterfaceType", lambda: ("Width", c_int())),
    ]


CASE_IDS = [c[0] for c in _cases()]


@pytest.mark.parametrize("name,make_args", _cases(), ids=CASE_IDS)
def test_restype_c_uint_and_code_returned(dll, name, make_args):
    rc = getattr(MvCamera(), name)(*make_args())
    assert dll._funcs[name].restype is c_uint
    assert rc == 0x80000106
    assert type(rc) is int


@pytest.mark.parametrize("name,make_args", _cases(), ids=CASE_IDS)
def test_argtypes_set_and_match_call(dll, name, make_args):
    """Атрибут именно ``argtypes`` (в старых обёртках опечатка ``argtype``)."""
    getattr(MvCamera(), name)(*make_args())
    func = dll._funcs[name]
    assert func.argtypes is not None
    assert len(func.argtypes) == len(func.calls[0])
    assert not hasattr(func, "argtype")


@pytest.mark.parametrize("name,make_args", _cases(), ids=CASE_IDS)
def test_non_ascii_name_raises_and_dll_not_called(dll, name, make_args):
    args = list(make_args())
    args[0] = "Режим"
    with pytest.raises(UnicodeEncodeError):
        getattr(MvCamera(), name)(*args)
    assert dll._funcs.get(name) is None or dll._funcs[name].calls == []


def test_get_enum_value_passes_handle_bytes_byref(dll):
    cam = MvCamera()
    st = MVCC_ENUMVALUE()
    cam.MV_CC_GetEnumValue("TriggerMode", st)
    (args,) = dll.MV_CC_GetEnumValue.calls
    assert args[0] is cam.handle
    assert args[1] == b"TriggerMode"
    assert _obj(args[2]) is st


def test_set_enum_value_by_string_passes_bytes_value(dll):
    cam = MvCamera()
    cam.MV_CC_SetEnumValueByString("TriggerSource", "Line0")
    (args,) = dll.MV_CC_SetEnumValueByString.calls
    assert args == (cam.handle, b"TriggerSource", b"Line0")


def test_set_enum_value_by_string_non_ascii_value_raises(dll):
    with pytest.raises(UnicodeEncodeError):
        MvCamera().MV_CC_SetEnumValueByString("TriggerSource", "Линия")
    assert dll.MV_CC_SetEnumValueByString.calls == []


def test_set_command_value_passes_bytes(dll):
    cam = MvCamera()
    cam.MV_CC_SetCommandValue("TriggerSoftware")
    (args,) = dll.MV_CC_SetCommandValue.calls
    assert args == (cam.handle, b"TriggerSoftware")


def test_get_string_value_passes_bytes(dll):
    st = MVCC_STRINGVALUE()
    MvCamera().MV_CC_GetStringValue("DeviceSerialNumber", st)
    (args,) = dll.MV_CC_GetStringValue.calls
    assert args[1] == b"DeviceSerialNumber"
    assert _obj(args[2]) is st


def test_get_enum_entry_symbolic_passes_bytes_and_byref(dll):
    entry = MVCC_ENUMENTRY()
    MvCamera().MV_CC_GetEnumEntrySymbolic("TriggerMode", entry)
    (args,) = dll.MV_CC_GetEnumEntrySymbolic.calls
    assert args[1] == b"TriggerMode"
    assert _obj(args[2]) is entry


def test_get_int_value_ex_passes_byref(dll):
    st = MVCC_INTVALUE_EX()
    MvCamera().MV_CC_GetIntValueEx("Width", st)
    (args,) = dll.MV_CC_GetIntValueEx.calls
    assert args[1] == b"Width"
    assert _obj(args[2]) is st


@pytest.mark.parametrize("name", ["MV_XML_GetNodeAccessMode", "MV_XML_GetNodeInterfaceType"])
def test_xml_node_accepts_byref_from_caller_without_double_wrap(dll, name):
    mode = c_int()
    ref = byref(mode)
    getattr(MvCamera(), name)("Width", ref)
    (args,) = dll._funcs[name].calls
    assert args[1] == b"Width"
    assert args[2] is ref  # byref вызывающего передан как есть, не byref(byref(..))


@pytest.mark.parametrize("name", ["MV_XML_GetNodeAccessMode", "MV_XML_GetNodeInterfaceType"])
def test_xml_node_accepts_plain_ctype_and_wraps_byref(dll, name):
    mode = c_int()
    getattr(MvCamera(), name)("Width", mode)
    (args,) = dll._funcs[name].calls
    assert _obj(args[2]) is mode


def test_get_bool_value_wraps_byref(dll):
    flag = c_bool()
    MvCamera().MV_CC_GetBoolValue("AcquisitionFrameRateEnable", flag)
    (args,) = dll.MV_CC_GetBoolValue.calls
    assert args[1] == b"AcquisitionFrameRateEnable"
    assert _obj(args[2]) is flag


# --- RegisterExceptionCallBack -------------------------------------------------
def test_exception_callback_prototype_is_uint_voidp_returning_none():
    """MvCameraControl.h:1362 -- void(__stdcall*)(unsigned int nMsgType, void* pUser)."""
    seen = []
    cb = EXCEPTION_CALLBACK(lambda msg, user: seen.append((msg, user)))
    cb(0x4005, None)  # реальный ctypes-вызов; 0x4005 = MV_CC_STREAM_EXCEPTION_DISCONNECTED
    assert seen == [(0x4005, None)]
    assert EXCEPTION_CALLBACK._restype_ is None
    assert EXCEPTION_CALLBACK._argtypes_ == (c_uint, ctypes.c_void_p)


def test_register_exception_callback_keeps_reference_and_passes_it(dll):
    cam = MvCamera()
    cb = EXCEPTION_CALLBACK(lambda msg, user: None)
    rc = cam.MV_CC_RegisterExceptionCallBack(cb, None)
    func = dll.MV_CC_RegisterExceptionCallBack
    assert rc == 0x80000106
    assert func.restype is c_uint
    assert func.argtypes is not None and len(func.argtypes) == 3
    assert func.argtypes[1] is EXCEPTION_CALLBACK
    (args,) = func.calls
    assert args[0] is cam.handle
    assert args[1] is cb
    assert args[2] is None


def test_register_exception_callback_replaces_kept_reference():
    with patch.object(bindings, "_MvCamCtrldll", FakeDll(ret=0)):
        cam = MvCamera()
        first = EXCEPTION_CALLBACK(lambda m, u: None)
        second = EXCEPTION_CALLBACK(lambda m, u: None)
        assert cam.MV_CC_RegisterExceptionCallBack(first) == 0
        assert cam._exception_cb is first  # GC-ловушка: пока жив MvCamera и rc == 0, колбэк жив
        assert cam.MV_CC_RegisterExceptionCallBack(second) == 0
        assert cam._exception_cb is second


# --- RegisterExceptionCallBack на НАСТОЯЩЕМ ctypes-объекте (from_param работает) ---
# Ревью W1a р.1, п.3: register(cb); register(None) -> ArgumentError, а ссылка уже стёрта.
_RegisterProto = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    c_uint, ctypes.c_void_p, EXCEPTION_CALLBACK, ctypes.c_void_p
)


class RealCtypesDll:
    """Фейковая DLL, у которой RegisterExceptionCallBack -- настоящий ctypes-указатель на функцию."""

    def __init__(self, on_call) -> None:
        self.calls: list[EXCEPTION_CALLBACK] = []

        def impl(handle, cb, user):
            self.calls.append(cb)
            return on_call(cb)

        self.MV_CC_RegisterExceptionCallBack = _RegisterProto(impl)  # держим thunk


def test_register_none_passes_null_callback_without_argument_error():
    fake = RealCtypesDll(lambda cb: 0)
    with patch.object(bindings, "_MvCamCtrldll", fake):
        cam = MvCamera()
        first = EXCEPTION_CALLBACK(lambda m, u: None)
        assert cam.MV_CC_RegisterExceptionCallBack(first) == 0
        assert cam.MV_CC_RegisterExceptionCallBack(None) == 0  # раньше: ctypes.ArgumentError
    # ctypes отдаёт в Python-реализацию новый объект-обёртку: сравниваем адреса
    assert ctypes.cast(fake.calls[0], ctypes.c_void_p).value == ctypes.cast(first, ctypes.c_void_p).value
    assert ctypes.cast(fake.calls[1], ctypes.c_void_p).value is None  # NULL-указатель на функцию
    assert cam._exception_cb is None  # SDK колбэк больше не держит


def test_old_callback_held_until_call_returned():
    cam_box = []
    held_during_call = []

    def on_call(cb):
        held_during_call.append(cam_box[0]._exception_cb)
        return 0

    fake = RealCtypesDll(on_call)
    with patch.object(bindings, "_MvCamCtrldll", fake):
        cam = MvCamera()
        cam_box.append(cam)
        first = EXCEPTION_CALLBACK(lambda m, u: None)
        second = EXCEPTION_CALLBACK(lambda m, u: None)
        cam.MV_CC_RegisterExceptionCallBack(first)
        cam.MV_CC_RegisterExceptionCallBack(second)
        cam.MV_CC_RegisterExceptionCallBack(None)
    assert held_during_call == [None, first, second]  # внутри вызова держится прежний
    assert cam._exception_cb is None


@pytest.mark.parametrize("second_arg", ["new_callback", "none"])
def test_old_callback_kept_when_register_fails(second_arg):
    results = iter([0, 0x80000106])
    fake = RealCtypesDll(lambda cb: next(results))
    with patch.object(bindings, "_MvCamCtrldll", fake):
        cam = MvCamera()
        first = EXCEPTION_CALLBACK(lambda m, u: None)
        assert cam.MV_CC_RegisterExceptionCallBack(first) == 0
        second = EXCEPTION_CALLBACK(lambda m, u: None) if second_arg == "new_callback" else None
        rc = cam.MV_CC_RegisterExceptionCallBack(second)
    assert rc == 0x80000106
    assert cam._exception_cb is first  # SDK по-прежнему держит first


def test_first_registration_failure_holds_nothing():
    fake = RealCtypesDll(lambda cb: 0x80000106)
    with patch.object(bindings, "_MvCamCtrldll", fake):
        cam = MvCamera()
        cam.MV_CC_RegisterExceptionCallBack(EXCEPTION_CALLBACK(lambda m, u: None))
    assert cam._exception_cb is None


# --- структуры и константы (заголовок CameraParams.h) ---------------------------
def test_sizeof_структур():
    assert ctypes.sizeof(MVCC_ENUMENTRY) == 84
    assert ctypes.sizeof(MVCC_INTVALUE_EX) == 96


def test_structure_field_names_match_header():
    """Опечатка в _fields_ молчит на setattr -- проверяем имена и порядок (CameraParams.h:952-959, :974-983)."""
    assert [f[0] for f in MVCC_ENUMENTRY._fields_] == ["nValue", "chSymbolic", "nReserved"]
    assert [f[0] for f in MVCC_INTVALUE_EX._fields_] == [
        "nCurValue",
        "nMax",
        "nMin",
        "nInc",
        "nReserved",
    ]
    e = MVCC_ENUMENTRY()
    e.nValue = 7
    e.chSymbolic = b"Off"
    assert (e.nValue, e.chSymbolic) == (7, b"Off")
    x = MVCC_INTVALUE_EX()
    x.nCurValue = 2**40
    x.nInc = 4
    assert (x.nCurValue, x.nInc) == (2**40, 4)


def test_structure_field_offsets():
    assert MVCC_ENUMENTRY.chSymbolic.offset == 4
    assert MVCC_ENUMENTRY.nReserved.offset == 68
    assert MVCC_INTVALUE_EX.nInc.offset == 24
    assert MVCC_INTVALUE_EX.nReserved.offset == 32


def test_access_mode_and_interface_type_constants_match_header():
    """CameraParams.h:925-934 (MV_XML_AccessMode), :908-922 (MV_XML_InterfaceType)."""
    assert (structures.AM_NI, structures.AM_NA, structures.AM_WO) == (0, 1, 2)
    assert (structures.AM_RO, structures.AM_RW) == (3, 4)
    assert (structures.AM_Undefined, structures.AM_CycleDetect) == (5, 6)
    assert structures.IFT_IValue == 0
    assert structures.IFT_IInteger == 2
    assert structures.IFT_ICommand == 4
    assert structures.IFT_IEnumeration == 9
    assert structures.IFT_IPort == 11


# --- реальная DLL (без камеры): экспорты на месте -------------------------------
@pytest.mark.skipif(not bindings.SDK_AVAILABLE, reason="MVS SDK не установлена")
@pytest.mark.parametrize("name", CASE_IDS + ["MV_CC_RegisterExceptionCallBack"])
def test_real_dll_exports_wrapped_functions(name):
    assert getattr(bindings._MvCamCtrldll, name, None) is not None


def test_initialize_finalize_not_wrapped():
    """MV_CC_Initialize/Finalize нет в SDK 0x04020003 -- обёрток быть не должно."""
    assert not hasattr(MvCamera, "MV_CC_Initialize")
    assert not hasattr(MvCamera, "MV_CC_Finalize")
