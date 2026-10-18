# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты Task 2.1 (get/set узлов GenICam в ``sdk/`` и зонд ``mvcr_probe``): RED до реализации.

Источник истины — раздел «Task 2.1» плана ``plans/code-reader-gui/phase-2.md`` (DESIGN и приёмка)
и заголовки SDK (``Development.zip`` -> ``MvCodeReaderParams.h`` 381-417, ``MvCodeReaderCtrl.h``
603-753, ``MvCodeReaderErrorDefine.h``). Реализацию тесты не видели.

Размеры структур посчитаны вручную по заголовку (MSVC x64, ``MV_CODEREADER_MAX_XML_SYMBOLIC_NUM`` = 64):

    INTVALUE_EX = 4 * int64 (32) + uint[16] (64)             = 96
    FLOATVALUE  = 3 * float (12) + uint[4] (16)              = 28
    ENUMVALUE   = 2 * uint (8) + uint[64] (256) + uint[4]    = 280

Ожидаемые значения — ЛИТЕРАЛЫ. Фейковая DLL пишет в out-структуры по байтовым смещениям
(``struct.pack``), а не через тестируемые ctypes-структуры: неверная раскладка не может
«согласоваться сама с собой».

ПРЕДПОЛОЖЕНИЯ, которых в DESIGN нет (формулировки строк ``ORIG``/``NODE``/``RESTORE*`` взяты из DESIGN буквально):
  * ключ узла в публичных методах ``MvCodeReaderApi`` — ``str`` (в DLL уходит ``bytes``);
  * зонд печатает в stdout; ``parser.error`` проявляется как ``SystemExit(2)`` либо возврат ``2``.
"""

from __future__ import annotations

import ctypes
import importlib
import os
import re
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

E_GC_RANGE = 0x80020102
E_GC_ACCESS = 0x80020106
E_GC_ACCESS_SIGNED = -2147352314  # 0x80020106 как знаковый int (restype = c_int)
E_NODATA = 0x80020006
HANDLE = 0x5150


def _sdk(name: str = "") -> Any:
    """Импорт внутри теста: RED приходит отдельно на каждом тесте."""
    return importlib.import_module("Services.code_reader.sdk" + (f".{name}" if name else ""))


def _run(fn: Any, deadline: float = 20.0) -> Any:
    """Вызов в daemon-потоке с дедлайном: зависший вызов = провал, а не зависание сюиты."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - пробрасываем в поток теста
            box["exc"] = exc

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(deadline)
    if th.is_alive():
        pytest.fail(f"вызов завис дольше {deadline} с")
    if "exc" in box:
        raise box["exc"]
    return box.get("value")


# ===========================================================================
# Фейковая DLL (форма — как FakeLib в test_sdk_layer.py)
# ===========================================================================


def _target(arg: Any) -> Any:
    """Объект, на который указывает byref()/pointer()/сам объект."""
    if hasattr(arg, "_obj"):
        return arg._obj
    if hasattr(arg, "contents"):
        return arg.contents
    return arg


class _Fn:
    def __init__(self, lib: ParamLib, name: str) -> None:
        self._lib = lib
        self.argtypes = None
        self.restype = None
        self.errcheck = None
        self._name = name

    def __call__(self, *args: Any) -> int:
        return self._lib._dispatch(self._name, args)


# Имя DLL-функции -> точный размер out-структуры (литералы, посчитаны по заголовку).
_OUT_SIZE = {"GetIntValue": 96, "GetFloatValue": 28, "GetEnumValue": 280, "GetBoolValue": 1}


class ParamLib:
    """Стенд вместо ``MvCodeReaderCtrl.dll``: пишет байты в out-структуру Get*, возвращает ``returns[имя]`` (или 0)."""

    PREFIX = "MV_CODEREADER_"

    def __init__(self, *, returns: dict[str, int] | None = None, fill: dict[str, bytes] | None = None) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.returns = dict(returns or {})
        self.fill = dict(fill or {})

    def __getattr__(self, name: str) -> _Fn:
        if not name.startswith(self.PREFIX):
            raise AttributeError(name)
        fn = _Fn(self, name[len(self.PREFIX) :])
        self.__dict__[name] = fn
        return fn

    def args_of(self, short: str) -> list[tuple[Any, ...]]:
        return [a for n, a in self.calls if n == short]

    def _dispatch(self, short: str, args: tuple[Any, ...]) -> int:
        self.calls.append((short, args))
        rc = self.returns.get(short, 0)
        if rc != 0:
            return rc
        if short in _OUT_SIZE:
            out = _target(args[2])
            assert ctypes.sizeof(out) == _OUT_SIZE[short], (
                f"{short}: out-структура {ctypes.sizeof(out)} Б, а в C она {_OUT_SIZE[short]} Б"
            )
            data = self.fill.get(short, b"")
            ctypes.memmove(ctypes.addressof(out), data, len(data))
        return 0


def _api(lib: ParamLib) -> Any:
    return _sdk("api").MvCodeReaderApi(lib=lib)


# Метод -> (имя DLL-функции, дополнительные аргументы после ключа).
METHODS: list[tuple[str, str, tuple[Any, ...]]] = [
    ("get_int", "GetIntValue", ()),
    ("get_float", "GetFloatValue", ()),
    ("get_enum", "GetEnumValue", ()),
    ("get_bool", "GetBoolValue", ()),
    ("set_int", "SetIntValue", (880,)),
    ("set_float", "SetFloatValue", (880.0,)),
    ("set_enum", "SetEnumValue", (1,)),
    ("set_enum_str", "SetEnumValueByString", ("Off",)),
    ("set_bool", "SetBoolValue", (True,)),
]
_METHOD_IDS = [m[0] for m in METHODS]


