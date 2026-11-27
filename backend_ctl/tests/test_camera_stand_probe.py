# -*- coding: utf-8 -*-
"""Приёмочный скрипт стенда камер (C6.1): выход 0 только по положительным наблюдениям.

Подменён только транспорт: ``FakeDriver`` — настоящий ``BackendDriver`` без сокета (``connect`` и
``request`` переопределены), так что ``send_command``/``introspect_telemetry``/``telemetry_snapshot``
настоящие. Ответы — литералы в форме проводов: ``state.get`` (``state_store_manager.py:334-345``) и
``introspect.telemetry`` в конверте ``{"success", "result"}``.
"""

from __future__ import annotations

import copy
import json

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.probes import camera_stand_probe as probe

_DETECT = "processes.camera_0.state.plugins"
_PLUGIN = "processes.camera_0.state.plugins.camera_device"

# --- записанные ответы ----------------------------------------------------


def block(state: str = "grabbing", link: str = "up", outages: int = 0) -> dict:
    return {
        "state": state,
        "device": {"kind": "serial", "value": "SIM-0001", "name": "sim"},
        "device_held": True,
        "profile": "run",
        "params": {},
        "params_status": {},
        "param_errors": {},
        "last_error": None,
        "capabilities": [],
        "identity": {"serial": "SIM-0001", "model": "SimCam", "ip": None, "width": 640, "height": 480},
        "stream": {"pixel_format": "mono8", "width": 640, "height": 480},
        "link": {
            "state": link,
            "reconnecting": False,
            "outages": outages,
            "attempts": 0,
            "last_outage_s": None,
            "lost_for_s": None,
        },
        "frame_watch": {},
    }


def metrics(frames: int, fps: float = 25.0, dropped: int = 0, errors: int = 0) -> dict:
    return {
        "fps": fps,
        "frames": frames,
        "errors": errors,
        "dropped": dropped,
        "overwritten": 0,
        "pending": 0,
        "incomplete": 3,
        "lost_packets": 4,
        "lost_frames": 5,
        "trigger_lost": 0,
        "trigger_missed": 6,
        "param_errors_count": 0,
    }


def state_ok(value: dict) -> dict:
    return {"success": True, "result": {"status": "ok", "request_id": "r1", "value": value}}


def state_error(path: str) -> dict:
    return {
        "success": False,
        "result": {"status": "error", "request_id": "r1", "error": f"Путь не существует: '{path}'"},
    }


def telemetry(plugins: dict) -> dict:
    return {
        "success": True,
        "result": {
            "success": True,
            "process": "camera_0",
            "gate_active": True,
            "levels": {"workers": {}, "state": {"plugins": plugins}},
            "snapshot_ts": 1000.0,
        },
    }


LEVELS_NONE = {"success": True, "result": {"success": True, "process": "camera_0", "levels": None}}
TIMEOUT = {"success": False, "error": "timeout", "request_id": "r1"}
NOT_CONNECTED = {"success": False, "error": "not connected"}


def tick(frames: int, *, blk: dict | None = None, **kw) -> tuple[dict, dict]:
    """Один такт: (ответ state.get, ответ introspect.telemetry) одного плагина ``camera_device``."""
    return state_ok(blk or block()), telemetry({"camera_device": metrics(frames, **kw)})


# --- подмена транспорта ----------------------------------------------------


class FakeDriver(BackendDriver):
    """``BackendDriver``, чей транспорт отдаёт заранее записанные ответы по очереди."""

    def __init__(self, replies: dict, *, connect_error: Exception | None = None, fallback=None) -> None:
        super().__init__(port=8765)
        self.replies = {key: list(queue) for key, queue in replies.items()}
        self.connect_error = connect_error
        self.fallback = fallback
        self.connected = False
        self.asked: list[str] = []

    def connect(self, timeout: float = 5.0) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True

    def request(self, message: dict, timeout: float | None = None) -> dict:
        if message["command"] == "state.get":
            assert message["targets"] == ["ProcessManager"]
            key = message["data"]["path"]
        else:
            assert message["command"] == "introspect.telemetry"
            key = f"telemetry:{message['targets'][0]}"
        self.asked.append(key)
        queue = self.replies.get(key)
        if queue:
            reply = queue.pop(0)
        elif self.fallback is not None:
            reply = self.fallback
        else:
            reply = TIMEOUT if key.startswith("telemetry:") else state_error(key)
        if isinstance(reply, BaseException):
            raise reply
        return copy.deepcopy(reply)

    def left(self) -> dict:
        return {key: len(queue) for key, queue in self.replies.items() if queue}


