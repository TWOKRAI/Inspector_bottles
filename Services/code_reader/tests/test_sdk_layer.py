# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты Task 6.1 (``Services.code_reader.sdk``): RED до реализации.

Источник истины — контракт Task 6.1 в ``plans/code-reader-sdk.md`` и заголовок
``MvCodeReaderParams.h`` (V1.5.3). Реализацию тесты не видели.

Ожидаемые значения — ЛИТЕРАЛЫ. Смещения и размеры посчитаны руками по правилам
выравнивания MSVC x64 (``bool`` = 1 байт, указатель = 8, enum = 4):

    CODE_INFO          = 50 полей по 4 байта                        -> 200
    BCR_INFO_EX2       = 4 + 4096 + 4 + 4 + 32 + 200 = 4340 (nAngle)
                         ... bIsGetQuality 4360 (1 байт), 3 байта пад, nIDRScore 4364
                         ... nReserved[57] с 4400 (228 байт)          -> 4628
    RESULT_BCR_EX2     = 4 + 300 * 4628 (=1388400) = 1388404 (nNoReadNum)
                         + 2 + 2 + 7*4                                -> 1388436
    IMAGE_OUT_INFO_EX2 : bIsGetCode 36 (1 байт) -> pstCodeListEx выровнен до 40
                         ... nImageCost 64 -> union 72 (align 8) ... nRes 90
                         -> pad до 96 (UnparsedAgvInfo) ... nReserved[23] 104..196
                         -> размер округлён до 8                      -> 200
    DEVICE_INFO        : bSelectDevice 20 -> nWebHostIp 24 -> SpecialInfo 32,
                         union = max(GigE 216, USB3 540) = 540        -> 572
    DEVICE_INFO_LIST   = 8 (nDeviceNum + пад) + 256 * 8               -> 2056

ПРЕДПОЛОЖЕНИЯ, которых в контракте нет (одно место правки — блок «HOOKS» ниже):
  * имена полей ctypes-структур = именам из C-заголовка (``nLen``, ``pt`` ...);
  * ``sdk.loader.IDMVS_PLUGIN_DIR`` — модульная константа каталога плагина IDMVS
    (решение лида: тесты её подменяют);
  * ``RawFrame`` плоский: ``image`` (bytes), ``width``, ``height``, ``pixel_type``,
    ``trigger_index``, ``frame_num``, ``no_read_num``, ``codes`` (копии
    ``BCR_INFO_EX2``, по одной на ``nCodeNum``);
  * ``DeviceEntry.ip`` — точечная запись из ``nCurrentIp`` (старший байт первым);
  * ``enum_devices`` опрашивает GigE-слой (``nTLayerType == 1``).
"""

from __future__ import annotations

import ctypes
import importlib
import os
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DLL_NAME = "MvCodeReaderCtrl.dll"

# Литералы кодов возврата в двух представлениях: без знака и как их вернёт
# ctypes при restype = c_int (реальная DLL возвращает int со знаком).
E_NODATA = 0x80020006
E_NODATA_SIGNED = -2147352570
E_ACCESS_DENIED = 0x80020203
E_ACCESS_DENIED_SIGNED = -2147352061
E_PRECONDITION = 0x80020007  # сосед NODATA: None должен быть ровно на 0x80020006


# ---------------------------------------------------------------------------
# HOOKS: всё, что тест угадывает про форму результата, собрано здесь.
# ---------------------------------------------------------------------------


def _sdk(name: str) -> Any:
    """Импорт внутри теста, чтобы RED был ModuleNotFoundError на КАЖДОМ тесте."""
    return importlib.import_module(f"Services.code_reader.sdk.{name}")


def _frame_view(raw: Any) -> dict[str, Any]:
    return {
        "image": raw.image,
        "width": raw.width,
        "height": raw.height,
        "pixel_type": raw.pixel_type,
        "trigger_index": raw.trigger_index,
        "frame_num": raw.frame_num,
        "no_read_num": raw.no_read_num,
        "n_codes": len(raw.codes),
    }


def _code_view(entry: Any) -> dict[str, Any]:
    n = entry.nLen
    return {
        "text": bytes(entry.chCode)[:n],
        "n_len": n,
        "bar_type": entry.nBarType,
        "pts": tuple((entry.pt[i].x, entry.pt[i].y) for i in range(4)),
        "overall": entry.stCodeQuality.nOverQuality,
        "angle": entry.nAngle,
        "ppm": entry.sPPM,
        "algo": entry.sAlgoCost,
        "has_quality": bool(entry.bIsGetQuality),
        "idr": entry.nIDRScore,
    }


# ---------------------------------------------------------------------------
# Общие помощники
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MVCR_SDK_DIR", raising=False)


def _isolated_loader(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """loader с подменённым каталогом IDMVS (на этой машине настоящий IDMVS есть)."""
    loader = _sdk("loader")
    monkeypatch.setattr(loader, "IDMVS_PLUGIN_DIR", tmp_path / "no_idmvs_here", raising=True)
    return loader


def _make_sdk_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / DLL_NAME).write_bytes(b"")
    return path


def _same(a: Any, b: Any) -> bool:
    def norm(x: Any) -> str:
        return os.path.normcase(os.path.normpath(str(x)))

    return norm(a) == norm(b)


def _run(fn: Any, *args: Any, deadline: float = 10.0) -> Any:
    """Вызов в daemon-потоке с дедлайном: зависший вызов = провал, а не зависание сюиты."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001 - пробрасываем в поток теста
            box["exc"] = exc

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(deadline)
    if th.is_alive():
        pytest.fail(f"вызов {getattr(fn, '__name__', fn)} завис дольше {deadline} с")
    if "exc" in box:
        raise box["exc"]
    return box.get("value")