# ===========================================================================
# sdk.structures: размеры и раскладка (литералы из заголовка)
# ===========================================================================


@pytest.mark.parametrize(
    ("struct_name", "size"),
    [("INTVALUE_EX", 96), ("FLOATVALUE", 28), ("ENUMVALUE", 280)],
)
def test_param_struct_total_size_matches_c_layout(struct_name: str, size: int) -> None:
    assert ctypes.sizeof(getattr(_sdk("structures"), struct_name)) == size


@pytest.mark.parametrize(
    ("struct_name", "field", "offset"),
    [
        ("INTVALUE_EX", "nCurValue", 0),
        ("INTVALUE_EX", "nMax", 8),
        ("INTVALUE_EX", "nMin", 16),
        ("INTVALUE_EX", "nInc", 24),
        ("INTVALUE_EX", "nReserved", 32),
        ("FLOATVALUE", "fCurValue", 0),
        ("FLOATVALUE", "fMax", 4),  # порядок в C: cur, max, min (не cur, min, max)
        ("FLOATVALUE", "fMin", 8),
        ("FLOATVALUE", "nReserved", 12),
        ("ENUMVALUE", "nCurValue", 0),
        ("ENUMVALUE", "nSupportedNum", 4),
        ("ENUMVALUE", "nSupportValue", 8),
        ("ENUMVALUE", "nReserved", 264),
    ],
)
def test_param_struct_field_offsets_match_c_layout(struct_name: str, field: str, offset: int) -> None:
    assert getattr(getattr(_sdk("structures"), struct_name), field).offset == offset


@pytest.mark.parametrize(
    ("struct_name", "field", "size"),
    [
        ("INTVALUE_EX", "nReserved", 64),
        ("FLOATVALUE", "nReserved", 16),
        ("ENUMVALUE", "nSupportValue", 256),
        ("ENUMVALUE", "nReserved", 16),
    ],
)
def test_param_struct_array_sizes(struct_name: str, field: str, size: int) -> None:
    assert getattr(getattr(_sdk("structures"), struct_name), field).size == size


def test_int_value_ex_fields_are_signed_64bit() -> None:
    """Тип поля проверяем на сыром буфере: знак и ширина."""
    buf = (ctypes.c_ubyte * 96)()
    ctypes.memmove(buf, struct.pack("<qqqq", -1, 2**40, -(2**40), 3), 32)
    v = _sdk("structures").INTVALUE_EX.from_buffer_copy(buf)
    assert (v.nCurValue, v.nMax, v.nMin, v.nInc) == (-1, 2**40, -(2**40), 3)


# ===========================================================================
# sdk.errors: E_GC_RANGE / E_GC_ACCESS
# ===========================================================================


def test_gc_error_constants_have_documented_values() -> None:
    errors = _sdk("errors")
    assert errors.E_GC_RANGE == 0x80020102
    assert errors.E_GC_ACCESS == 0x80020106


def test_gc_error_constants_are_exported_from_sdk_package() -> None:
    sdk = _sdk()
    assert sdk.E_GC_RANGE == 0x80020102
    assert sdk.E_GC_ACCESS == 0x80020106
    assert {"E_GC_RANGE", "E_GC_ACCESS"} <= set(sdk.__all__)


def test_param_structures_are_not_exported_from_sdk_package() -> None:
    """Структуры наружу не экспортируются (как сейчас); зелёный уже на текущем коде — страж от будущего расширения."""
    sdk = _sdk()
    for name in ("INTVALUE_EX", "FLOATVALUE", "ENUMVALUE"):
        assert not hasattr(sdk, name)
        assert name not in sdk.__all__


# ===========================================================================
# sdk.api: аргументы вызова DLL
# ===========================================================================


@pytest.mark.parametrize(("method", "fn", "extra"), METHODS, ids=_METHOD_IDS)
def test_key_is_passed_to_dll_as_plain_bytes(method: str, fn: str, extra: tuple[Any, ...]) -> None:
    lib = ParamLib()
    _run(lambda: getattr(_api(lib), method)(HANDLE, "ExposureTime", *extra))
    (args,) = lib.args_of(fn)
    assert type(args[1]) is bytes  # не str (ушёл бы как UTF-16) и не c_char_p
    assert args[1] == b"ExposureTime"


@pytest.mark.parametrize(("method", "fn", "extra"), METHODS, ids=_METHOD_IDS)
def test_handle_is_passed_to_dll_as_c_void_p(method: str, fn: str, extra: tuple[Any, ...]) -> None:
    lib = ParamLib()
    _run(lambda: getattr(_api(lib), method)(HANDLE, "ExposureTime", *extra))
    (args,) = lib.args_of(fn)
    assert isinstance(args[0], ctypes.c_void_p)
    assert args[0].value == HANDLE


