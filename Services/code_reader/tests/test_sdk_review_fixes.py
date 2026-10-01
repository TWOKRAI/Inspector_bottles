# -*- coding: utf-8 -*-
"""Тесты правок по ревью Task 6.1/6.2 (автор — лидер; ревью 2026-09-29).

Каждый тест закрывает одну находку с воспроизведением ревьюера:
п.1 — DLL на месте, но не грузится → ``SdkNotFoundError``, кука пути снята;
п.2 — нуль внутри кода не обрывает текст;
п.3 — отказ ``DestroyHandle`` после отказа ``OpenDevice`` не теряется;
п.4 — повторный ``load_library`` не копит записи пути поиска DLL;
6.2 — ``interfaces`` не тянет OpenCV (TCP-плагину он не нужен).
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

import pytest

from Services.code_reader.core.sdk_frame import frame_from_raw
from Services.code_reader.sdk import api as api_mod
from Services.code_reader.sdk import loader
from Services.code_reader.sdk.errors import SdkError, SdkNotFoundError
from Services.code_reader.sdk.structures import BCR_INFO_EX2, PIXEL_JPEG, code_bytes
from Services.code_reader.tests.test_sdk_reader import (  # фейк и фикстура слепого набора — не дублировать
    ERR,
    FakeApi,
    code,
    make_raw,
    make_reader,  # noqa: F401 — pytest-фикстура
    sdk_error,
    wait_until,
)

ROOT = Path(__file__).resolve().parents[3]


def _record(raw: bytes) -> BCR_INFO_EX2:
    rec = BCR_INFO_EX2()
    ctypes.memmove(ctypes.addressof(rec) + BCR_INFO_EX2.chCode.offset, raw, len(raw))
    rec.nLen = len(raw)
    return rec


def test_code_bytes_keeps_nul_inside_code() -> None:
    assert code_bytes(_record(b"AB\x00CD")) == b"AB\x00CD"


def test_frame_text_keeps_nul_inside_code() -> None:
    raw = api_mod.RawFrame(
        image=b"",
        width=1,
        height=1,
        pixel_type=PIXEL_JPEG,
        trigger_index=0,
        frame_num=0,
        no_read_num=0,
        codes=(_record(b"AB\x00CD"),),
    )
    assert frame_from_raw(raw).codes[0].text == "AB\x00CD"


@pytest.fixture
def sdk_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / loader.DLL_NAME).write_bytes(b"MZ")
    monkeypatch.setattr(loader, "_dll_dir_cookies", {})
    return tmp_path


class _Cookie:
    def __init__(self, log: list[str], path: str) -> None:
        self._log, self._path = log, path

    def close(self) -> None:
        self._log.append(f"close {self._path}")


def test_dll_present_but_unloadable_raises_not_found_and_drops_cookie(
    sdk_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log: list[str] = []
    monkeypatch.setattr(os, "add_dll_directory", lambda p: (log.append(f"add {p}"), _Cookie(log, p))[1])

    def broken_winddl(path: str, *a: object, **k: object) -> object:
        raise FileNotFoundError(f"Could not find module '{path}' (or one of its dependencies)")

    monkeypatch.setattr(ctypes, "WinDLL", broken_winddl)
    with pytest.raises(SdkNotFoundError) as info:
        loader.load_library(sdk_dir)
    assert "не загрузился" in str(info.value)
    assert isinstance(info.value.__cause__, OSError)
    assert log == [f"add {sdk_dir}", f"close {sdk_dir}"]
    assert loader._dll_dir_cookies == {}


def test_repeated_load_library_adds_search_path_once(sdk_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    monkeypatch.setattr(os, "add_dll_directory", lambda p: (log.append(f"add {p}"), _Cookie(log, p))[1])
    monkeypatch.setattr(ctypes, "WinDLL", lambda path, *a, **k: object())
    for _ in range(3):
        loader.load_library(sdk_dir)
    assert log == [f"add {sdk_dir}"]


class _FailingOpenLib:
    """OpenDevice отказал, DestroyHandle тоже вернул ошибку."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        def fn(*args: object) -> int:
            self.calls.append(name)
            if name == "MV_CODEREADER_OpenDevice":
                return 0x80020203
            if name == "MV_CODEREADER_DestroyHandle":
                return 0x80000000
            return 0

        return fn


def test_destroy_failure_after_open_failure_is_not_lost() -> None:
    lib = _FailingOpenLib()
    entry = api_mod.DeviceEntry(ip="1.2.3.4", model="m", serial="s", info=api_mod.DEVICE_INFO())
    with pytest.raises(SdkError) as info:
        api_mod.MvCodeReaderApi(lib=lib).open(entry)
    assert info.value.code == 0x80020203
    assert any("0x80000000" in note for note in getattr(info.value, "__notes__", []))
    assert "MV_CODEREADER_DestroyHandle" in lib.calls


def test_nodata_resets_consecutive_error_counter(make_reader) -> None:  # noqa: F811 — фикстура из слепого набора
    """План, уточнение §6: E_NODATA — успешный вызов. Пробел нашла инъекция K5 лидера:
    без сброса ошибки «2 + пусто + 1» считались бы тремя подряд, и живой прибор
    закрывался бы из-за одиночных сбоев, разделённых тишиной между срабатываниями."""
    script = [sdk_error(ERR), sdk_error(ERR), None, sdk_error(ERR), sdk_error(ERR), make_raw([code()], trigger=9)]
    api = FakeApi(script=script)
    r = make_reader(api, timeout_ms=10)
    r.reader.start()
    try:
        assert wait_until(lambda: len(r.frames) == 1)
        assert r.reader.state == "running"
        assert api.count("close") == 0
    finally:
        r.reader.stop()


class _CableCutApi(FakeApi):
    """Обрыв кабеля: после ошибок get_frame падают и StopGrabbing, и CloseDevice."""

    def stop_grabbing(self, h):
        super().stop_grabbing(h)
        raise sdk_error(0x80000007, "StopGrabbing")

    def close(self, h):
        super().close(h)
        raise sdk_error(0x80000007, "CloseDevice")


def test_final_failure_reason_survives_failing_release(make_reader) -> None:  # noqa: F811
    """Ревью 6.2 итерации 2, п.2: причина сбоя в stats() не перетирается ошибкой close."""
    api = _CableCutApi(script=[sdk_error(ERR)] * 3)
    r = make_reader(api, timeout_ms=10)
    r.reader.start()
    try:
        assert wait_until(lambda: r.reader.state == "error" and api.count("close") == 1)
        assert wait_until(lambda: "подряд" in (r.reader.stats()["last_error"] or ""))
        assert "подряд" in r.reader.stats()["last_error"]
    finally:
        r.reader.stop()


def test_interfaces_import_does_not_pull_opencv() -> None:
    code = "import sys, Services.code_reader.interfaces; print('cv2' in sys.modules)"
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"
