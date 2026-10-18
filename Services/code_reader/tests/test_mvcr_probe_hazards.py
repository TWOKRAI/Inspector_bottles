# -*- coding: utf-8 -*-
"""Hazard-тесты зонда ``mvcr_probe`` (ревью Task 2.1, итерация 1): восстановление узлов при ЛЮБОМ выходе.

После ``--set`` свободный режим греет прибор, поэтому исходные значения обязаны вернуться, что бы ни бросил
``stop_grabbing``, ``start_grabbing`` или сама запись оригинала. Фейк и хелперы берутся из ``test_sdk_params``
(тест тестера не правится); ожидаемые значения — литералы.
"""

from __future__ import annotations

import importlib
import re
from types import SimpleNamespace
from typing import Any

import pytest

from Services.code_reader.sdk.errors import SdkError
from Services.code_reader.tests.test_sdk_params import (
    TRIGGER_OFF,
    TWO_NODES,
    FakeApi,
    _main,
    _out,
    _run,
)

E_GC_RANGE = 0x80020102


@pytest.fixture
def probe() -> Any:
    return importlib.import_module("Services.code_reader.tools.mvcr_probe")


def _restores(fake: FakeApi) -> list[tuple[str, int]]:
    return [(k, v) for n, k, v in fake.set_calls() if n == "set_enum"]


class _StartRaises(FakeApi):
    """``start_grabbing`` успел начать захват и бросил."""

    def start_grabbing(self, h: Any) -> None:
        super().start_grabbing(h)
        raise KeyboardInterrupt


# -- a) stop_grabbing бросает не SdkError -----------------------------------------------------------


@pytest.mark.parametrize("exc", [RuntimeError("stop-boom"), OSError("stop-os")], ids=["RuntimeError", "OSError"])
def test_stop_grabbing_exception_is_printed_and_restore_runs_exactly_once(
    probe: Any, capsys: pytest.CaptureFixture[str], exc: Exception
) -> None:
    fake = FakeApi(fail={("stop_grabbing", ""): exc})
    _main(probe, TRIGGER_OFF, fake)
    assert _restores(fake) == [("TriggerMode", 1)]
    assert fake.journal[-1] == "close"
    assert fake.journal.count("close") == 1
    assert type(exc).__name__ in _out(capsys)


def test_stop_grabbing_keyboard_interrupt_still_restores_then_propagates(probe: Any) -> None:
    fake = FakeApi(fail={("stop_grabbing", ""): KeyboardInterrupt()})
    with pytest.raises(KeyboardInterrupt):
        _run(lambda: probe.main(TRIGGER_OFF, api=fake))
    j = fake.journal
    assert _restores(fake) == [("TriggerMode", 1)]
    assert j.index("stop_grabbing") < j.index("set_enum") < j.index("close")


def test_guard_stop_grabbing_without_failure_restores_exactly_once_too(probe: Any) -> None:
    """Парный страж к a): без отказа восстановление тоже ровно одно (иначе 'ровно один' вакуумно)."""
    fake = FakeApi()
    assert _main(probe, TRIGGER_OFF, fake) == 0
    assert _restores(fake) == [("TriggerMode", 1)]


# -- b) сбой восстановления одного узла не пропускает остальные ------------------------------------------