@pytest.mark.parametrize(
    ("method", "fn", "value", "wrapper", "expected"),
    [
        ("set_int", "SetIntValue", 880, ctypes.c_int64, 880),
        ("set_float", "SetFloatValue", 880.0, ctypes.c_float, 880.0),
        ("set_enum", "SetEnumValue", 1, ctypes.c_uint, 1),
        ("set_bool", "SetBoolValue", True, ctypes.c_bool, True),
    ],
)
def test_set_value_is_wrapped_in_exact_ctypes_type(
    method: str, fn: str, value: Any, wrapper: type, expected: Any
) -> None:
    lib = ParamLib()
    _run(lambda: getattr(_api(lib), method)(HANDLE, "ExposureTime", value))
    (args,) = lib.args_of(fn)
    assert isinstance(args[2], wrapper), f"{fn}: значение {type(args[2]).__name__}, ожидалось {wrapper.__name__}"
    assert args[2].value == expected


def test_set_enum_str_passes_value_as_bytes() -> None:
    lib = ParamLib()
    _run(lambda: _api(lib).set_enum_str(HANDLE, "TriggerMode", "Off"))
    (args,) = lib.args_of("SetEnumValueByString")
    assert type(args[1]) is bytes
    assert args[1] == b"TriggerMode"
    assert type(args[2]) is bytes  # str ушёл бы как UTF-16 и дал неверное значение
    assert args[2] == b"Off"


@pytest.mark.parametrize(
    ("method", "fn", "value", "expected"),
    [
        ("set_int", "SetIntValue", 2**40, 2**40),  # шире 32 бит
        ("set_int", "SetIntValue", -7, -7),  # знак
        ("set_enum", "SetEnumValue", 3_000_000_000, 3_000_000_000),  # беззнаковый выше 2**31
        ("set_bool", "SetBoolValue", False, False),
    ],
)
def test_set_value_keeps_width_and_sign(method: str, fn: str, value: Any, expected: Any) -> None:
    lib = ParamLib()
    _run(lambda: getattr(_api(lib), method)(HANDLE, "Gain", value))
    (args,) = lib.args_of(fn)
    assert args[2].value == expected


def test_set_float_has_no_python_side_range_check() -> None:
    """Судья диапазона — SDK (E_GC_RANGE), не Python: значение за любым диапазоном доходит до DLL."""
    lib = ParamLib()
    _run(lambda: _api(lib).set_float(HANDLE, "ExposureTime", 1.0e9))
    assert len(lib.args_of("SetFloatValue")) == 1


@pytest.mark.parametrize(("method", "fn", "extra"), METHODS, ids=_METHOD_IDS)
def test_non_ascii_key_raises_before_dll_call(method: str, fn: str, extra: tuple[Any, ...]) -> None:
    lib = ParamLib()
    with pytest.raises(UnicodeEncodeError):
        _run(lambda: getattr(_api(lib), method)(HANDLE, "Экспозиция", *extra))
    assert lib.calls == []


# ===========================================================================
# sdk.api: чтение (фейк пишет по байтовым смещениям)
# ===========================================================================


def test_get_float_reads_cur_max_min_in_c_order() -> None:
    lib = ParamLib(fill={"GetFloatValue": struct.pack("<fff", 880.0, 10000.0, 15.0)})  # fCurValue@0, fMax@4, fMin@8
    assert _run(lambda: _api(lib).get_float(HANDLE, "ExposureTime")) == {"cur": 880.0, "min": 15.0, "max": 10000.0}


def test_get_int_reads_four_int64_fields() -> None:
    lib = ParamLib(fill={"GetIntValue": struct.pack("<qqqq", 880, 10000, 15, 5)})  # nCurValue@0 nMax@8 nMin@16 nInc@24
    assert _run(lambda: _api(lib).get_int(HANDLE, "ExposureTime")) == {"cur": 880, "min": 15, "max": 10000, "inc": 5}


def test_get_int_keeps_sign_and_width_of_int64() -> None:
    lib = ParamLib(fill={"GetIntValue": struct.pack("<qqqq", -3, 2**40, -(2**40), 7)})
    assert _run(lambda: _api(lib).get_int(HANDLE, "Gain")) == {"cur": -3, "min": -(2**40), "max": 2**40, "inc": 7}


def test_get_enum_reads_cur_and_supported_list() -> None:
    data = struct.pack("<II", 1, 3) + struct.pack("<3I", 0, 1, 7)  # nCurValue@0 nSupportedNum@4 nSupportValue@8
    lib = ParamLib(fill={"GetEnumValue": data})
    assert _run(lambda: _api(lib).get_enum(HANDLE, "TriggerMode")) == {"cur": 1, "supported": [0, 1, 7]}


def test_get_enum_supported_is_clamped_to_64_entries() -> None:
    data = struct.pack("<II", 1, 70) + struct.pack("<64I", *range(100, 164))  # nSupportedNum > 64
    lib = ParamLib(fill={"GetEnumValue": data})
    result = _run(lambda: _api(lib).get_enum(HANDLE, "TriggerMode"))
    assert len(result["supported"]) == 64
    assert result["supported"] == list(range(100, 164))


def test_get_enum_supported_is_empty_when_count_is_zero() -> None:
    lib = ParamLib(fill={"GetEnumValue": struct.pack("<II", 2, 0) + struct.pack("<2I", 9, 9)})
    assert _run(lambda: _api(lib).get_enum(HANDLE, "TriggerMode")) == {"cur": 2, "supported": []}


@pytest.mark.parametrize(("raw", "expected"), [(b"\x01", True), (b"\x00", False)])
def test_get_bool_returns_python_bool(raw: bytes, expected: bool) -> None:
    lib = ParamLib(fill={"GetBoolValue": raw})
    result = _run(lambda: _api(lib).get_bool(HANDLE, "QualityEnable"))
    assert result is expected


