# -*- coding: utf-8 -*-
"""Зонд ``mvcr_probe`` не молчит, когда SDK не дал кадр (H5): строки ``no_frame`` и ``summary``.

SDK подменён фейком через ``main(..., api=...)``, часы зонда — фейковые: каждый ``get_frame`` сдвигает
их на ``STEP`` секунд, поэтому число вызовов и ``t_s`` детерминированы. Ожидаемые значения — литералы.
"""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

from Services.code_reader.sdk.api import RawFrame
from Services.code_reader.sdk.errors import SdkError

STEP = 0.12345  # секунд на один get_frame; не кратно 0.001 — проверяет округление t_s
SECONDS = "0.7"  # при STEP это ровно 6 вызовов get_frame
STOP_MARK = "<STOP_GRABBING>"


def _frame(trigger: int) -> RawFrame:
    return RawFrame(
        image=b"abcd",
        width=1280,
        height=1024,
        pixel_type=0x1080001,
        trigger_index=trigger,
        frame_num=trigger + 100,
        no_read_num=0,
        codes=(),
    )


def _timeout_error() -> SdkError:
    return SdkError(0x80020203, "MV_CODEREADER_GetOneFrameTimeoutEx2")


class _Api:
    """Отдаёт ``script`` по одному элементу на ``get_frame``: кадр, ``None`` или исключение (бросается)."""

    def __init__(self, script: list[Any], *, start_exc: BaseException | None = None) -> None:
        self.script = list(script)
        self.start_exc = start_exc
        self.now = 100.0
        self.sleeps: list[float] = []
        self.journal: list[str] = []

    def enum_devices(self) -> list[Any]:
        return [SimpleNamespace(ip="10.0.0.1", model="FAKE", serial="S1")]

    def open(self, dev: Any) -> int:
        return 1

    def close(self, h: Any) -> None:
        self.journal.append("close")

    def start_grabbing(self, h: Any) -> None:
        self.journal.append("start_grabbing")
        if self.start_exc is not None:
            raise self.start_exc
        self.now += 5.0  # сам запуск захвата длится: t_s считается ОТ его конца, не от точки до вызова

    def stop_grabbing(self, h: Any) -> None:
        self.journal.append("stop_grabbing")
        print(STOP_MARK, flush=True)

    def get_frame(self, h: Any, timeout_ms: int = 1000) -> Any:
        if not self.script:  # лишний вызов: фейк сам заканчивает захват, сломанный зонд не повисает
            self.now += 1000.0
            raise AssertionError("зонд позвал get_frame больше раз, чем есть в сценарии")
        self.now += STEP
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture
def probe() -> Any:
    return importlib.import_module("Services.code_reader.tools.mvcr_probe")


def _fake_clock(probe: Any, monkeypatch: pytest.MonkeyPatch, api: _Api) -> None:
    monkeypatch.setattr(probe, "time", SimpleNamespace(perf_counter=lambda: api.now, sleep=api.sleeps.append))


def _mixed() -> _Api:
    """3 кадра, 2 ``None``, 1 ``SdkError``."""
    return _Api([_frame(1), None, _frame(2), _timeout_error(), None, _frame(3)])


def _go(probe: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], api: _Api) -> list[str]:
    _fake_clock(probe, monkeypatch, api)
    assert probe.main([SECONDS], api=api) == 0
    return capsys.readouterr().out.splitlines()