def stand(ticks: list[tuple[dict, dict]], *, detect: list[dict] | None = None) -> FakeDriver:
    """Процесс ``camera_0`` с плагином ``camera_device``; ``detect`` — ответы автовыбора (начало, конец)."""
    found = state_ok({"camera_device": block()})
    return FakeDriver(
        {
            _DETECT: detect or [found, found],
            _PLUGIN: [state for state, _ in ticks],
            "telemetry:camera_0": [levels for _, levels in ticks],
        }
    )


def run(monkeypatch, tmp_path, fake: FakeDriver, ticks: int, *extra: str, processes: str = "camera_0"):
    monkeypatch.setattr(probe, "BackendDriver", lambda port=None: fake)
    out = tmp_path / "stand.json"
    argv = ["--port", "8765", "--processes", processes, "--out", str(out)]
    argv += ["--seconds", str((ticks - 1) * 0.01), "--interval", "0.01", *extra]
    code = probe.main(argv)
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["exit_code"] == code
    return code, report


def row(report: dict, plugin: str = "camera_device", process: str = "camera_0") -> dict:
    return report["processes"][process]["plugins"][plugin]


# --- приёмка по брифу ------------------------------------------------------


def test_table_from_recorded_answers(monkeypatch, tmp_path, capsys):
    fake = stand([tick(100, fps=25.0), tick(220, fps=24.0)])

    code, report = run(monkeypatch, tmp_path, fake, 2)

    assert code == 0
    assert report["errors"] == []
    assert row(report) == {
        "failures": [],
        "failed_polls": 0,
        "samples": 2,
        "fps_mean": 24.5,
        "fps_min": 24.0,
        "frames": 220,
        "dropped": 0,
        "errors": 0,
        "param_errors_count": 0,
        "lost_frames": 5,
        "incomplete": 3,
        "lost_packets": 4,
        "trigger_missed": 6,
        "state": "grabbing",
        "link_state": "up",
        "link_outages": 0,
        "link_attempts": 0,
        "identity_serial": "SIM-0001",
    }
    assert fake.left() == {}  # прочитаны все записанные ответы: оба такта и оба автовыбора
    lines = [line for line in capsys.readouterr().out.splitlines() if "camera_device" in line]
    assert len(lines) == 1
    assert lines[0].split()[:2] == ["camera_0", "camera_device"]
    assert "220" in lines[0].split()
    assert lines[0].split()[-1] == "ok"


_NO_ERRORS_METRIC = metrics(220)
del _NO_ERRORS_METRIC["errors"]

# id -> (такты, ожидаемый код причины, samples, failed_polls)
_FAILING = {
    "dropped": ([tick(100), tick(220, dropped=1)], "dropped", 2, 0),
    "link_lost": ([tick(100), tick(220, blk=block(link="lost"))], "link_lost", 2, 0),
    "not_grabbing": ([tick(100), tick(220, blk=block(state="error"))], "state_not_grabbing", 2, 0),
    "errors_grew": ([tick(100, errors=1), tick(220, errors=2)], "errors_grew", 2, 0),
    "missing_metric": (
        [tick(100), (state_ok(block()), telemetry({"camera_device": _NO_ERRORS_METRIC}))],
        "missing_metric:errors",
        2,
        0,
    ),
    "no_samples": ([(state_ok(block()), telemetry({}))] * 2, "no_samples", 0, 2),
    "one_sample": ([tick(100)], "too_few_samples", 1, 0),
    "frames_zero": ([tick(0), tick(0)], "frames_stalled", 2, 0),
    "frames_stalled_silent": ([tick(100), tick(100, blk=block(link="silent"))], "frames_stalled", 2, 0),
    "frames_reset": ([tick(100), tick(200), tick(50), tick(80)], "frames_reset", 4, 0),
    "timeout_last_poll": ([tick(100), tick(220), (state_ok(block()), TIMEOUT)], "failed_poll", 2, 1),
    "state_error": ([tick(100), tick(220), (state_error(_PLUGIN), tick(340)[1])], "failed_poll", 2, 1),
    "levels_none": ([tick(100), tick(220), (state_ok(block()), LEVELS_NONE)], "failed_poll", 2, 1),
}


@pytest.mark.parametrize("case", _FAILING)
def test_exit_1_condition(monkeypatch, tmp_path, case):
    ticks, reason, samples, failed_polls = _FAILING[case]

    code, report = run(monkeypatch, tmp_path, stand(ticks), len(ticks))

    assert code == 1
    assert reason in row(report)["failures"]
    assert row(report)["samples"] == samples
    assert row(report)["failed_polls"] == failed_polls


def test_outage_reported_not_failing(monkeypatch, tmp_path):
    after = block(outages=2)
    fake = stand([tick(100, blk=after), tick(220, blk=after)])

    code, report = run(monkeypatch, tmp_path, fake, 2)

    assert code == 0
    assert row(report)["link_outages"] == 2
    assert row(report)["failures"] == []