def _hv(x: Any) -> int:
    """Значение handle/числа независимо от обёртки (int, c_void_p, c_uint...)."""
    return int(getattr(x, "value", x) or 0)


def _target(arg: Any) -> Any:
    """Объект, на который указывает byref()/pointer()/сам объект."""
    if hasattr(arg, "_obj"):
        return arg._obj
    if hasattr(arg, "contents"):
        return arg.contents
    return arg


def _address_of(x: Any) -> int:
    if isinstance(x, int):
        return x
    if hasattr(x, "_obj"):
        return ctypes.addressof(x._obj)
    if isinstance(x, ctypes.c_void_p):
        return x.value or 0
    if hasattr(x, "contents"):
        return ctypes.cast(x, ctypes.c_void_p).value or 0
    return ctypes.addressof(x)


def _poke(addr: int, fmt: str, *vals: Any) -> None:
    import struct

    data = struct.pack("<" + fmt, *vals)
    ctypes.memmove(addr, data, len(data))


def _poke_ptr(addr: int, value: int) -> None:
    ctypes.c_void_p.from_address(addr).value = value


# ---------------------------------------------------------------------------
# Фейковая DLL: пишет в out-структуры по ЛИТЕРАЛЬНЫМ C-смещениям, а не через
# тестируемые ctypes-структуры (иначе неверная раскладка согласовалась бы сама с собой).
# ---------------------------------------------------------------------------

_RESULT_SIZE = 1388436
_ENTRY = 4628


class _Fn:
    def __init__(self, lib: FakeLib, name: str) -> None:
        self._lib = lib
        self._name = name
        self.argtypes = None
        self.restype = None
        self.errcheck = None

    def __call__(self, *args: Any) -> int:
        return self._lib._dispatch(self._name, args)


class FakeLib:
    """Стенд вместо MvCodeReaderCtrl.dll; любые MV_CODEREADER_* по умолчанию возвращают 0."""

    PREFIX = "MV_CODEREADER_"

    def __init__(
        self,
        *,
        returns: dict[str, int] | None = None,
        frames: list[dict[str, Any]] | None = None,
        devices: list[dict[str, Any]] | None = None,
        handle: int = 0x5150,
    ) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.returns = dict(returns or {})
        self.frames = deque(frames or [])
        self.devices = list(devices or [])
        self.handle = handle
        # Как в SDK: один буфер под кадр и один под список кодов, переиспользуются.
        self.image_buf = ctypes.create_string_buffer(65536)
        self.result_buf = (ctypes.c_ubyte * _RESULT_SIZE)()
        self.dev_bufs = [(ctypes.c_ubyte * 572)() for _ in self.devices]

    def __getattr__(self, name: str) -> _Fn:
        if not name.startswith(self.PREFIX):
            raise AttributeError(name)
        fn = _Fn(self, name[len(self.PREFIX) :])
        self.__dict__[name] = fn
        return fn

    # -- introspection ------------------------------------------------------
    def names(self) -> list[str]:
        return [n for n, _ in self.calls]

    def args_of(self, short: str) -> list[tuple[Any, ...]]:
        return [a for n, a in self.calls if n == short]

    # -- dispatch -----------------------------------------------------------
    def _dispatch(self, short: str, args: tuple[Any, ...]) -> int:
        self.calls.append((short, args))
        rc = self.returns.get(short, 0)
        if rc not in (0,):
            return rc
        if short == "EnumDevices":
            self._fill_devices(_target(args[0]))
        elif short == "CreateHandle":
            _poke_ptr(ctypes.addressof(_target(args[0])), self.handle)
        elif short == "GetOneFrameTimeoutEx2":
            self._fill_frame(_target(args[1]), _target(args[2]))
        return 0

    def _fill_devices(self, lst: Any) -> None:
        assert ctypes.sizeof(lst) >= 2056, "DEVICE_INFO_LIST меньше 2056 байт: раскладка неверна"
        base = ctypes.addressof(lst)
        _poke(base, "I", len(self.devices))  # nDeviceNum @0
        for i, dev in enumerate(self.devices):
            buf = self.dev_bufs[i]
            addr = ctypes.addressof(buf)
            _poke(addr + 12, "I", 1)  # nTLayerType
            _poke(addr + 40, "I", dev["ip_int"])  # SpecialInfo(32)+nCurrentIp(8)
            _poke(addr + 84, "32s", dev["model"].encode())  # 32+chModelName(52)
            _poke(addr + 196, "16s", dev["serial"].encode())  # 32+chSerialNumber(164)
            _poke_ptr(base + 8 + 8 * i, addr)  # pDeviceInfo[i] @8

    def _fill_frame(self, pdata: Any, info: Any) -> None:
        assert ctypes.sizeof(info) >= 200, "IMAGE_OUT_INFO_EX2 меньше 200 байт: раскладка неверна"
        assert ctypes.sizeof(pdata) >= 8, "pData не помещает указатель"
        if not self.frames:
            raise AssertionError("у фейка кончились кадры")
        fr = self.frames.popleft()
        image = fr["image"]
        ctypes.memset(self.image_buf, 0, len(self.image_buf))
        ctypes.memmove(self.image_buf, image, len(image))
        _poke_ptr(ctypes.addressof(pdata), ctypes.addressof(self.image_buf))

        ia = ctypes.addressof(info)
        _poke(ia + 0, "H", fr["width"])
        _poke(ia + 2, "H", fr["height"])
        _poke(ia + 4, "I", fr["pixel_type"])
        _poke(ia + 8, "I", fr["trigger_index"])
        _poke(ia + 12, "I", fr["frame_num"])
        _poke(ia + 16, "I", len(image))
        _poke(ia + 36, "B", 1 if fr["codes"] else 0)  # bIsGetCode
        if fr.get("null_code_list"):
            _poke_ptr(ia + 72, 0)
            return
        ctypes.memset(self.result_buf, 0, _RESULT_SIZE)
        ra = ctypes.addressof(self.result_buf)
        _poke(ra, "I", len(fr["codes"]))  # nCodeNum
        for i, c in enumerate(fr["codes"]):
            e = ra + 4 + i * _ENTRY
            _poke(e + 0, "I", c.get("id", i + 1))
            _poke(e + 4, "%ds" % len(c["text"]), c["text"])
            _poke(e + 4100, "I", c.get("n_len", len(c["text"])))
            _poke(e + 4104, "I", c["bar_type"])
            for k, (x, y) in enumerate(c["pts"]):
                _poke(e + 4108 + 8 * k, "ii", x, y)
            _poke(e + 4140, "i", c.get("overall", 0))  # stCodeQuality.nOverQuality
            _poke(e + 4340, "i", c.get("angle", 0))
            _poke(e + 4354, "H", c.get("ppm", 0))
            _poke(e + 4356, "H", c.get("algo", 0))
            _poke(e + 4360, "B", 1 if c.get("has_quality") else 0)
            _poke(e + 4364, "I", c.get("idr", 0))
        _poke(ra + 1388404, "H", fr.get("no_read_num", 0))  # nNoReadNum
        _poke_ptr(ia + 72, ra)  # UnparsedBcrList.pstCodeListEx2


