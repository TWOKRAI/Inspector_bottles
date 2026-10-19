# -*- coding: utf-8 -*-
"""Hazard-тесты ``cam_cfg``: сбой посреди ``set``/``save`` не теряет исходное и не оставляет дескриптор открытым;
битый файл исходных и неверные аргументы отсекаются до открытия прибора; порядок и код возврата ``revert``.

Свой маленький фейк (не из ``test_cam_cfg.py``): setter и getter умеют бросать заданное исключение.
"""

from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import pytest

from Services.code_reader.tools import cam_cfg

IP = "10.0.0.1"
PERIOD = "TriggerSelfTriggerPeriod"


class NodeApi:
    """Фейк прибора: узлы -> (вид, значение); журнал вызовов; снимок orig-файла в момент каждого setter."""

    def __init__(self, orig_path: pathlib.Path):
        self.orig_path = orig_path
        self.state = {
            "TriggerMode": ["enum", 0],
            "TriggerSource": ["enum", 0],
            PERIOD: ["int", 300],
            "ExposureTime": ["float", 1000.0],
        }
        self.set_raises: BaseException | None = None  # любой setter бросает это
        self.fail_set: set[str] = set()  # setter этого узла отказывает
        self.readback_raises = False  # узел, в который уже пытались писать, больше не читается
        self.attempted: set[str] = set()
        self.opens = 0
        self.closes = 0
        self.setters: list[tuple] = []
        self.orig_at_set: list[tuple[str, dict | None]] = []

    def enum_devices(self):
        return [SimpleNamespace(ip=IP, model="ID3013")]

    def open(self, entry):
        self.opens += 1
        return 1

    def close(self, h):
        self.closes += 1

    def _read(self, node):
        if self.readback_raises and node in self.attempted:
            raise RuntimeError("readback lost")
        return self.state[node][1]

    def get_int(self, h, node):
        return {"cur": self._read(node), "min": 0, "max": 9999, "inc": 1}

    def get_float(self, h, node):
        return {"cur": self._read(node), "min": 0.0, "max": 1e6}

    def get_enum(self, h, node):
        return {"cur": self._read(node), "supported": [0, 1, 7]}

    def get_bool(self, h, node):
        return self._read(node)

    def _write(self, method, node, value, stored=None):
        self.setters.append((method, node, value))
        self.attempted.add(node)
        text = self.orig_path.read_text(encoding="utf-8") if self.orig_path.exists() else None
        self.orig_at_set.append((node, json.loads(text) if text else None))
        if self.set_raises is not None:
            raise self.set_raises
        if node in self.fail_set:
            raise RuntimeError("node is locked")
        self.state[node][1] = value if stored is None else stored

    def set_int(self, h, node, value):
        self._write("set_int", node, value)

    def set_float(self, h, node, value):
        self._write("set_float", node, value)

    def set_enum(self, h, node, value):
        self._write("set_enum", node, value)

    def set_enum_str(self, h, node, value):
        self._write("set_enum_str", node, value, stored={"Off": 0, "On": 1, "SelfTrigger": 7}[value])

    def set_bool(self, h, node, value):
        self._write("set_bool", node, value)


@pytest.fixture
def orig(tmp_path):
    return tmp_path / "cam_orig.json"


@pytest.fixture
def api(orig):
    return NodeApi(orig)


def run(argv, api, orig):
    """Код выхода: возвращённый int или код SystemExit (строка -> 1)."""
    try:
        return cam_cfg.main(argv, api=api, orig_path=orig)
    except SystemExit as exc:
        return 0 if exc.code is None else exc.code if isinstance(exc.code, int) else 1


def write_orig(orig, per_ip):
    orig.write_text(json.dumps({IP: per_ip}, indent=2), encoding="utf-8")


# ============================================================ сбой посреди set


def test_keyboard_interrupt_in_setter_keeps_original_on_disk_and_closes_once(api, orig):
    api.set_raises = KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        cam_cfg.main(["set", IP, f"{PERIOD}:int=500"], api=api, orig_path=orig)

    assert json.loads(orig.read_text(encoding="utf-8")) == {IP: {PERIOD: {"value": 300, "type": "int"}}}
    assert api.closes == 1


def test_readback_failure_prints_line_without_crash_and_closes_once(api, orig, capsys):
    api.readback_raises = True

    rc = cam_cfg.main(["set", IP, f"{PERIOD}:int=500"], api=api, orig_path=orig)

    assert rc == 0
    assert api.state[PERIOD][1] == 500
    assert f"SET {PERIOD}: было=300 записано=500 OK прочитано=ERR readback lost" in capsys.readouterr().out
    assert api.closes == 1


def test_set_refusal_with_unreadable_readback_still_returns_one_and_closes_once(api, orig, capsys):
    api.fail_set.add(PERIOD)
    api.readback_raises = True

    rc = cam_cfg.main(["set", IP, f"{PERIOD}:int=500"], api=api, orig_path=orig)

    assert rc == 1
    assert "ОТКАЗ node is locked прочитано=ERR readback lost" in capsys.readouterr().out
    assert api.closes == 1