# ===========================================================================
# sdk.api: ошибки
# ===========================================================================


@pytest.mark.parametrize("rc", [E_GC_ACCESS, E_GC_ACCESS_SIGNED])
def test_set_float_error_names_call_key_and_hex_code(rc: int) -> None:
    errors = _sdk("errors")
    lib = ParamLib(returns={"SetFloatValue": rc})
    with pytest.raises(errors.SdkError) as info:
        _run(lambda: _api(lib).set_float(HANDLE, "ExposureTime", 880.0))
    assert info.value.code == 0x80020106
    text = str(info.value)  # ключ — в str(), а не в add_note (add_note str() не меняет)
    assert "SetFloatValue" in text
    assert "ExposureTime" in text
    assert "0x80020106" in text


@pytest.mark.parametrize("rc", [E_GC_ACCESS, E_GC_ACCESS_SIGNED])
@pytest.mark.parametrize(("method", "fn", "extra"), METHODS, ids=_METHOD_IDS)
def test_every_method_raises_sdk_error_with_code_and_key(method: str, fn: str, extra: tuple[Any, ...], rc: int) -> None:
    errors = _sdk("errors")
    lib = ParamLib(returns={fn: rc})
    with pytest.raises(errors.SdkError) as info:
        _run(lambda: getattr(_api(lib), method)(HANDLE, "Gain", *extra))
    assert info.value.code == 0x80020106
    text = str(info.value)
    assert fn in text
    assert "Gain" in text
    assert "0x80020106" in text


@pytest.mark.parametrize(("method", "fn", "extra"), METHODS, ids=_METHOD_IDS)
def test_error_where_carries_call_name_and_key(method: str, fn: str, extra: tuple[Any, ...]) -> None:
    errors = _sdk("errors")
    lib = ParamLib(returns={fn: E_GC_RANGE})
    with pytest.raises(errors.SdkError) as info:
        _run(lambda: getattr(_api(lib), method)(HANDLE, "Gain", *extra))
    assert info.value.code == 0x80020102
    assert info.value.where == f"MV_CODEREADER_{fn}[Gain]"


@pytest.mark.parametrize("rc", [E_NODATA, -2147352570])
@pytest.mark.parametrize(("method", "fn", "extra"), METHODS, ids=_METHOD_IDS)
def test_nodata_is_an_error_not_none(method: str, fn: str, extra: tuple[Any, ...], rc: int) -> None:
    errors = _sdk("errors")
    lib = ParamLib(returns={fn: rc})
    with pytest.raises(errors.SdkError) as info:
        _run(lambda: getattr(_api(lib), method)(HANDLE, "ExposureTime", *extra))
    assert info.value.code == 0x80020006


# ===========================================================================
# Регрессия: импорт sdk без IDMVS не грузит DLL (уже покрыта test_sdk_layer.py; здесь — после новых экспортов)
# ===========================================================================

_PROBE_CODE = (
    "import ctypes\n"
    "attempts = []\n"
    "_orig = getattr(ctypes, 'WinDLL', None)\n"
    "def _spy(*a, **k):\n"
    "    attempts.append(str(a[0] if a else k))\n"
    "    return _orig(*a, **k)\n"
    "if _orig is not None:\n"
    "    ctypes.WinDLL = _spy\n"
    "import Services.code_reader.sdk\n"
    "mvcr = [a for a in attempts if 'MvCodeReader' in a]\n"
    "print('MVCR_LOAD_ATTEMPTS=' + repr(mvcr))\n"
)


def test_import_sdk_does_not_load_dll(tmp_path: Path) -> None:
    empty = tmp_path / "empty_sdk_dir"
    empty.mkdir()
    env = dict(os.environ)
    env["MVCR_SDK_DIR"] = str(empty)
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE_CODE],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "MVCR_LOAD_ATTEMPTS=[]" in proc.stdout


# ===========================================================================
# Зонд mvcr_probe: фейковый MvCodeReaderApi через main(argv, api=fake)
# ===========================================================================

DEFAULT_NODES: dict[str, dict[str, Any]] = {
    "ExposureTime": {"float": 880.0},
    "Gain": {"float": 1.0},
    "TriggerMode": {"enum": 1},
    "TriggerSource": {"enum": 0},
    "QualityEnable": {"bool": True},
    "LightBrightness": {"int": 50},
    "RunningMode": {"enum": 0},
}
ENUM_NAMES = {"Off": 0, "On": 1, "Normal": 0, "Raw": 1, "Test": 2}