PIX_MONO8 = 0x01080001
PIX_JPEG = 0x80180001
QUAD_A = ((10, 20), (110, 20), (110, 120), (10, 120))
QUAD_B = ((-5, 2), (3, 4), (5, 6), (7, 8))


def _frame_a() -> dict[str, Any]:
    """Кадр из двух кодов: читаемый и NoRead (nLen = 0, bar_type = 1001)."""
    return {
        "image": bytes(range(32)),
        "width": 640,
        "height": 480,
        "pixel_type": PIX_MONO8,
        "trigger_index": 7,
        "frame_num": 3,
        "no_read_num": 1,
        "codes": [
            {
                "text": b"QR-30MM",
                "bar_type": 5,
                "pts": QUAD_A,
                "overall": 3,
                "angle": 900,
                "ppm": 1234,
                "algo": 12,
                "has_quality": True,
                "idr": 77,
            },
            {"text": b"", "n_len": 0, "bar_type": 1001, "pts": QUAD_B, "angle": -1},
        ],
    }


def _api(lib: FakeLib) -> Any:
    return _sdk("api").MvCodeReaderApi(lib=lib)


# ===========================================================================
# sdk.errors
# ===========================================================================


def test_error_constants_have_documented_values() -> None:
    errors = _sdk("errors")
    assert errors.MV_OK == 0
    assert errors.E_NODATA == 0x80020006
    assert errors.E_ACCESS_DENIED == 0x80020203


def test_sdk_error_str_names_the_call_and_the_hex_code() -> None:
    errors = _sdk("errors")
    text = str(errors.SdkError(0x80020203, "MV_CODEREADER_OpenDevice"))
    assert "MV_CODEREADER_OpenDevice" in text
    assert "0x80020203" in text


@pytest.mark.parametrize("given", [0x80020203, -2147352061])
def test_sdk_error_code_is_unsigned_32bit(given: int) -> None:
    errors = _sdk("errors")
    err = errors.SdkError(given, "x")
    assert err.code == 0x80020203
    assert err.where == "x"


def test_sdk_error_is_an_exception() -> None:
    errors = _sdk("errors")
    assert issubclass(errors.SdkError, Exception)
    assert issubclass(errors.SdkNotFoundError, Exception)


# ===========================================================================
# sdk.loader
# ===========================================================================


def test_find_sdk_dir_order_explicit_env_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    loader = _sdk("loader")
    explicit = _make_sdk_dir(tmp_path / "explicit")
    env_dir = _make_sdk_dir(tmp_path / "env")
    default = _make_sdk_dir(tmp_path / "default")
    monkeypatch.setattr(loader, "IDMVS_PLUGIN_DIR", default, raising=True)
    monkeypatch.setenv("MVCR_SDK_DIR", str(env_dir))

    assert _same(loader.find_sdk_dir(explicit), explicit)
    assert _same(loader.find_sdk_dir(), env_dir)
    monkeypatch.delenv("MVCR_SDK_DIR")
    assert _same(loader.find_sdk_dir(), default)