def test_refused_node_original_is_on_disk_at_moment_of_its_setter(api, orig):
    api.fail_set.add(PERIOD)

    rc = run(["set", IP, "ExposureTime:float=2000.0", f"{PERIOD}:int=500"], api, orig)

    assert rc == 1
    node, on_disk = api.orig_at_set[-1]
    assert node == PERIOD
    assert on_disk[IP][PERIOD] == {"value": 300, "type": "int"}
    assert on_disk[IP]["ExposureTime"] == {"value": 1000.0, "type": "float"}


# ============================================================ битый файл исходных


@pytest.mark.parametrize(
    "cmd", [["set", IP, f"{PERIOD}:int=500"], ["revert", IP], ["selftrigger", IP], ["period", IP, "500"]]
)
@pytest.mark.parametrize(
    "text", ['{"10.0.0.1": {"TriggerMo', "[]", '{"10.0.0.1": 5}', ""], ids=["truncated", "list", "ip-not-dict", "empty"]
)
def test_broken_orig_file_exits_before_device_is_touched(api, orig, cmd, text):
    orig.write_text(text, encoding="utf-8")

    rc = run(cmd, api, orig)

    assert rc != 0
    assert (api.opens, api.closes, api.setters) == (0, 0, [])
    assert orig.read_text(encoding="utf-8") == text  # битый файл не затёрт


def test_broken_orig_file_message_is_clear(api, orig):
    orig.write_text('{"10.0.0.1": {"TriggerMo', encoding="utf-8")

    with pytest.raises(SystemExit) as info:
        cam_cfg.main(["set", IP, f"{PERIOD}:int=500"], api=api, orig_path=orig)

    assert "повреждён" in str(info.value.code)


# ============================================================ атомарный save


def test_save_failure_mid_write_keeps_previous_file_valid(tmp_path, monkeypatch):
    target = tmp_path / "cam_orig.json"
    cam_cfg.save({IP: {PERIOD: {"value": 300, "type": "int"}}}, target)

    def half_write(self, text, encoding=None):
        pathlib.Path.write_bytes(self, text.encode("utf-8")[:10])  # диск кончился на середине файла
        raise OSError("disk full")

    monkeypatch.setattr(pathlib.Path, "write_text", half_write)
    with pytest.raises(OSError, match="disk full"):
        cam_cfg.save({IP: {PERIOD: {"value": 999, "type": "int"}}}, target)
    monkeypatch.undo()

    assert json.loads(target.read_text(encoding="utf-8")) == {IP: {PERIOD: {"value": 300, "type": "int"}}}
    assert [p.name for p in tmp_path.iterdir()] == ["cam_orig.json"]  # временный файл убран


def test_save_failure_on_second_node_keeps_first_original_and_skips_its_setter(api, orig, monkeypatch):
    real_save = cam_cfg.save
    calls = []

    def flaky_save(data, path):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk full")
        real_save(data, path)

    monkeypatch.setattr(cam_cfg, "save", flaky_save)
    with pytest.raises(OSError, match="disk full"):
        cam_cfg.main(["set", IP, "ExposureTime:float=2000.0", f"{PERIOD}:int=500"], api=api, orig_path=orig)

    assert json.loads(orig.read_text(encoding="utf-8")) == {IP: {"ExposureTime": {"value": 1000.0, "type": "float"}}}
    assert [s[1] for s in api.setters] == ["ExposureTime"]  # setter узла без сохранённого исходного не вызван
    assert api.closes == 1


# ============================================================ порядок и код revert


def test_legacy_entries_revert_period_source_mode_regardless_of_file_order(api, orig):
    write_orig(orig, {PERIOD: 300, "TriggerMode": 0, "TriggerSource": 0})

    rc = run(["revert", IP], api, orig)

    assert rc == 0
    assert [s[1] for s in api.setters] == [PERIOD, "TriggerSource", "TriggerMode"]


def test_modern_entries_revert_before_legacy_ones(api, orig):
    write_orig(
        orig,
        {PERIOD: 300, "TriggerMode": 0, "ExposureTime": {"value": 1000.0, "type": "float"}, "TriggerSource": 0},
    )

    run(["revert", IP], api, orig)

    assert [s[1] for s in api.setters] == ["ExposureTime", PERIOD, "TriggerSource", "TriggerMode"]


def test_revert_returns_one_when_a_node_is_not_returned(api, orig, capsys):
    write_orig(orig, {"ExposureTime": {"value": 1000.0, "type": "float"}, PERIOD: {"value": 300, "type": "int"}})
    api.fail_set.add(PERIOD)

    rc = run(["revert", IP], api, orig)

    assert rc == 1
    assert any(line.startswith("НЕ ВОЗВРАЩЁН " + PERIOD) for line in capsys.readouterr().out.splitlines())
    assert [s[1] for s in api.setters] == [PERIOD, "ExposureTime"]  # отказ не остановил остальных
    assert api.closes == 1