class FakeApi:
    """Двойник ``MvCodeReaderApi``: те же методы, журнал вызовов, узлы с состоянием.

    Узел отвечает только на getter своего типа; остальные бросают ``SdkError(E_GC_ACCESS)``.
    ``fail[(метод, ключ)]`` — исключение на каждый такой вызов; ``ignore`` — запись молча не меняет состояние.
    """

    def __init__(
        self,
        *,
        nodes: dict[str, dict[str, Any]] | None = None,
        frames: list[Any] | None = None,
        frame_exc: BaseException | None = None,
        fail: dict[tuple[str, str], BaseException] | None = None,
        ignore: set[tuple[str, str]] | None = None,
        on_write: Any = None,
    ) -> None:
        base = DEFAULT_NODES if nodes is None else nodes
        self.nodes = {k: dict(v) for k, v in base.items()}
        self.frames = list(frames or [])
        self.frame_exc = frame_exc
        self.fail = dict(fail or {})
        self.ignore = set(ignore or set())
        self.on_write = on_write
        self.log: list[tuple[str, tuple[Any, ...]]] = []

    # -- introspection -------------------------------------------------------
    @property
    def journal(self) -> list[str]:
        """Имена вызовов без ``enum_devices`` (в спеке журнал начинается с ``open``)."""
        return [n for n, _ in self.log if n != "enum_devices"]

    def set_calls(self) -> list[tuple[str, str, Any]]:
        return [(n, a[1], a[2]) for n, a in self.log if n.startswith("set_")]

    def _rec(self, name: str, *args: Any) -> None:
        self.log.append((name, args))

    # -- API -----------------------------------------------------------------
    def enum_devices(self) -> list[Any]:
        self._rec("enum_devices")
        return [SimpleNamespace(ip="192.168.1.10", model="MV-ID3013PM-06M", serial="DA1234567", info=None)]

    def open(self, entry: Any) -> int:
        self._rec("open", entry)
        return HANDLE

    def start_grabbing(self, h: Any) -> None:
        self._rec("start_grabbing", h)

    def stop_grabbing(self, h: Any) -> None:
        self._rec("stop_grabbing", h)
        exc = self.fail.get(("stop_grabbing", ""))
        if exc is not None:
            raise exc

    def close(self, h: Any) -> None:
        self._rec("close", h)

    def get_frame(self, h: Any, timeout_ms: int = 1000) -> Any:
        self._rec("get_frame", h, timeout_ms)
        time.sleep(0.01)  # настоящий вызов ждёт; без паузы фейк крутит журнал вхолостую
        if self.frame_exc is not None:
            raise self.frame_exc
        return self.frames.pop(0) if self.frames else None

    def _get(self, name: str, typ: str, h: Any, key: str) -> Any:
        self._rec(name, h, key)
        node = self.nodes.get(key, {})
        if typ not in node:
            raise _sdk("errors").SdkError(E_GC_ACCESS, f"MV_CODEREADER_{name}[{key}]")
        v = node[typ]
        if typ == "enum":
            return {"cur": v, "supported": [0, 1, 2]}
        if typ == "int":
            return {"cur": v, "min": 0, "max": 100, "inc": 1}
        if typ == "float":
            return {"cur": v, "min": 0.0, "max": 10000.0}
        return v

    def get_enum(self, h: Any, key: str) -> Any:
        return self._get("get_enum", "enum", h, key)

    def get_int(self, h: Any, key: str) -> Any:
        return self._get("get_int", "int", h, key)

    def get_float(self, h: Any, key: str) -> Any:
        return self._get("get_float", "float", h, key)

    def get_bool(self, h: Any, key: str) -> Any:
        return self._get("get_bool", "bool", h, key)

    def _set(self, name: str, typ: str, h: Any, key: str, value: Any) -> None:
        self._rec(name, h, key, value)
        if self.on_write is not None:
            self.on_write(name)
        exc = self.fail.get((name, key))
        if exc is not None:
            raise exc
        if (name, key) in self.ignore:
            return
        if name == "set_enum_str":
            value = ENUM_NAMES.get(value, 99)
        self.nodes.setdefault(key, {})[typ] = value

    def set_enum(self, h: Any, key: str, value: int) -> None:
        self._set("set_enum", "enum", h, key, value)

    def set_enum_str(self, h: Any, key: str, value: str) -> None:
        self._set("set_enum_str", "enum", h, key, value)

    def set_int(self, h: Any, key: str, value: int) -> None:
        self._set("set_int", "int", h, key, value)

    def set_float(self, h: Any, key: str, value: float) -> None:
        self._set("set_float", "float", h, key, value)

    def set_bool(self, h: Any, key: str, value: bool) -> None:
        self._set("set_bool", "bool", h, key, value)


@pytest.fixture
def probe() -> Any:
    return importlib.import_module("Services.code_reader.tools.mvcr_probe")


def _main(probe_mod: Any, argv: list[str], fake: FakeApi) -> Any:
    """Код выхода: возврат ``main`` либо ``SystemExit.code`` (``parser.error``); иное исключение — наружу."""
    try:
        return _run(lambda: probe_mod.main(argv, api=fake))
    except SystemExit as exc:
        return exc.code


def _out(capsys: pytest.CaptureFixture[str]) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


def _collapse(journal: list[str]) -> list[str]:
    """Подряд идущие ``get_frame`` — в один (их число зависит от темпа цикла)."""
    result: list[str] = []
    for name in journal:
        if name == "get_frame" and result and result[-1] == "get_frame":
            continue
        result.append(name)
    return result


def _code(text: bytes, bar_type: int) -> Any:
    b = _sdk("structures").BCR_INFO_EX2()
    b.chCode = text
    b.nLen = len(text)
    b.nBarType = bar_type
    return b


def _frame(codes: list[Any], n: int) -> Any:
    noread = sum(1 for c in codes if c.nBarType == 1001)
    return _sdk("api").RawFrame(
        image=b"\xff\xd8JPEG\xff\xd9",
        width=640,
        height=480,
        pixel_type=0x80180001,
        trigger_index=n,
        frame_num=n,
        no_read_num=noread,
        codes=tuple(codes),
    )


def _three_frames() -> list[Any]:
    """1 кадр с кодом ``QR``, 1 с NoRead, 1 пустой."""
    return [
        _frame([_code(b"QR", 5)], 1),
        _frame([_code(b"", 1001)], 2),
        _frame([], 3),
    ]