def _json_lines(lines: list[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in lines if line.startswith("{")]


def _events(lines: list[str], name: str) -> list[dict[str, Any]]:
    return [rec for rec in _json_lines(lines) if rec.get("event") == name]


# -- приёмочные ----------------------------------------------------------------------------------------


def test_none_gives_no_frame_line(
    probe: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = _go(probe, monkeypatch, capsys, _mixed())
    nones = [rec for rec in _events(lines, "no_frame") if rec["kind"] == "none"]
    assert nones == [
        {"event": "no_frame", "t_s": 0.247, "kind": "none"},
        {"event": "no_frame", "t_s": 0.617, "kind": "none"},
    ]


def test_sdk_error_gives_no_frame_line(
    probe: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    api = _mixed()
    lines = _go(probe, monkeypatch, capsys, api)
    errors = [rec for rec in _events(lines, "no_frame") if rec["kind"] == "sdk_error"]
    assert errors == [
        {
            "event": "no_frame",
            "t_s": 0.494,
            "kind": "sdk_error",
            "error": "MV_CODEREADER_GetOneFrameTimeoutEx2 вернул 0x80020203",
        }
    ]
    assert "MV_CODEREADER_GetOneFrameTimeoutEx2 вернул 0x80020203" not in lines  # вместо печати текста
    assert api.sleeps == [0.175]  # пауза после SdkError осталась: min(0.2, 0.7 / 4)


def test_summary_line_counts(probe: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    lines = _go(probe, monkeypatch, capsys, _mixed())
    assert _events(lines, "summary") == [
        {
            "event": "summary",
            "frames": 3,
            "none_count": 2,
            "sdk_error_count": 1,
            "first_no_frame_s": 0.247,
            "last_no_frame_s": 0.617,
        }
    ]
    order = [rec.get("event", "frame") for rec in _json_lines(lines)]
    assert order == ["frame", "no_frame", "frame", "no_frame", "no_frame", "frame", "summary"]
    assert [rec["kind"] for rec in _events(lines, "no_frame")] == ["none", "sdk_error", "none"]
    summary_at = next(i for i, line in enumerate(lines) if '"summary"' in line)
    assert lines[summary_at + 1] == STOP_MARK  # прямо перед stop_grabbing
    assert lines[-1].startswith("ИТОГ кадров: 3 с_кодом: 0 read: 0 noread: 0 ")


def test_frame_lines_unchanged(probe: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Охранный (зелёный и до H5): ``None`` и ``SdkError`` не меняют строки кадров и их нумерацию."""
    lines = _go(probe, monkeypatch, capsys, _mixed())
    frame_lines = [line for line in lines if line.startswith('{"trigger"')]
    head = '"size": [1280, 1024], "pix": "0x1080001", "len": 4, "no_read_num": 0, "codes": []'
    assert frame_lines == [
        '{"trigger": 1, "frame_num": 101, ' + head + ', "frame": 1}',
        '{"trigger": 2, "frame_num": 102, ' + head + ', "frame": 2}',
        '{"trigger": 3, "frame_num": 103, ' + head + ', "frame": 3}',
    ]


# -- опасности: любой выход из захвата ------------------------------------------------------------------


def test_foreign_exception_propagates_and_stops_grabbing(probe: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Охранный (зелёный и до H5): чужое исключение из ``get_frame`` выходит наружу, захват остановлен."""
    exc = RuntimeError("чужое")
    api = _Api([_frame(1), None, exc])
    _fake_clock(probe, monkeypatch, api)
    with pytest.raises(RuntimeError) as caught:
        probe.main([SECONDS], api=api)
    assert caught.value is exc
    assert api.journal == ["start_grabbing", "stop_grabbing", "close"]


@pytest.mark.parametrize("exc", [RuntimeError("чужое"), KeyboardInterrupt()], ids=["RuntimeError", "Ctrl+C"])
def test_summary_is_printed_when_capture_is_broken_off(
    probe: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], exc: BaseException
) -> None:
    api = _Api([_frame(1), None, exc])
    _fake_clock(probe, monkeypatch, api)
    with pytest.raises(type(exc)):
        probe.main([SECONDS], api=api)
    lines = capsys.readouterr().out.splitlines()
    assert _events(lines, "summary") == [
        {
            "event": "summary",
            "frames": 1,
            "none_count": 1,
            "sdk_error_count": 0,
            "first_no_frame_s": 0.247,
            "last_no_frame_s": 0.247,
        }
    ]
    assert len(_events(lines, "no_frame")) == 1  # чужое исключение — не «нет кадра»


def test_summary_without_no_frame_has_null_times(
    probe: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = _go(probe, monkeypatch, capsys, _Api([_frame(n) for n in range(1, 7)]))
    assert _events(lines, "no_frame") == []
    assert _events(lines, "summary") == [
        {
            "event": "summary",
            "frames": 6,
            "none_count": 0,
            "sdk_error_count": 0,
            "first_no_frame_s": None,
            "last_no_frame_s": None,
        }
    ]


def test_no_summary_when_start_grabbing_failed(
    probe: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    api = _Api([], start_exc=_timeout_error())
    _fake_clock(probe, monkeypatch, api)
    with pytest.raises(SdkError):
        probe.main([SECONDS], api=api)
    assert api.journal == ["start_grabbing", "stop_grabbing", "close"]
    assert _events(capsys.readouterr().out.splitlines(), "summary") == []


def test_failed_summary_print_does_not_skip_stop_grabbing(probe: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def dumps(obj: Any, **kwargs: Any) -> str:
        if obj.get("event") == "summary":
            raise OSError("stdout закрыт")
        return json.dumps(obj, **kwargs)

    api = _mixed()
    _fake_clock(probe, monkeypatch, api)
    monkeypatch.setattr(probe, "json", SimpleNamespace(dumps=dumps))
    with pytest.raises(OSError, match="stdout закрыт"):
        probe.main([SECONDS], api=api)
    assert api.journal == ["start_grabbing", "stop_grabbing", "close"]