def test_plugins_autodetected_by_link_block(monkeypatch, tmp_path):
    no_link = block()
    del no_link["link"]
    no_held = block()
    del no_held["device_held"]
    found = state_ok({"camera_device": block(), "no_link": no_link, "no_held": no_held, "stats": {"count": 1}})
    fake = stand([tick(100), tick(220)], detect=[found, found])

    code, report = run(monkeypatch, tmp_path, fake, 2)

    assert code == 0
    assert list(report["processes"]["camera_0"]["plugins"]) == ["camera_device"]
    assert not [key for key in fake.asked if key.endswith((".no_link", ".no_held", ".stats"))]


def test_no_camera_plugin_gives_exit_1(monkeypatch, tmp_path):
    found = state_ok({"stats": {"count": 1}})
    fake = FakeDriver({_DETECT: [found, found]})

    code, report = run(monkeypatch, tmp_path, fake, 2)

    assert code == 1
    assert report["errors"] == ["no_camera_plugin:camera_0"]


def test_requested_plugin_missing_gives_exit_1(monkeypatch, tmp_path):
    fake = stand([tick(100), tick(220)])

    code, report = run(monkeypatch, tmp_path, fake, 2, "--plugins", "camera_device,hikvision")

    assert code == 1
    assert report["errors"] == ["plugin_not_found:hikvision"]
    assert row(report)["failures"] == []  # красный — только из-за ненайденного


# --- опасные пути автора: «ничего не увидел» не должно давать 0 -------------


@pytest.mark.parametrize(
    "argv",
    [
        ["--processes", ""],
        ["--processes", " , "],
        ["--processes", "camera_0", "--plugins", ""],
        ["--processes", "camera_0", "--interval", "0"],
        ["--processes", "camera_0", "--interval", "nan"],
        ["--processes", "camera_0", "--seconds", "-1"],
        ["--processes", "camera_0", "--seconds", "inf"],
    ],
)
def test_bad_arguments_are_not_green(monkeypatch, tmp_path, argv):
    fake = FakeDriver({})
    monkeypatch.setattr(probe, "BackendDriver", lambda port=None: fake)

    with pytest.raises(SystemExit) as stop:
        probe.main([*argv, "--out", str(tmp_path / "stand.json")])

    assert stop.value.code == 2
    assert fake.connected is False


def test_process_that_does_not_exist(monkeypatch, tmp_path):
    fake = stand([tick(100), tick(220)])

    code, report = run(monkeypatch, tmp_path, fake, 2, processes="camera_0,nope")

    assert code == 1
    assert report["errors"] == ["detect_failed:nope", "no_camera_plugin:nope"]
    assert row(report)["failures"] == []  # живой сосед не прикрывает отсутствующий процесс


def test_connect_failure_replaces_stale_green_report(monkeypatch, tmp_path):
    (tmp_path / "stand.json").write_text('{"exit_code": 0}', encoding="utf-8")
    fake = FakeDriver({}, connect_error=ConnectionRefusedError("refused"))

    code, report = run(monkeypatch, tmp_path, fake, 2)

    assert code == 1
    assert report["processes"] == {}
    assert report["errors"] == ["driver:ConnectionRefusedError: refused"]


def test_driver_exception_mid_run_is_a_failed_poll(monkeypatch, tmp_path):
    ticks = [tick(100), tick(220), (state_ok(block()), ConnectionError("reset"))]

    code, report = run(monkeypatch, tmp_path, stand(ticks), 3)

    assert code == 1
    assert row(report)["failures"] == ["failed_poll"]
    assert row(report)["samples"] == 2


@pytest.mark.parametrize("answer", [NOT_CONNECTED, TIMEOUT, RuntimeError("boom"), {}, None])
def test_nothing_but_failures_from_driver(monkeypatch, tmp_path, answer):
    fake = FakeDriver({}, fallback=answer if answer is not None else {"success": True, "result": {}})

    code, report = run(monkeypatch, tmp_path, fake, 3)

    assert code == 1
    assert "no_camera_plugin:camera_0" in report["errors"]


def test_seconds_shorter_than_interval_is_one_sample(monkeypatch, tmp_path):
    fake = stand([tick(100)])
    monkeypatch.setattr(probe, "BackendDriver", lambda port=None: fake)
    out = tmp_path / "stand.json"

    code = probe.main(["--processes", "camera_0", "--seconds", "1", "--interval", "5", "--out", str(out)])

    assert code == 1
    assert row(json.loads(out.read_text(encoding="utf-8")))["failures"] == ["too_few_samples"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "0", None, False])