TRIGGER_OFF = ["0.2", "--set", "TriggerMode=enum:Off"]
TWO_NODES = ["0.2", "--set", "TriggerMode=enum:Off", "--set", "RunningMode=enum:Raw"]


# -- сценарий 1: журнал вызовов -----------------------------------------------


def test_scenario1_call_journal_is_exact(probe: Any) -> None:
    fake = FakeApi()
    assert _main(probe, TRIGGER_OFF, fake) == 0
    assert _collapse(fake.journal) == [
        "open",
        "get_enum",
        "set_enum_str",
        "start_grabbing",
        "get_frame",
        "stop_grabbing",
        "set_enum",
        "get_enum",
        "close",
    ]


def test_scenario1_exactly_one_restore_with_original_value(probe: Any) -> None:
    fake = FakeApi()
    _main(probe, TRIGGER_OFF, fake)
    assert [(n, k, v) for n, k, v in fake.set_calls() if n == "set_enum"] == [("set_enum", "TriggerMode", 1)]
    assert [(n, k, v) for n, k, v in fake.set_calls() if n == "set_enum_str"] == [
        ("set_enum_str", "TriggerMode", "Off")
    ]


def test_scenario1_every_session_call_uses_the_opened_handle(probe: Any) -> None:
    fake = FakeApi()
    _main(probe, TRIGGER_OFF, fake)
    session = [(n, a) for n, a in fake.log if n not in ("enum_devices", "open")]
    assert session  # не вакуумно
    assert all(a[0] == HANDLE for _, a in session)
    closes = [a for n, a in fake.log if n == "close"]
    assert closes == [(HANDLE,)]


def test_scenario1_orig_line_is_printed_before_first_write(probe: Any, capsys: pytest.CaptureFixture[str]) -> None:
    seen: list[str] = []
    fake = FakeApi(on_write=lambda name: seen.append(_out(capsys)))
    _main(probe, TRIGGER_OFF, fake)
    assert seen, "запись не произошла"
    assert "ORIG TriggerMode=enum:1" in seen[0]  # ORIG — единственное, что остаётся при жёстком убийстве процесса


def test_scenario1_restore_is_reported_with_node_name(probe: Any, capsys: pytest.CaptureFixture[str]) -> None:
    _main(probe, TRIGGER_OFF, FakeApi())
    assert re.search(r"^RESTORED TriggerMode\b", _out(capsys), re.MULTILINE)


def test_two_nodes_are_written_in_order_before_start_grabbing(probe: Any) -> None:
    fake = FakeApi()
    assert _main(probe, TWO_NODES, fake) == 0
    writes = [(n, k, v) for n, k, v in fake.set_calls() if n == "set_enum_str"]
    assert writes == [("set_enum_str", "TriggerMode", "Off"), ("set_enum_str", "RunningMode", "Raw")]
    j = fake.journal
    assert max(i for i, n in enumerate(j) if n == "set_enum_str") < j.index("start_grabbing")


def test_two_nodes_both_restored_to_originals(probe: Any) -> None:
    fake = FakeApi()
    _main(probe, TWO_NODES, fake)
    restores = sorted((k, v) for n, k, v in fake.set_calls() if n == "set_enum")
    assert restores == [("RunningMode", 0), ("TriggerMode", 1)]


# -- сценарий 2: исключение из цикла приёма выходит наружу ----------------------