def test_restore_oserror_on_first_node_still_restores_second_and_closes(
    probe: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeApi(fail={("set_enum", "TriggerMode"): OSError("av")})
    rc = _main(probe, TWO_NODES, fake)
    assert rc == 3
    assert ("RunningMode", 0) in _restores(fake)  # второй узел попытан
    assert fake.journal[-1] == "close"
    assert re.search(r"RESTORE FAILED TriggerMode orig=1 OSError", _out(capsys))


def test_restore_keyboard_interrupt_walks_all_nodes_then_propagates(
    probe: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeApi(fail={("set_enum", "TriggerMode"): KeyboardInterrupt()})
    with pytest.raises(KeyboardInterrupt):
        _run(lambda: probe.main(TWO_NODES, api=fake))
    assert ("RunningMode", 0) in _restores(fake)  # обход не прерван
    assert fake.journal[-1] == "close"
    assert re.search(r"RESTORE FAILED TriggerMode orig=1 KeyboardInterrupt", _out(capsys))


# -- c) start_grabbing бросил после начала захвата -----------------------------------------------------


def test_start_grabbing_interrupt_still_stops_grabbing_and_restores(probe: Any) -> None:
    fake = _StartRaises()
    with pytest.raises(KeyboardInterrupt):
        _run(lambda: probe.main(TRIGGER_OFF, api=fake))
    j = fake.journal
    assert "stop_grabbing" in j
    assert _restores(fake) == [("TriggerMode", 1)]
    assert j.index("start_grabbing") < j.index("stop_grabbing") < j.index("set_enum") < j.index("close")


def test_guard_stop_grabbing_is_not_called_when_start_never_ran(probe: Any) -> None:
    """Парный страж к c): запись отказала до start_grabbing -> stop_grabbing не зовётся (и грабить нечего)."""
    fake = FakeApi(fail={("set_enum_str", "TriggerMode"): SdkError(E_GC_RANGE, "x")})
    assert _main(probe, TRIGGER_OFF, fake) == 1
    assert "start_grabbing" not in fake.journal
    assert "stop_grabbing" not in fake.journal


# -- d) seconds=0 без --set -------------------------------------------------------------------------------


def test_zero_seconds_without_set_does_not_divide_by_zero(probe: Any, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeApi()
    assert _main(probe, ["0"], fake) == 0
    out = capsys.readouterr().out
    assert "ИТОГ кадров: 0" in out
    assert "fps: 0.0" in out
    assert not [n for n in fake.journal if n.startswith("set_")]


# -- e) сценарий 3: восстановление отказавшего узла тоже выполнено ---------------------------------------------


def test_scenario3_failed_node_gets_its_original_written_back(probe: Any) -> None:
    fake = FakeApi(fail={("set_enum_str", "RunningMode"): SdkError(E_GC_RANGE, "MV_CODEREADER_SetEnumValueByString")})
    rc = _main(probe, TWO_NODES, fake)
    assert rc == 1  # восстановление удалось, отказ записи остаётся причиной выхода
    assert ("set_enum", "RunningMode", 0) in fake.set_calls()
    assert ("set_enum", "TriggerMode", 1) in fake.set_calls()


# -- f) умолчания и граница секунд -------------------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def perf_counter(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _elapsed(probe: Any, monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> tuple[Any, float]:
    clock = _Clock()
    monkeypatch.setattr(probe.time, "perf_counter", clock.perf_counter)
    monkeypatch.setattr(probe.time, "sleep", clock.sleep)
    fake = FakeApi()
    rc = _main(probe, argv, fake)
    return rc, clock.now


def test_default_seconds_is_60_without_set_and_10_with_set(probe: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    rc, spent = _elapsed(probe, monkeypatch, [])
    assert rc == 0
    assert 60.0 <= spent < 60.5
    rc, spent = _elapsed(probe, monkeypatch, ["--set", "TriggerMode=enum:Off"])
    assert rc == 0
    assert 10.0 <= spent < 10.5


def test_set_seconds_upper_bound_30_accepted_30_5_refused(probe: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    rc, spent = _elapsed(probe, monkeypatch, ["30", "--set", "TriggerMode=enum:Off"])
    assert rc == 0
    assert 30.0 <= spent < 30.5
    clock = _Clock()
    monkeypatch.setattr(probe.time, "perf_counter", clock.perf_counter)
    fake = FakeApi()
    assert _main(probe, ["30.5", "--set", "TriggerMode=enum:Off"], fake) == 2
    assert fake.log == []


# -- g) прямой порядок восстановления --------------------------------------------------------------------------


def test_restore_order_follows_set_order(probe: Any) -> None:
    fake = FakeApi()
    assert _main(probe, TWO_NODES, fake) == 0
    assert fake.set_calls() == [
        ("set_enum_str", "TriggerMode", "Off"),
        ("set_enum_str", "RunningMode", "Raw"),
        ("set_enum", "TriggerMode", 1),
        ("set_enum", "RunningMode", 0),
    ]


# -- h) границы значений --set ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec",
    [
        "TriggerMode=enum:4294967296",
        "LightBrightness=int:9223372036854775808",
        "LightBrightness=int:-9223372036854775809",
        "Gain=float:1e39",
        "Gain=float:-1e39",
    ],
)
def test_out_of_range_values_exit_2_and_api_is_untouched(probe: Any, spec: str) -> None:
    fake = FakeApi()
    assert _main(probe, ["0.2", "--set", spec], fake) == 2
    assert fake.log == []


@pytest.mark.parametrize(
    ("spec", "setter", "value"),
    [
        ("TriggerMode=enum:4294967295", "set_enum", 4294967295),
        ("LightBrightness=int:9223372036854775807", "set_int", 9223372036854775807),
        ("LightBrightness=int:-9223372036854775808", "set_int", -9223372036854775808),
        ("Gain=float:3.4028235e38", "set_float", 3.4028235e38),
    ],
)
def test_boundary_values_are_accepted_and_reach_the_api(probe: Any, spec: str, setter: str, value: Any) -> None:
    fake = FakeApi()
    assert _main(probe, ["0.2", "--set", spec], fake) == 0
    assert fake.set_calls()[0][0] == setter
    assert fake.set_calls()[0][2] == value
    assert fake.log  # фейк реально вызван (страж к h)


# -- выбор прибора по --ip ----------------------------------------------------------------------------------------


class _TwoDevices(FakeApi):
    """Два прибора в порядке [.11, .10]; ``open`` отдаёт handle по ip (0x11 / 0x10)."""

    def enum_devices(self) -> list[Any]:
        self._rec("enum_devices")
        return [
            SimpleNamespace(ip="192.168.1.11", model="SENSOTEC", serial="S11", info=None),
            SimpleNamespace(ip="192.168.1.10", model="WBPF", serial="S10", info=None),
        ]

    def open(self, entry: Any) -> int:
        self._rec("open", entry)
        return 0x10 if entry.ip.endswith(".10") else 0x11


def _opens(fake: FakeApi) -> list[str]:
    return [a[0].ip for n, a in fake.log if n == "open"]


def test_ip_selects_second_device_for_params(probe: Any) -> None:
    fake = _TwoDevices()
    assert _main(probe, ["--params", "--ip", "192.168.1.10"], fake) == 0
    assert _opens(fake) == ["192.168.1.10"]
    assert all(a[0] == 0x10 for n, a in fake.log if n.startswith("get_"))
    assert fake.journal[-1] == "close"


def test_ip_selects_device_for_set_session_and_writes_only_to_its_handle(probe: Any) -> None:
    fake = _TwoDevices()
    assert _main(probe, ["0.2", "--set", "TriggerMode=enum:0", "--ip", "192.168.1.10"], fake) == 0
    assert _opens(fake) == ["192.168.1.10"]
    session = [a for n, a in fake.log if n not in ("enum_devices", "open")]
    assert session  # не вакуумно
    assert all(a[0] == 0x10 for a in session)
    assert [n for n, _, _ in fake.set_calls()] == ["set_enum", "set_enum"]


def test_guard_without_ip_first_device_is_opened(probe: Any) -> None:
    """Парный страж к выбору по --ip: без флага прежнее поведение (devices[0] = .11)."""
    fake = _TwoDevices()
    assert _main(probe, ["--params"], fake) == 0
    assert _opens(fake) == ["192.168.1.11"]


@pytest.mark.parametrize(
    "argv", [["--params"], ["0.2", "--set", "TriggerMode=enum:0"], ["0.2"]], ids=["params", "set", "live"]
)
def test_unknown_ip_exits_1_without_open_or_writes(
    probe: Any, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    fake = _TwoDevices()
    assert _main(probe, [*argv, "--ip", "192.168.1.99"], fake) == 1
    assert "open" not in fake.journal
    assert not [n for n in fake.journal if n.startswith("set_")]
    out = capsys.readouterr().out
    assert "НЕ НАЙДЕН" in out
    assert "192.168.1.11" in out
    assert "192.168.1.10" in out
    assert fake.log  # enum_devices реально вызван: тест не вакуумен


# -- --node: чтение произвольных узлов (только вместе с --params) -------------------------------------------------

_GETTERS = ("get_enum", "get_int", "get_float", "get_bool")
_SEVEN = ["ExposureTime", "Gain", "TriggerMode", "TriggerSource", "QualityEnable", "LightBrightness", "RunningMode"]


def _getter_calls(fake: FakeApi) -> list[tuple[str, str]]:
    return [(n, a[1]) for n, a in fake.log if n in _GETTERS]


def test_node_flags_read_exactly_the_named_nodes_in_command_line_order(
    probe: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeApi()
    assert _main(probe, ["--params", "--node", "FocusMode", "--node", "LightEnable"], fake) == 0
    assert _getter_calls(fake) == [(g, node) for node in ("FocusMode", "LightEnable") for g in _GETTERS]
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("NODE ")]
    assert [ln.split()[1] for ln in lines] == ["FocusMode", "LightEnable"]
    assert not [n for n in fake.journal if n.startswith("set_")]


def test_guard_params_without_node_still_reads_the_seven_nodes(probe: Any) -> None:
    fake = FakeApi()
    assert _main(probe, ["--params"], fake) == 0
    assert _getter_calls(fake) == [(g, node) for node in _SEVEN for g in _GETTERS]


@pytest.mark.parametrize(
    "argv",
    [
        ["--node", "FocusMode"],
        ["--params", "--set", "TriggerMode=enum:Off", "--node", "FocusMode"],
        ["--params", "--node", "Фокус"],
    ],
    ids=["without_params", "with_set", "non_ascii"],
)
def test_bad_node_usage_exits_2_and_api_is_untouched(probe: Any, argv: list[str]) -> None:
    fake = FakeApi()
    assert _main(probe, argv, fake) == 2
    assert fake.log == []