def test_find_sdk_dir_skips_dir_without_dll(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    loader = _isolated_loader(monkeypatch, tmp_path)
    empty = tmp_path / "explicit_no_dll"
    empty.mkdir()
    env_dir = _make_sdk_dir(tmp_path / "env")
    monkeypatch.setenv("MVCR_SDK_DIR", str(env_dir))
    assert _same(loader.find_sdk_dir(empty), env_dir)


def test_find_sdk_dir_skips_nonexistent_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    loader = _isolated_loader(monkeypatch, tmp_path)
    env_dir = _make_sdk_dir(tmp_path / "env")
    monkeypatch.setenv("MVCR_SDK_DIR", str(env_dir))
    assert _same(loader.find_sdk_dir(tmp_path / "does_not_exist"), env_dir)


def test_find_sdk_dir_env_dir_without_dll_falls_through_to_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    loader = _sdk("loader")
    env_empty = tmp_path / "env_no_dll"
    env_empty.mkdir()
    default = _make_sdk_dir(tmp_path / "default")
    monkeypatch.setattr(loader, "IDMVS_PLUGIN_DIR", default, raising=True)
    monkeypatch.setenv("MVCR_SDK_DIR", str(env_empty))
    assert _same(loader.find_sdk_dir(), default)


def test_find_sdk_dir_returns_none_when_nothing_has_the_dll(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    loader = _isolated_loader(monkeypatch, tmp_path)
    (tmp_path / "e").mkdir()
    monkeypatch.setenv("MVCR_SDK_DIR", str(tmp_path / "e"))
    assert loader.find_sdk_dir(tmp_path / "missing") is None


@pytest.mark.parametrize("as_type", [str, Path])
def test_find_sdk_dir_accepts_str_and_path_and_returns_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, as_type: type
) -> None:
    loader = _isolated_loader(monkeypatch, tmp_path)
    explicit = _make_sdk_dir(tmp_path / "explicit")
    found = loader.find_sdk_dir(as_type(explicit))
    assert isinstance(found, Path)
    assert _same(found, explicit)


def test_find_sdk_dir_does_not_load_anything(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    loader = _isolated_loader(monkeypatch, tmp_path)
    explicit = _make_sdk_dir(tmp_path / "explicit")
    touched: list[str] = []

    def boom(*a: Any, **k: Any) -> Any:
        touched.append("called")
        raise AssertionError("find_sdk_dir не должен грузить DLL / трогать пути поиска DLL")

    monkeypatch.setattr(ctypes, "WinDLL", boom, raising=False)
    monkeypatch.setattr(ctypes, "CDLL", boom, raising=False)
    monkeypatch.setattr(os, "add_dll_directory", boom, raising=False)
    assert _same(loader.find_sdk_dir(explicit), explicit)
    assert touched == []


def test_load_library_not_found_lists_every_checked_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    loader = _sdk("loader")
    errors = _sdk("errors")
    explicit = tmp_path / "explicit_missing"  # не существует
    env_dir = tmp_path / "env_no_dll"  # существует, DLL нет
    env_dir.mkdir()
    default = tmp_path / "idmvs_missing"  # не существует
    monkeypatch.setattr(loader, "IDMVS_PLUGIN_DIR", default, raising=True)
    monkeypatch.setenv("MVCR_SDK_DIR", str(env_dir))

    with pytest.raises(errors.SdkNotFoundError) as info:
        loader.load_library(explicit)

    message = os.path.normcase(str(info.value))
    for checked in (explicit, env_dir, default):
        assert os.path.normcase(str(checked)) in message, f"{checked} не назван в: {info.value}"


def test_load_library_adds_dll_directory_before_loading_the_dll(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    loader = _isolated_loader(monkeypatch, tmp_path)
    sdk_dir = _make_sdk_dir(tmp_path / "sdk")
    events: list[tuple[str, str]] = []
    sentinel = object()

    class _Cookie:
        def close(self) -> None:
            events.append(("cookie_closed", ""))

    def fake_add(path: Any) -> _Cookie:
        events.append(("add_dll_directory", str(path)))
        return _Cookie()

    def fake_windll(*a: Any, **k: Any) -> object:
        path = a[0] if a else k.get("name")
        events.append(("WinDLL", str(path)))
        return sentinel

    monkeypatch.setattr(os, "add_dll_directory", fake_add, raising=False)
    monkeypatch.setattr(ctypes, "WinDLL", fake_windll, raising=False)

    lib = loader.load_library(sdk_dir)

    assert lib is sentinel
    order = [name for name, _ in events if name in ("add_dll_directory", "WinDLL")]
    assert order == ["add_dll_directory", "WinDLL"]
    got = dict(e for e in events if e[0] in ("add_dll_directory", "WinDLL"))
    assert _same(got["add_dll_directory"], sdk_dir)
    assert _same(got["WinDLL"], sdk_dir / DLL_NAME)


def _run_python(code: str, env_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["MVCR_SDK_DIR"] = str(env_dir)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


_PROBE_PREFIX = (
    "import ctypes\n"
    "attempts = []\n"
    "_orig = getattr(ctypes, 'WinDLL', None)\n"
    "def _spy(*a, **k):\n"
    "    attempts.append(str(a[0] if a else k))\n"
    "    return _orig(*a, **k)\n"
    "if _orig is not None:\n"
    "    ctypes.WinDLL = _spy\n"
)
_PROBE_SUFFIX = "mvcr = [a for a in attempts if 'MvCodeReader' in a]\nprint('MVCR_LOAD_ATTEMPTS=' + repr(mvcr))\n"


def test_import_sdk_does_not_load_dll(tmp_path: Path) -> None:
    empty = tmp_path / "empty_sdk_dir"
    empty.mkdir()
    proc = _run_python(_PROBE_PREFIX + "import Services.code_reader.sdk\n" + _PROBE_SUFFIX, empty)
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "MVCR_LOAD_ATTEMPTS=[]" in proc.stdout


def test_import_sdk_submodules_does_not_load_dll(tmp_path: Path) -> None:
    empty = tmp_path / "empty_sdk_dir"
    empty.mkdir()
    code = (
        _PROBE_PREFIX
        + "import Services.code_reader.sdk.errors, Services.code_reader.sdk.structures\n"
        + "import Services.code_reader.sdk.loader, Services.code_reader.sdk.api\n"
        + "Services.code_reader.sdk.api.MvCodeReaderApi()\n"
        + _PROBE_SUFFIX
    )
    proc = _run_python(code, empty)
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "MVCR_LOAD_ATTEMPTS=[]" in proc.stdout


def test_api_first_call_without_sdk_raises_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    loader = _isolated_loader(monkeypatch, tmp_path)
    assert loader is not None
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("MVCR_SDK_DIR", str(empty))
    api = _sdk("api").MvCodeReaderApi()  # ленивая загрузка: конструктор не падает
    with pytest.raises(_sdk("errors").SdkNotFoundError):
        _run(api.enum_devices)


# ===========================================================================
# sdk.structures
# ===========================================================================


def test_constants_have_documented_values() -> None:
    s = _sdk("structures")
    assert s.GIGE_DEVICE == 1
    assert s.PIXEL_MONO8 == 0x01080001
    assert s.PIXEL_JPEG == 0x80180001
    assert s.BAR_TYPE_NOREAD == 1001


@pytest.mark.parametrize(
    ("struct_name", "size"),
    [
        ("POINT_I", 8),
        ("CODE_INFO", 200),
        ("BCR_INFO_EX2", 4628),
        ("RESULT_BCR_EX2", 1388436),
        ("IMAGE_OUT_INFO_EX2", 200),
        ("DEVICE_INFO", 572),
        ("DEVICE_INFO_LIST", 2056),
    ],
)
def test_struct_total_size_matches_c_layout(struct_name: str, size: int) -> None:
    assert ctypes.sizeof(getattr(_sdk("structures"), struct_name)) == size


@pytest.mark.parametrize(
    ("field", "offset"),
    [
        ("nID", 0),
        ("chCode", 4),
        ("nLen", 4100),
        ("nBarType", 4104),
        ("pt", 4108),
        ("stCodeQuality", 4140),
        ("nAngle", 4340),
        ("nMainPackageId", 4344),
        ("nSubPackageId", 4348),
        ("sAppearCount", 4352),
        ("sPPM", 4354),
        ("sAlgoCost", 4356),
        ("sSharpness", 4358),
        ("bIsGetQuality", 4360),
        ("nIDRScore", 4364),  # 3 байта выравнивания после bool
        ("n1DIsGetQuality", 4368),
        ("nTotalProcCost", 4372),
        ("nTriggerTimeTvHigh", 4376),
        ("nTriggerTimeUtvLow", 4388),
        ("sPollingIndex", 4392),
        ("sRoiIndex", 4394),
        ("nLightSourceBitMap", 4396),
        ("nReserved", 4400),
    ],
)
def test_bcr_info_ex2_offsets_match_c_layout(field: str, offset: int) -> None:
    assert getattr(_sdk("structures").BCR_INFO_EX2, field).offset == offset


@pytest.mark.parametrize(
    ("field", "size"),
    [("chCode", 4096), ("pt", 32), ("stCodeQuality", 200), ("bIsGetQuality", 1), ("nReserved", 228)],
)
def test_bcr_info_ex2_field_sizes(field: str, size: int) -> None:
    assert getattr(_sdk("structures").BCR_INFO_EX2, field).size == size


@pytest.mark.parametrize(
    ("field", "offset"),
    [
        ("nOverQuality", 0),
        ("nFPDGrade", 16),
        ("nPGVGrade", 36),
        ("fSCScore", 40),
        ("fPGVScore", 68),
        ("nRMGrade", 72),
        ("fRMScore", 76),
        ("n1DEdgeGrade", 80),
        ("f1DEdgeScore", 104),
        ("f1DQZScore", 124),
        ("nReserved", 128),
    ],
)
def test_code_info_offsets_match_c_layout(field: str, offset: int) -> None:
    assert getattr(_sdk("structures").CODE_INFO, field).offset == offset


def test_point_i_layout() -> None:
    p = _sdk("structures").POINT_I
    assert (p.x.offset, p.y.offset) == (0, 4)


@pytest.mark.parametrize(
    ("struct_name", "field", "offset"),
    [
        ("RESULT_BCR_EX2", "nCodeNum", 0),
        ("RESULT_BCR_EX2", "stBcrInfoEx2", 4),
        ("RESULT_BCR_EX2", "nNoReadNum", 1388404),
        ("RESULT_BCR_EX2", "nRes", 1388406),
        ("RESULT_BCR_EX2", "nReserved", 1388408),
        ("IMAGE_OUT_INFO_EX2", "nWidth", 0),
        ("IMAGE_OUT_INFO_EX2", "nHeight", 2),
        ("IMAGE_OUT_INFO_EX2", "enPixelType", 4),
        ("IMAGE_OUT_INFO_EX2", "nTriggerIndex", 8),
        ("IMAGE_OUT_INFO_EX2", "nFrameNum", 12),
        ("IMAGE_OUT_INFO_EX2", "nFrameLen", 16),
        ("IMAGE_OUT_INFO_EX2", "nFocusScore", 32),
        ("IMAGE_OUT_INFO_EX2", "bIsGetCode", 36),
        ("IMAGE_OUT_INFO_EX2", "pstCodeListEx", 40),  # после bool: пад до 8
        ("IMAGE_OUT_INFO_EX2", "pstWaybillList", 48),
        ("IMAGE_OUT_INFO_EX2", "nEventID", 56),
        ("IMAGE_OUT_INFO_EX2", "nImageCost", 64),
        ("IMAGE_OUT_INFO_EX2", "UnparsedBcrList", 72),
        ("IMAGE_OUT_INFO_EX2", "UnparsedOcrList", 80),
        ("IMAGE_OUT_INFO_EX2", "nWholeFlag", 88),
        ("IMAGE_OUT_INFO_EX2", "nRes", 90),
        ("IMAGE_OUT_INFO_EX2", "UnparsedAgvInfo", 96),
        ("IMAGE_OUT_INFO_EX2", "nReserved", 104),
    ],
)
def test_result_bcr_ex2_and_image_out_info_ex2_layout(struct_name: str, field: str, offset: int) -> None:
    assert getattr(getattr(_sdk("structures"), struct_name), field).offset == offset


@pytest.mark.parametrize(
    ("struct_name", "field", "size"),
    [
        ("IMAGE_OUT_INFO_EX2", "bIsGetCode", 1),  # C bool: DLL пишет один байт
        ("IMAGE_OUT_INFO_EX2", "enPixelType", 4),
        ("IMAGE_OUT_INFO_EX2", "UnparsedBcrList", 8),
        ("DEVICE_INFO", "bSelectDevice", 1),
        ("DEVICE_INFO", "SpecialInfo", 540),  # max(GigE 216, USB3 540)
    ],
)
def test_field_sizes_match_c_layout(struct_name: str, field: str, size: int) -> None:
    assert getattr(getattr(_sdk("structures"), struct_name), field).size == size


def test_result_bcr_ex2_holds_300_entries() -> None:
    assert _sdk("structures").RESULT_BCR_EX2.stBcrInfoEx2.size == 300 * 4628


@pytest.mark.parametrize(
    ("struct_name", "field", "offset"),
    [
        ("DEVICE_INFO", "nTLayerType", 12),
        ("DEVICE_INFO", "nDeviceType", 16),
        ("DEVICE_INFO", "bSelectDevice", 20),
        ("DEVICE_INFO", "nWebHostIp", 24),
        ("DEVICE_INFO", "SpecialInfo", 32),
        ("DEVICE_INFO_LIST", "nDeviceNum", 0),
        ("DEVICE_INFO_LIST", "pDeviceInfo", 8),
    ],
)
def test_device_info_layout(struct_name: str, field: str, offset: int) -> None:
    assert getattr(getattr(_sdk("structures"), struct_name), field).offset == offset


def test_bcr_info_ex2_reads_field_types_from_raw_c_bytes() -> None:
    """Типы (знак/ширина) проверяем на сыром буфере, собранном по литеральным смещениям."""
    buf = (ctypes.c_ubyte * 4628)()
    a = ctypes.addressof(buf)
    _poke(a + 0, "I", 4294967295)  # nID: unsigned
    _poke(a + 4, "5s", b"AB\x00CD")
    _poke(a + 4100, "I", 4294967295)  # nLen: unsigned
    _poke(a + 4108 + 16, "ii", -5, -6)  # pt[2]: знаковые
    _poke(a + 4140, "i", 4)  # stCodeQuality.nOverQuality
    _poke(a + 4340, "i", -7)  # nAngle: знаковый
    _poke(a + 4354, "H", 65535)  # sPPM: unsigned short
    _poke(a + 4356, "H", 65534)  # sAlgoCost: unsigned short
    _poke(a + 4360, "B", 1)  # bIsGetQuality
    _poke(a + 4364, "I", 4294967294)  # nIDRScore: unsigned
    _poke(a + 4396, "I", 4294967293)  # nLightSourceBitMap

    e = _sdk("structures").BCR_INFO_EX2.from_buffer_copy(buf)

    assert e.nID == 4294967295
    assert bytes(e.chCode)[:2] == b"AB"
    assert e.nLen == 4294967295
    assert (e.pt[2].x, e.pt[2].y) == (-5, -6)
    assert e.stCodeQuality.nOverQuality == 4
    assert e.nAngle == -7
    assert e.sPPM == 65535
    assert e.sAlgoCost == 65534
    assert bool(e.bIsGetQuality) is True
    assert e.nIDRScore == 4294967294
    assert e.nLightSourceBitMap == 4294967293


def test_code_info_reads_float_scores_from_raw_c_bytes() -> None:
    buf = (ctypes.c_ubyte * 200)()
    a = ctypes.addressof(buf)
    _poke(a + 40, "f", 2.5)  # fSCScore
    _poke(a + 76, "f", 0.75)  # fRMScore
    _poke(a + 124, "f", 1.5)  # f1DQZScore
    q = _sdk("structures").CODE_INFO.from_buffer_copy(buf)
    assert q.fSCScore == pytest.approx(2.5)
    assert q.fRMScore == pytest.approx(0.75)
    assert q.f1DQZScore == pytest.approx(1.5)


# ===========================================================================
# sdk.api: enum / open / start / stop / close
# ===========================================================================

_DEVICES = [
    {"ip_int": 0xC0A8010A, "model": "MV-ID3013PM-06M", "serial": "DA1234567"},
    {"ip_int": 0x0A000007, "model": "MV-ID3004PM", "serial": "DA7654321"},
]


def test_enum_devices_returns_entries_with_ip_model_serial() -> None:
    lib = FakeLib(devices=_DEVICES)
    entries = _run(_api(lib).enum_devices)
    assert [(e.ip, e.model, e.serial) for e in entries] == [
        ("192.168.1.10", "MV-ID3013PM-06M", "DA1234567"),
        ("10.0.0.7", "MV-ID3004PM", "DA7654321"),
    ]


def test_enum_devices_empty_list_when_no_devices() -> None:
    assert _run(_api(FakeLib(devices=[])).enum_devices) == []


def test_enum_devices_asks_gige_layer() -> None:
    lib = FakeLib(devices=_DEVICES)
    _run(_api(lib).enum_devices)
    (args,) = lib.args_of("EnumDevices")
    assert _hv(args[1]) == 1


def test_enum_devices_error_raises_sdk_error_with_code() -> None:
    errors = _sdk("errors")
    lib = FakeLib(returns={"EnumDevices": E_PRECONDITION})
    with pytest.raises(errors.SdkError) as info:
        _run(_api(lib).enum_devices)
    assert info.value.code == E_PRECONDITION


def test_open_creates_handle_then_opens_it_and_returns_handle() -> None:
    lib = FakeLib(devices=_DEVICES, handle=0x5150)
    api = _api(lib)
    entries = _run(api.enum_devices)
    handle = _run(api.open, entries[1])

    assert _hv(handle) == 0x5150
    names = lib.names()
    assert names.index("CreateHandle") < names.index("OpenDevice")
    (create_args,) = lib.args_of("CreateHandle")
    assert _address_of(create_args[1]) == ctypes.addressof(lib.dev_bufs[1])
    (open_args,) = lib.args_of("OpenDevice")
    assert _hv(open_args[0]) == 0x5150


def test_open_access_denied_raises_sdk_error_and_destroys_created_handle() -> None:
    errors = _sdk("errors")
    lib = FakeLib(devices=_DEVICES, handle=0x5150, returns={"OpenDevice": E_ACCESS_DENIED_SIGNED})
    api = _api(lib)
    entries = _run(api.enum_devices)
    with pytest.raises(errors.SdkError) as info:
        _run(api.open, entries[0])
    assert info.value.code == E_ACCESS_DENIED
    assert [_hv(a[0]) for a in lib.args_of("DestroyHandle")] == [0x5150]


@pytest.mark.parametrize(("method", "fn"), [("start_grabbing", "StartGrabbing"), ("stop_grabbing", "StopGrabbing")])
def test_start_stop_grabbing_call_dll_with_handle(method: str, fn: str) -> None:
    lib = FakeLib()
    _run(getattr(_api(lib), method), 0x5150)
    assert [_hv(a[0]) for a in lib.args_of(fn)] == [0x5150]


@pytest.mark.parametrize(("method", "fn"), [("start_grabbing", "StartGrabbing"), ("stop_grabbing", "StopGrabbing")])
def test_start_stop_grabbing_error_raises_sdk_error(method: str, fn: str) -> None:
    errors = _sdk("errors")
    lib = FakeLib(returns={fn: E_ACCESS_DENIED_SIGNED})
    with pytest.raises(errors.SdkError) as info:
        _run(getattr(_api(lib), method), 0x5150)
    assert info.value.code == E_ACCESS_DENIED


def test_close_calls_close_device_then_destroy_handle() -> None:
    lib = FakeLib()
    _run(_api(lib).close, 0x5150)
    assert lib.names() == ["CloseDevice", "DestroyHandle"]
    assert _hv(lib.args_of("CloseDevice")[0][0]) == 0x5150
    assert _hv(lib.args_of("DestroyHandle")[0][0]) == 0x5150


def test_close_calls_destroy_even_if_close_device_fails() -> None:
    lib = FakeLib(returns={"CloseDevice": E_PRECONDITION})
    try:
        _run(_api(lib).close, 0x5150)
    except _sdk("errors").SdkError:
        pass  # контракт не говорит, поднимать ли ошибку; обязателен только DestroyHandle
    assert [_hv(a[0]) for a in lib.args_of("DestroyHandle")] == [0x5150]


# ===========================================================================
# sdk.api: get_frame / RawFrame
# ===========================================================================


@pytest.mark.parametrize("rc", [E_NODATA, E_NODATA_SIGNED])
def test_get_frame_nodata_returns_none(rc: int) -> None:
    lib = FakeLib(returns={"GetOneFrameTimeoutEx2": rc})
    assert _run(_api(lib).get_frame, 0x5150, 500) is None


def test_get_frame_nodata_is_a_single_dll_call_not_a_retry_loop() -> None:
    lib = FakeLib(returns={"GetOneFrameTimeoutEx2": E_NODATA})
    _run(_api(lib).get_frame, 0x5150, 500)
    assert lib.names().count("GetOneFrameTimeoutEx2") == 1


@pytest.mark.parametrize("rc", [E_ACCESS_DENIED, E_ACCESS_DENIED_SIGNED])
def test_get_frame_access_denied_raises_sdk_error_with_code(rc: int) -> None:
    errors = _sdk("errors")
    lib = FakeLib(returns={"GetOneFrameTimeoutEx2": rc})
    with pytest.raises(errors.SdkError) as info:
        _run(_api(lib).get_frame, 0x5150, 500)
    assert info.value.code == 0x80020203
    assert "0x80020203" in str(info.value)


def test_get_frame_neighbour_of_nodata_code_is_an_error_not_none() -> None:
    errors = _sdk("errors")
    lib = FakeLib(returns={"GetOneFrameTimeoutEx2": E_PRECONDITION})
    with pytest.raises(errors.SdkError) as info:
        _run(_api(lib).get_frame, 0x5150, 500)
    assert info.value.code == 0x80020007


def test_get_frame_passes_handle_and_timeout_to_dll() -> None:
    lib = FakeLib(frames=[_frame_a()])
    _run(_api(lib).get_frame, 0x5150, 731)
    (args,) = lib.args_of("GetOneFrameTimeoutEx2")
    assert _hv(args[0]) == 0x5150
    assert _hv(args[3]) == 731


def test_get_frame_returns_frame_level_fields() -> None:
    lib = FakeLib(frames=[_frame_a()])
    raw = _run(_api(lib).get_frame, 0x5150, 500)
    view = _frame_view(raw)
    assert view["width"] == 640
    assert view["height"] == 480
    assert view["pixel_type"] == PIX_MONO8
    assert view["trigger_index"] == 7
    assert view["frame_num"] == 3
    assert view["no_read_num"] == 1


def test_raw_frame_image_is_bytes_of_frame_len_jpeg() -> None:
    jpeg = b"\xff\xd8\xff\xe0JFIF\x00\xff\xd9"  # 11 байт, не width*height
    fr = _frame_a()
    fr.update(image=jpeg, pixel_type=PIX_JPEG, codes=[])
    raw = _run(_api(FakeLib(frames=[fr])).get_frame, 0x5150, 500)
    view = _frame_view(raw)
    assert isinstance(view["image"], bytes)
    assert view["image"] == jpeg
    assert view["pixel_type"] == 0x80180001


def test_raw_frame_codes_are_parsed_per_ncodenum() -> None:
    lib = FakeLib(frames=[_frame_a()])
    raw = _run(_api(lib).get_frame, 0x5150, 500)
    assert _frame_view(raw)["n_codes"] == 2
    first, second = (_code_view(c) for c in raw.codes)
    assert first == {
        "text": b"QR-30MM",
        "n_len": 7,
        "bar_type": 5,
        "pts": QUAD_A,
        "overall": 3,
        "angle": 900,
        "ppm": 1234,
        "algo": 12,
        "has_quality": True,
        "idr": 77,
    }
    assert second["n_len"] == 0
    assert second["text"] == b""
    assert second["bar_type"] == 1001
    assert second["pts"] == QUAD_B
    assert second["angle"] == -1
    assert second["has_quality"] is False


def test_raw_frame_has_no_codes_when_ncodenum_is_zero() -> None:
    fr = _frame_a()
    fr.update(codes=[], no_read_num=0)
    raw = _run(_api(FakeLib(frames=[fr])).get_frame, 0x5150, 500)
    assert _frame_view(raw)["n_codes"] == 0


def test_raw_frame_has_no_codes_when_code_list_pointer_is_null() -> None:
    fr = _frame_a()
    fr.update(null_code_list=True)
    raw = _run(_api(FakeLib(frames=[fr])).get_frame, 0x5150, 500)
    assert _frame_view(raw)["n_codes"] == 0


def test_raw_frame_is_a_copy_not_a_view() -> None:
    lib = FakeLib(frames=[_frame_a()])
    raw = _run(_api(lib).get_frame, 0x5150, 500)
    expected = bytes(range(32))
    assert _frame_view(raw)["image"] == expected

    ctypes.memset(lib.image_buf, 0xFF, len(lib.image_buf))  # SDK «перезаписал» буфер

    assert bytes(_frame_view(raw)["image"]) == expected


def test_raw_frame_codes_survive_overwriting_of_sdk_result_buffer() -> None:
    lib = FakeLib(frames=[_frame_a()])
    raw = _run(_api(lib).get_frame, 0x5150, 500)
    ctypes.memset(lib.result_buf, 0xFF, _RESULT_SIZE)

    first = _code_view(raw.codes[0])
    assert first["text"] == b"QR-30MM"
    assert first["pts"] == QUAD_A
    assert first["bar_type"] == 5
    assert _code_view(raw.codes[1])["bar_type"] == 1001


def test_raw_frame_stays_valid_after_next_get_frame_reuses_the_buffers() -> None:
    second = _frame_a()
    second.update(
        image=b"\xaa" * 32,
        frame_num=4,
        codes=[{"text": b"OTHER", "bar_type": 9, "pts": QUAD_B}],
    )
    lib = FakeLib(frames=[_frame_a(), second])  # оба кадра идут через ОДНИ буферы фейка
    api = _api(lib)
    first_raw = _run(api.get_frame, 0x5150, 500)
    second_raw = _run(api.get_frame, 0x5150, 500)

    assert _frame_view(second_raw)["image"] == b"\xaa" * 32
    assert _frame_view(first_raw)["image"] == bytes(range(32))
    assert _frame_view(first_raw)["frame_num"] == 3
    assert _code_view(first_raw.codes[0])["text"] == b"QR-30MM"
    assert _code_view(second_raw.codes[0])["text"] == b"OTHER"