def test_scenario2_unexpected_exception_propagates_after_one_restore(probe: Any) -> None:
    fake = FakeApi(frame_exc=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        _run(lambda: probe.main(TRIGGER_OFF, api=fake))
    j = fake.journal
    assert [(n, k, v) for n, k, v in fake.set_calls() if n == "set_enum"] == [("set_enum", "TriggerMode", 1)]
    assert j.index("stop_grabbing") < j.index("set_enum") < j.index("close")


def test_scenario2_sdk_error_in_receive_loop_is_swallowed_and_loop_goes_on(probe: Any) -> None:
    """Парная проверка к сценарию 2: SdkError цикл ловит (в отличие от RuntimeError) — вакуумность 'boom' снимается."""
    errors = _sdk("errors")
    fake = FakeApi(frame_exc=errors.SdkError(0x80020203, "MV_CODEREADER_GetOneFrameTimeoutEx2"))
    assert _main(probe, TRIGGER_OFF, fake) == 0
    assert fake.journal.count("get_frame") >= 2


# -- сценарий 3: отказ записи второго узла ------------------------------------


def test_scenario3_second_write_fails_no_grabbing_first_node_restored_exit_1(probe: Any) -> None:
    errors = _sdk("errors")
    fake = FakeApi(
        fail={("set_enum_str", "RunningMode"): errors.SdkError(E_GC_RANGE, "MV_CODEREADER_SetEnumValueByString")}
    )
    rc = _main(probe, TWO_NODES, fake)
    assert rc == 1
    assert "start_grabbing" not in fake.journal
    assert "get_frame" not in fake.journal
    # парный страж: запись первого узла была, значит тест не вакуумен
    assert ("set_enum_str", "TriggerMode", "Off") in fake.set_calls()
    assert ("set_enum", "TriggerMode", 1) in fake.set_calls()
    assert "close" in fake.journal


# -- сценарий 4: отказ восстановления не пропускает остальное -------------------


def _scenario4_fake() -> FakeApi:
    errors = _sdk("errors")
    return FakeApi(fail={("set_enum", "TriggerMode"): errors.SdkError(E_GC_RANGE, "MV_CODEREADER_SetEnumValue")})


def test_scenario4_failed_restore_still_restores_second_node_and_closes(probe: Any) -> None:
    fake = _scenario4_fake()
    rc = _main(probe, TWO_NODES, fake)
    assert rc != 0
    restores = [(k, v) for n, k, v in fake.set_calls() if n == "set_enum"]
    assert ("RunningMode", 0) in restores  # второй узел восстановлен, несмотря на отказ первого
    assert fake.journal[-1] == "close"
    assert fake.journal.count("close") == 1


def test_scenario4_failed_restore_is_not_retried_and_exit_code_is_3(
    probe: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = _scenario4_fake()
    rc = _main(probe, TWO_NODES, fake)
    assert rc == 3
    assert [k for n, k, _ in fake.set_calls() if n == "set_enum" and k == "TriggerMode"] == [
        "TriggerMode"
    ]  # без повторов
    assert re.search(r"RESTORE FAILED TriggerMode orig=1 0x80020102", _out(capsys))


def test_restore_mismatch_is_reported_when_readback_differs(probe: Any, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeApi(ignore={("set_enum", "TriggerMode")})  # запись оригинала молча не меняет узел -> чтение даст 0, не 1
    _main(probe, TRIGGER_OFF, fake)
    text = _out(capsys)
    assert "RESTORE MISMATCH" in text
    assert not re.search(r"^RESTORED TriggerMode\b", text, re.MULTILINE)
    assert "close" in fake.journal


def test_stop_grabbing_error_is_printed_and_does_not_skip_restore_or_close(
    probe: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    errors = _sdk("errors")
    fake = FakeApi(fail={("stop_grabbing", ""): errors.SdkError(0x80020203, "MV_CODEREADER_StopGrabbing")})
    _main(probe, TRIGGER_OFF, fake)
    assert "0x80020203" in _out(capsys)
    assert [(k, v) for n, k, v in fake.set_calls() if n == "set_enum"] == [("TriggerMode", 1)]
    assert fake.journal[-1] == "close"


def test_unreadable_node_exits_before_first_write_and_grabbing(probe: Any) -> None:
    fake = FakeApi()  # ExposureTime отвечает только как float: get_int бросает SdkError
    rc = _main(probe, ["0.2", "--set", "ExposureTime=int:5"], fake)
    assert rc != 0
    assert "start_grabbing" not in fake.journal
    assert not [n for n in fake.journal if n.startswith("set_")]
    assert "get_int" in fake.journal  # читался именно getter заданного ТИПа
    assert "close" in fake.journal


# -- типы и значения --set ---------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "getter", "expected"),
    [
        ("TriggerMode=enum:Off", "get_enum", [("set_enum_str", "Off", "str"), ("set_enum", 1, "int")]),
        ("TriggerMode=enum:0", "get_enum", [("set_enum", 0, "int"), ("set_enum", 1, "int")]),
        ("Gain=float:1.5", "get_float", [("set_float", 1.5, "float"), ("set_float", 1.0, "float")]),
        ("LightBrightness=int:5", "get_int", [("set_int", 5, "int"), ("set_int", 50, "int")]),
        ("QualityEnable=bool:false", "get_bool", [("set_bool", False, "bool"), ("set_bool", True, "bool")]),
        ("QualityEnable=bool:0", "get_bool", [("set_bool", False, "bool"), ("set_bool", True, "bool")]),
    ],
)
def test_set_type_selects_getter_setter_and_restores_original(
    probe: Any, spec: str, getter: str, expected: list[tuple[str, Any, str]]
) -> None:
    fake = FakeApi()
    assert _main(probe, ["0.2", "--set", spec], fake) == 0
    assert fake.journal[:2] == ["open", getter]
    assert [(n, v, type(v).__name__) for n, _, v in fake.set_calls()] == expected


@pytest.mark.parametrize("spec", ["QualityEnable=bool:true", "QualityEnable=bool:1"])
def test_bool_true_spellings(probe: Any, spec: str) -> None:
    fake = FakeApi(nodes={"QualityEnable": {"bool": False}})
    assert _main(probe, ["0.2", "--set", spec], fake) == 0
    assert [(n, v, type(v).__name__) for n, _, v in fake.set_calls()] == [
        ("set_bool", True, "bool"),
        ("set_bool", False, "bool"),
    ]


# -- без --set ничего не пишется (парный страж внутри) -------------------------------


def test_without_set_there_is_no_set_call_and_with_set_there_is(probe: Any) -> None:
    plain = FakeApi()
    assert _main(probe, ["0.2"], plain) == 0
    assert {"open", "start_grabbing", "get_frame", "stop_grabbing", "close"} <= set(plain.journal)  # сессия шла
    assert not [n for n in plain.journal if n.startswith("set_")]
    withset = FakeApi()
    _main(probe, TRIGGER_OFF, withset)
    assert [n for n in withset.journal if n.startswith("set_")]  # тот же стенд с --set пишет: тест не вакуумен


# -- итог -----------------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [TRIGGER_OFF, ["0.2"]], ids=["with_set", "without_set"])
def test_summary_line_counts_frames_codes_read_and_noread(
    probe: Any, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    fake = FakeApi(frames=_three_frames())
    assert _main(probe, argv, fake) == 0
    out_lines = capsys.readouterr().out.splitlines()
    summary = [ln for ln in out_lines if ln.startswith("ИТОГ кадров:")]
    assert len(summary) == 1
    assert summary[0].startswith("ИТОГ кадров: 3 с_кодом: 2 read: 1 noread: 1 fps:")


def test_summary_read_and_noread_are_not_interchangeable(probe: Any, capsys: pytest.CaptureFixture[str]) -> None:
    """Несимметричные данные: 3 прочитанных кода и 1 NoRead (в `_three_frames` по одному — read/noread не различить).

    Находка матрицы инъекций P4 (2026-10-16): подмена `noread` на «не NoRead» оставляла 159 тестов зелёными.
    """
    frames = [
        _frame([_code(b"QR-A", 5), _code(b"QR-B", 5), _code(b"", 1001)], 1),
        _frame([_code(b"QR-C", 5)], 2),
    ]
    fake = FakeApi(frames=frames)
    _main(probe, TRIGGER_OFF, fake)
    summary = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("ИТОГ кадров:")]
    assert len(summary) == 1
    assert summary[0].startswith("ИТОГ кадров: 2 с_кодом: 2 read: 3 noread: 1 fps:"), summary[0]


def test_summary_fps_is_frames_divided_by_seconds(probe: Any, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeApi(frames=_three_frames())
    _main(probe, TRIGGER_OFF, fake)
    summary = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("ИТОГ кадров:")]
    assert summary[0].endswith("fps: 15.0")  # 3 кадра / 0.2 с


# -- --params ----------------------------------------------------------------------------------

_SEVEN = ["ExposureTime", "Gain", "TriggerMode", "TriggerSource", "QualityEnable", "LightBrightness", "RunningMode"]


def test_params_calls_all_four_getters_for_each_of_seven_nodes(probe: Any) -> None:
    fake = FakeApi()
    assert _main(probe, ["--params"], fake) == 0
    got = sorted((n, a[1]) for n, a in fake.log if n.startswith("get_") and n != "get_frame")
    want = sorted((g, node) for node in _SEVEN for g in ("get_enum", "get_int", "get_float", "get_bool"))
    assert got == want
    assert fake.journal[0] == "open"
    assert fake.journal[-1] == "close"


def test_params_writes_nothing_and_does_not_grab(probe: Any) -> None:
    fake = FakeApi()
    _main(probe, ["--params"], fake)
    assert fake.journal  # прогон был
    assert not [n for n in fake.journal if n.startswith("set_")]
    assert "start_grabbing" not in fake.journal


def test_params_prints_one_node_line_per_node_with_all_four_getters(
    probe: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    _main(probe, ["--params"], FakeApi())
    text = _out(capsys)
    for node in _SEVEN:
        lines = [ln for ln in text.splitlines() if ln.startswith(f"NODE {node} ")]
        assert len(lines) == 1, f"{node}: строк NODE {len(lines)}"
        for getter in ("enum=", "int=", "float=", "bool="):
            assert re.search(rf"\b{getter}", lines[0]), f"{node}: нет {getter} в {lines[0]!r}"
        # порядок как в DESIGN: enum, int, float, bool
        pos = [lines[0].index(g) for g in ("enum=", " int=", " float=", " bool=")]
        assert pos == sorted(pos)


def test_params_line_shows_ok_and_error_code_per_getter(probe: Any, capsys: pytest.CaptureFixture[str]) -> None:
    _main(probe, ["--params"], FakeApi())
    text = _out(capsys)
    trig = next(ln for ln in text.splitlines() if ln.startswith("NODE TriggerMode "))
    assert "enum=OK(cur=1)" in trig
    assert re.search(r"\bint=0x80020106", trig)
    assert re.search(r"\bfloat=0x80020106", trig)
    assert re.search(r"\bbool=0x80020106", trig)
    expo = next(ln for ln in text.splitlines() if ln.startswith("NODE ExposureTime "))
    assert re.search(r"\bfloat=OK", expo)
    assert re.search(r"\benum=0x80020106", expo)


# -- разбор аргументов: отказ с кодом 2, API не тронут ----------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["--set", "TriggerMode=1"],  # без ТИП:
        ["--set", "X=1"],
        ["--set", "TriggerMode=enum:-1"],  # отрицательный enum
        ["--set", "Gain=float:nan"],
        ["--set", "Gain=float:inf"],
        ["--set", "Gain=float:-inf"],
        ["--params", "--set", "TriggerMode=enum:Off"],
        ["31", "--set", "TriggerMode=enum:Off"],
        ["0", "--set", "TriggerMode=enum:Off"],
        ["-1", "--set", "TriggerMode=enum:Off"],
    ],
    ids=[
        "no_type_enum",
        "no_type_X",
        "negative_enum",
        "float_nan",
        "float_inf",
        "float_minus_inf",
        "params_with_set",
        "seconds_31",
        "seconds_0",
        "seconds_negative",
    ],
)
def test_bad_arguments_exit_2_and_fake_api_is_untouched(
    probe: Any, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    fake = FakeApi()
    assert _main(probe, argv, fake) == 2
    assert fake.log == []
    assert _out(capsys)  # argparse объяснил отказ


def test_valid_arguments_do_touch_the_fake_api(probe: Any) -> None:
    """Парный страж к отказам: корректная команда реально доходит до API (иначе 'API не тронут' вакуумно)."""
    fake = FakeApi()
    assert _main(probe, TRIGGER_OFF, fake) == 0
    assert fake.log