def test_revert_with_nothing_saved_returns_one_with_explicit_line(api, orig, capsys):
    rc = run(["revert", IP], api, orig)

    assert rc == 1
    assert f"нет сохранённых исходных для {IP}" in capsys.readouterr().out.splitlines()
    assert api.setters == []
    assert api.closes == api.opens  # прибор не остаётся открытым


def test_revert_with_other_ip_only_saved_returns_one(api, orig, capsys):
    orig.write_text(json.dumps({"10.0.0.2": {PERIOD: 300}}), encoding="utf-8")

    rc = run(["revert", IP], api, orig)

    assert rc == 1
    assert f"нет сохранённых исходных для {IP}" in capsys.readouterr().out
    assert api.setters == []


def test_revert_skips_malformed_entry_and_continues(api, orig, capsys):
    write_orig(orig, {"ExposureTime": {"type": "float"}, PERIOD: {"value": 300, "type": "int"}})
    api.state[PERIOD][1] = 20

    rc = run(["revert", IP], api, orig)

    assert rc == 0
    assert "SKIP ExposureTime (битая запись)" in capsys.readouterr().out.splitlines()
    assert api.state[PERIOD][1] == 300
    assert [s[1] for s in api.setters] == [PERIOD]


# ============================================================ разбор значений до открытия прибора


@pytest.mark.parametrize(
    "arg",
    [
        "ExposureTime:float=nan",
        "ExposureTime:float=inf",
        "ExposureTime:float=-inf",
        "ExposureTime:float=1e999",
        "ExposureTime:float=1_0",
        "ExposureTime:float=",
        "TriggerSource:enum=",
        "TriggerSource:enum=   ",
        "TriggerMode:enum=-1",
        "TriggerMode:enum=4294967296",
        "TriggerMode:enum=1_0",
        "TriggerMode:enum=+1",
        f"{PERIOD}:int=1_0",
        f"{PERIOD}:int=+5",
        f"{PERIOD}:int=١٢",
        f"{PERIOD}:int=9223372036854775808",
        f"{PERIOD}:int=1.5",
        f"{PERIOD}:int=",
        "LightEnable:bool=yes",
    ],
)
def test_bad_value_exits_before_opening_device(api, orig, arg):
    rc = run(["set", IP, f"{PERIOD}:int=500", arg], api, orig)  # первый узел верный, второй нет

    assert rc != 0
    assert (api.opens, api.setters) == (0, [])
    assert not orig.exists()


def test_integer_with_spaces_is_accepted(api, orig):
    rc = run(["set", IP, f"{PERIOD}:int= 5 "], api, orig)

    assert rc == 0
    assert api.setters == [("set_int", PERIOD, 5)]


def test_enum_upper_bound_is_accepted(api, orig):
    run(["set", IP, "TriggerMode:enum=4294967295"], api, orig)

    assert api.setters == [("set_enum", "TriggerMode", 4294967295)]


@pytest.mark.parametrize(
    "argv",
    [
        ["frobnicate", IP],
        ["get", IP],
        ["set", IP],
        ["period", IP],
        ["period", IP, "abc"],
        ["period", IP, "1.5"],
        ["period", IP, "500", "600"],
    ],
    ids=["unknown-cmd", "get-empty", "set-empty", "period-missing", "period-abc", "period-float", "period-two"],
)
def test_bad_command_line_exits_before_opening_device(api, orig, argv):
    rc = run(argv, api, orig)

    assert rc != 0
    assert (api.opens, api.setters) == (0, [])


# ============================================================ selftrigger не трогает чужие сохранённые узлы


def test_failed_selftrigger_rolls_back_only_trigger_nodes(api, orig):
    run(["set", IP, "ExposureTime:float=2000.0"], api, orig)
    api.setters.clear()
    api.fail_set.add("TriggerSource")

    with pytest.raises(RuntimeError, match="node is locked"):
        cam_cfg.main(["selftrigger", IP], api=api, orig_path=orig)

    assert api.state["ExposureTime"][1] == 2000.0
    assert "ExposureTime" not in [s[1] for s in api.setters]
    assert api.state["TriggerMode"][1] == 0  # свои узлы возвращены
    assert api.closes == 2  # set + selftrigger, по разу


def test_selftrigger_uses_value_of_dict_entry_written_by_set(api, orig, capsys):
    run(["set", IP, "TriggerMode:enum=1"], api, orig)  # исходное 0 сохранено как dict
    capsys.readouterr()

    rc = run(["selftrigger", IP], api, orig)

    out = capsys.readouterr().out
    assert rc == 0
    assert "ORIG TriggerMode = 0" in out.splitlines()
    assert api.state["TriggerSource"][1] == 7
    assert json.loads(orig.read_text(encoding="utf-8"))[IP]["TriggerMode"] == {"value": 0, "type": "enum"}