def test_non_number_dropped_is_a_missing_metric(monkeypatch, tmp_path, bad):
    code, report = run(monkeypatch, tmp_path, stand([tick(100), tick(220, dropped=bad)]), 2)

    assert code == 1
    assert row(report)["failures"] == ["missing_metric:dropped"]


def test_frames_missing_on_previous_poll_is_no_proof_of_advance(monkeypatch, tmp_path):
    first = metrics(100)
    del first["frames"]
    ticks = [(state_ok(block()), telemetry({"camera_device": first})), tick(220)]

    code, report = run(monkeypatch, tmp_path, stand(ticks), 2)

    assert code == 1
    assert row(report)["failures"] == ["frames_stalled"]


def test_frames_reset_seen_across_a_poll_without_frames(monkeypatch, tmp_path):
    gap = metrics(0)
    del gap["frames"]
    ticks = [tick(200), (state_ok(block()), telemetry({"camera_device": gap})), tick(50), tick(80)]

    code, report = run(monkeypatch, tmp_path, stand(ticks), 4)

    assert code == 1
    assert row(report)["failures"] == ["frames_reset"]


def test_plugin_that_appears_late_is_not_silently_skipped(monkeypatch, tmp_path):
    start = state_ok({"camera_device": block()})
    end = state_ok({"camera_device": block(), "hikvision": block()})
    fake = stand([tick(100), tick(220)], detect=[start, end])

    code, report = run(monkeypatch, tmp_path, fake, 2)

    assert code == 1
    assert row(report, "hikvision")["failures"] == ["no_samples"]
    assert row(report)["failures"] == []


def test_failed_final_detection_is_not_green(monkeypatch, tmp_path):
    fake = stand([tick(100), tick(220)], detect=[state_ok({"camera_device": block()}), TIMEOUT])

    code, report = run(monkeypatch, tmp_path, fake, 2)

    assert code == 1
    assert report["errors"] == ["detect_failed:camera_0"]


# --- повтор флага и прерванный прогон --------------------------------------


def test_repeated_processes_flag_checks_every_process(monkeypatch, tmp_path):
    fake = stand([tick(100), tick(220)])

    code, report = run(monkeypatch, tmp_path, fake, 2, "--processes", "camera_0", processes="nope")

    assert code == 1
    assert "no_camera_plugin:nope" in report["errors"]
    assert row(report)["failures"] == []


def test_repeated_plugins_flag_checks_every_plugin(monkeypatch, tmp_path):
    found = state_ok({"camera_device": block(), "hikvision": block(state="error")})
    levels = [telemetry({"camera_device": metrics(n), "hikvision": metrics(n)}) for n in (100, 220)]
    fake = FakeDriver(
        {
            _DETECT: [found, found],
            _PLUGIN: [state_ok(block())] * 2,
            f"{_DETECT}.hikvision": [state_ok(block(state="error"))] * 2,
            "telemetry:camera_0": levels,
        }
    )

    code, report = run(monkeypatch, tmp_path, fake, 2, "--plugins", "hikvision", "--plugins", "camera_device")

    assert code == 1
    assert row(report, "hikvision")["failures"] == ["state_not_grabbing"]
    assert row(report)["failures"] == []


@pytest.mark.parametrize(
    "processes, extra",
    [
        ("camera_0,camera_0", ()),
        ("camera_0", ("--processes", "camera_0")),
        ("camera_0", ("--plugins", "camera_device", "--plugins", "camera_device")),
    ],
    ids=["comma_process", "repeated_process", "repeated_plugin"],
)
def test_duplicate_name_is_polled_once_per_tick(monkeypatch, tmp_path, processes, extra):
    # Живой стенд на повторный вопрос в том же такте отвечает тем же уровнем: 100, 220, 220, 220.
    # Опроси скрипт дубль дважды — последние два числа равны, то есть ложный frames_stalled.
    found = state_ok({"camera_device": block()})
    fake = FakeDriver(
        {
            _DETECT: [found] * 4,
            _PLUGIN: [state_ok(block())] * 4,
            "telemetry:camera_0": [tick(n)[1] for n in (100, 220, 220, 220)],
        }
    )

    code, report = run(monkeypatch, tmp_path, fake, 2, *extra, processes=processes)

    assert row(report)["failures"] == []
    assert code == 0
    assert fake.asked.count(_PLUGIN) == 2
    assert fake.asked.count("telemetry:camera_0") == 2


def test_interrupted_run_leaves_no_previous_report(monkeypatch, tmp_path):
    out = tmp_path / "stand.json"
    out.write_text('{"exit_code": 0}', encoding="utf-8")
    fake = FakeDriver({}, fallback=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        run(monkeypatch, tmp_path, fake, 2)

    assert not out.exists()
