"""Тесты сборщика ``scripts/wire_audit/collect.py`` на фейке клиента ``backend_ctl`` (Task 3b).

Фейком подменён только клиент и (в большинстве тестов) время; файлы пишет настоящий писатель в ``tmp_path``.
Тесты, которые могут зависнуть, гоняют ``run`` в daemon-потоке с дедлайном ``join``.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from scripts.wire_audit import collect

_T0 = datetime(2026, 11, 22, 13, 0, 0).timestamp()  # локальное время: формат не зависит от пояса
_TIME_RE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}$")
_DEADLINE_S = 10.0

LAYOUT_REPLY = {
    "result": {
        "registers": {
            "word_layout": {
                "first_x": 320.0,
                "first_y": -440.0,
                "pitch_mm": 0.0,
                "disk_radius_mm": 55.0,
                "line_angle_deg": 90.0,
                "place_z_mm": -132.0,
                "pick_z_mm": -132.0,
                "angle_zero_deg": 0.0,
                "angle_invert": False,
                "use_pitch": True,
                "word_gap_slots": 0,
                "jobs_emitted": 7,
            }
        }
    }
}


def passport(letter: str, angle: float, lateral: float) -> dict:
    return {"class_name": letter, "angle_deg": angle, "lateral_px": lateral, "spawn_encoder": 5}


def objects_reply(objects: dict | None) -> dict:
    if objects is None:
        return {"result": {"status": "error", "message": "no such path"}}
    return {"result": {"status": "ok", "value": objects}}


def journal_reply(rows: list[tuple]) -> dict:
    """Строка кольца: ``(t, side, text)`` или ``(t, side, text, n)`` — склеенная строка с счётчиком ``n``."""
    wire = [
        {"t": row[0], "side": row[1], "text": row[2], "tag": "", "n": row[3] if len(row) > 3 else 1} for row in rows
    ]
    return {"result": {"status": "ok", "counters": {}, "recent": [], "wire": wire}}


class FakeClient:
    """Клиент ``backend_ctl``: ответы по сценарию (последний повторяется), запись всех вызовов."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.objects: list[Any] = [objects_reply({})]
        self.journal: list[Any] = [journal_reply([])]
        self.layout: Any = LAYOUT_REPLY
        self.connect_error: Exception | None = None
        self.closed = False
        self.on_journal: Callable[[int], None] | None = None
        self._n_objects = 0
        self._n_journal = 0

    def connect(self, timeout: float = 5.0) -> None:
        if self.connect_error is not None:
            raise self.connect_error

    def close(self) -> None:
        self.closed = True

    @staticmethod
    def _step(script: list[Any], index: int) -> Any:
        item = script[min(index, len(script) - 1)]
        if isinstance(item, BaseException):
            raise item
        return item

    def send_command(self, target: str, command: str, args: dict | None = None, *, timeout: float | None = None):
        self.calls.append((target, command, args))
        if command == "state.get":
            self._n_objects += 1
            return self._step(self.objects, self._n_objects - 1)
        if command == "sim_robot.journal":
            self._n_journal += 1
            if self.on_journal is not None:
                self.on_journal(self._n_journal)
            return self._step(self.journal, self._n_journal - 1)
        raise AssertionError(f"неожиданная команда сборщика: {target}.{command}")

    def introspect_registers(self, process: str, **kw: Any) -> Any:
        self.calls.append((process, "introspect.registers", None))
        return self.layout


class FakeTime:
    """Часы и сон: сон двигает время; хук получает номер вызова сна (для STOP посреди сна)."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps = 0
        self.hook: Callable[[int], None] | None = None

    def clock(self) -> float:
        return self.now

    def wall(self) -> float:
        return _T0 + self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.now += seconds
        if self.hook is not None:
            self.hook(self.sleeps)


class Rig:
    """Стенд теста: два фейка клиента, фейковое время, каталог; ``go`` гонит ``run`` в daemon-потоке."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.proto = FakeClient()
        self.sim = FakeClient()
        self.time = FakeTime()
        self.err = StringIO()
        self.rc: int | None = None

    def stop_after_journal_polls(self, polls: int) -> None:
        """STOP-файл появляется на ``polls``-м опросе журнала — то есть посреди сна после него."""

        def on_journal(n: int) -> None:
            if n >= polls:
                (self.out_dir / "STOP").write_text("", encoding="utf-8")

        self.sim.on_journal = on_journal

    def go(self, extra: list[str] | None = None) -> int:
        argv = ["--proto-port", "8765", "--sim-port", "8766", "--out-dir", str(self.out_dir), *(extra or [])]

        def target() -> None:
            self.rc = collect.run(
                argv,
                client_factory=lambda port: self.proto if port == 8765 else self.sim,
                clock=self.time.clock,
                sleep=self.time.sleep,
                wall=self.time.wall,
                err=self.err,
            )

        worker = threading.Thread(target=target, daemon=True)
        worker.start()
        worker.join(_DEADLINE_S)
        assert not worker.is_alive(), "сборщик завис: STOP или цикл не сработал"
        assert self.rc is not None
        return self.rc

    def jsonl(self, name: str) -> list[dict]:
        path = self.out_dir / name
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def meta(self) -> dict:
        return json.loads((self.out_dir / "meta.json").read_text(encoding="utf-8"))


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path / "out")


# --- паспорта ---------------------------------------------------------------------------------------------------------


def test_passport_written_once_and_kept_after_removal(rig: Rig) -> None:
    """o1 виден три опроса подряд, потом «взят» (пропал из sim.objects), o2 появился: две записи, не пять."""
    o1, o2 = passport("Е", 30.0, -12.5), passport("Р", 91.9, 20.0)
    rig.sim.objects = [
        objects_reply({"o1": o1}),
        objects_reply({"o1": o1}),
        objects_reply({"o1": o1}),
        objects_reply({}),
        objects_reply({"o2": o2}),
        objects_reply({"o1": o1, "o2": o2}),  # o1 вернулся (повтор id) — всё равно не пишется второй раз
    ]
    rig.stop_after_journal_polls(6)

    assert rig.go() == 0

    rows = rig.jsonl("sim_objects.jsonl")
    assert [(r["object_id"], r["class_name"], r["angle_deg"], r["lateral_px"]) for r in rows] == [
        ("o1", "Е", 30.0, -12.5),
        ("o2", "Р", 91.9, 20.0),
    ]
    assert all(_TIME_RE.match(r["t"]) for r in rows)
    assert rig.meta()["objects"] == 2


def test_state_get_missing_key_is_not_an_error(rig: Rig) -> None:
    """``sim.objects`` до первого спавна отвечает status error: паспортов нет, ошибкой это не считается."""
    rig.sim.objects = [objects_reply(None)]
    rig.stop_after_journal_polls(3)

    assert rig.go() == 0

    assert (rig.out_dir / "sim_objects.jsonl").read_text(encoding="utf-8") == ""
    assert rig.meta()["errors"] == 0
    assert rig.meta()["polls"] == 3


# --- журнал -----------------------------------------------------------------------------------------------------------


def test_journal_ring_overflow_repeats_are_written_once(rig: Rig) -> None:
    """Кольцо отдаёт скользящее окно с перекрытием: каждая строка пишется один раз, порядок сохранён."""
    a = (1.0, "in", "W* CMD_SEQ = 11")
    b = (1.5, "in", "W* CMD_OPCODE = 32 (CVT_JOB)")
    c = (2.0, "out", "[v2] CMD seq=11 op=CVT_JOB")
    d = (2.5, "out", "[v2] DONE seq=11 op=CVT_JOB")
    rig.sim.journal = [journal_reply([a, b]), journal_reply([a, b, c]), journal_reply([b, c, d]), journal_reply([c, d])]
    rig.stop_after_journal_polls(4)

    assert rig.go() == 0

    rows = rig.jsonl("sim_journal.jsonl")
    assert [(r["side"], r["text"]) for r in rows] == [
        ("in", "W* CMD_SEQ = 11"),
        ("in", "W* CMD_OPCODE = 32 (CVT_JOB)"),
        ("out", "[v2] CMD seq=11 op=CVT_JOB"),
        ("out", "[v2] DONE seq=11 op=CVT_JOB"),
    ]
    assert all(set(r) == {"t", "side", "text"} and _TIME_RE.match(r["t"]) for r in rows)
    assert rig.meta()["journal_lines"] == 4


def test_same_text_at_another_time_is_a_new_line(rig: Rig) -> None:
    """Ключ дедупа — ``(t, side, text)``: тот же текст в другой момент — другая строка (две ``STOP_REQ``)."""
    rig.sim.journal = [
        journal_reply([(1.0, "in", "STOP_REQ")]),
        journal_reply([(1.0, "in", "STOP_REQ"), (9.0, "in", "STOP_REQ")]),
    ]
    rig.stop_after_journal_polls(2)

    assert rig.go() == 0

    assert [r["text"] for r in rig.jsonl("sim_journal.jsonl")] == ["STOP_REQ", "STOP_REQ"]


def test_merged_ring_row_with_growing_n_and_moving_t_is_written_once(rig: Rig) -> None:
    """Keepalive ``W 0x1204 = 1``: кольцо склеивает повторы, растит ``n`` и двигает ``t``. Файл — одна строка."""
    cmd = (2.0, "out", "[v2] CMD seq=11 op=CVT_JOB")
    keepalive = "W 0x1204 = 1"
    rig.sim.journal = [
        journal_reply([cmd, (3.0, "in", keepalive, 1)]),
        journal_reply([cmd, (3.5, "in", keepalive, 2)]),
        journal_reply([cmd, (4.0, "in", keepalive, 3)]),
        journal_reply([cmd, (4.5, "in", keepalive, 4), (5.0, "in", "W 0x1205 = 0")]),
        journal_reply([(4.5, "in", keepalive, 4), (5.0, "in", "W 0x1205 = 0")]),
    ]
    rig.stop_after_journal_polls(5)

    assert rig.go() == 0

    assert [r["text"] for r in rig.jsonl("sim_journal.jsonl")] == [cmd[2], keepalive, "W 0x1205 = 0"]
    assert rig.meta()["journal_lines"] == 3


def test_merged_row_first_seen_already_grown_is_written_once(rig: Rig) -> None:
    keepalive = "W 0x1204 = 1"
    rig.sim.journal = [
        journal_reply([(3.0, "in", keepalive, 5)]),
        journal_reply([(3.5, "in", keepalive, 6)]),
        journal_reply([(4.0, "in", keepalive, 7)]),
    ]
    rig.stop_after_journal_polls(3)

    assert rig.go() == 0

    assert [r["text"] for r in rig.jsonl("sim_journal.jsonl")] == [keepalive]
    assert rig.meta()["journal_lines"] == 1


def test_same_text_run_after_another_line_is_a_new_line(rig: Rig) -> None:
    """Склейка касается только последней строки кольца: тот же текст после другой строки — новая запись."""
    k, y = "W 0x1204 = 1", "W 0x1205 = 0"
    rig.sim.journal = [
        journal_reply([(1.0, "in", k, 2), (2.0, "in", y)]),
        journal_reply([(1.0, "in", k, 2), (2.0, "in", y), (3.0, "in", k)]),
        journal_reply([(1.0, "in", k, 2), (2.0, "in", y), (3.5, "in", k, 2)]),
    ]
    rig.stop_after_journal_polls(3)

    assert rig.go() == 0

    assert [r["text"] for r in rig.jsonl("sim_journal.jsonl")] == [k, y, k]


def test_seen_keys_window_is_bounded() -> None:
    keys = collect._RecentKeys(3)
    for n in range(5):
        keys.add(("t", n))
    keys.add(("t", 4))  # повтор не занимает место

    assert len(keys) == 3
    assert ("t", 0) not in keys and ("t", 1) not in keys
    assert all(("t", n) in keys for n in (2, 3, 4))


def test_journal_server_not_running_is_logged_and_collection_goes_on(rig: Rig) -> None:
    rig.sim.journal = [
        {"result": {"status": "error", "message": "server_not_running"}},
        journal_reply([(1.0, "in", "W 0x1204 = 1")]),
    ]
    rig.stop_after_journal_polls(2)

    assert rig.go() == 0

    assert [r["text"] for r in rig.jsonl("sim_journal.jsonl")] == ["W 0x1204 = 1"]
    assert rig.meta()["errors"] == 1
    assert "server_not_running" in (rig.out_dir / "collect.log").read_text(encoding="utf-8")


# --- сбой опроса ------------------------------------------------------------------------------------------------------


def test_client_exception_mid_poll_does_not_stop_collection(rig: Rig) -> None:
    """Исключение при чтении объектов на 2-м опросе: журнал того же опроса прочитан, сбор идёт до STOP."""
    o1 = passport("Е", 30.0, 1.0)
    rig.sim.objects = [objects_reply({"o1": o1}), TimeoutError("state.get timeout"), objects_reply({"o1": o1})]
    rig.sim.journal = [
        journal_reply([(1.0, "in", "a")]),
        journal_reply([(1.0, "in", "a"), (2.0, "in", "b")]),
        journal_reply([(3.0, "in", "c")]),
    ]
    rig.stop_after_journal_polls(3)

    assert rig.go() == 0

    meta = rig.meta()
    assert (meta["polls"], meta["errors"], meta["objects"], meta["journal_lines"]) == (3, 1, 1, 3)
    assert [r["text"] for r in rig.jsonl("sim_journal.jsonl")] == ["a", "b", "c"]
    log = (rig.out_dir / "collect.log").read_text(encoding="utf-8")
    assert len(log.splitlines()) == 1
    assert "objects" in log and "TimeoutError" in log
    assert "sim.objects" not in log  # значений аргументов команды в логе нет


def test_journal_exception_does_not_block_objects(rig: Rig) -> None:
    rig.sim.objects = [objects_reply({"o1": passport("М", 10.0, 0.0)})]
    rig.sim.journal = [ConnectionError("lost")]
    rig.stop_after_journal_polls(2)

    assert rig.go() == 0

    assert [r["object_id"] for r in rig.jsonl("sim_objects.jsonl")] == ["o1"]
    assert rig.meta()["errors"] == 2


# --- остановка --------------------------------------------------------------------------------------------------------


def test_stop_file_during_sleep_stops_before_next_poll(rig: Rig) -> None:
    """STOP появляется во время сна после 1-го опроса: второго опроса нет, причина — stop_file."""
    rig.time.hook = lambda n: (rig.out_dir / "STOP").write_text("", encoding="utf-8") if n == 1 else None

    assert rig.go() == 0

    meta = rig.meta()
    assert meta["polls"] == 1
    assert meta["stop_reason"] == "stop_file"
    assert rig.time.sleeps == 1  # сон прерван на первом шаге, а не отсижен весь период


def test_stale_stop_file_from_previous_run_is_removed_at_start(rig: Rig) -> None:
    rig.out_dir.mkdir(parents=True)
    (rig.out_dir / "STOP").write_text("", encoding="utf-8")
    rig.stop_after_journal_polls(2)

    assert rig.go() == 0

    assert rig.meta()["polls"] == 2


def test_keyboard_interrupt_ends_cleanly_with_data_kept(rig: Rig) -> None:
    rig.sim.journal = [journal_reply([(1.0, "in", "a")]), KeyboardInterrupt()]

    assert rig.go() == 0

    assert [r["text"] for r in rig.jsonl("sim_journal.jsonl")] == ["a"]
    assert rig.meta()["stop_reason"] == "interrupt"


# --- старт, аргументы, реестр -----------------------------------------------------------------------------------------


def test_unreachable_port_exit_3_without_values_in_message(rig: Rig) -> None:
    rig.sim.connect_error = ConnectionRefusedError("127.0.0.1:8766 refused")

    assert rig.go() == 3

    assert "8766" not in rig.err.getvalue()
    assert rig.sim.closed and rig.proto.closed
    assert rig.sim.calls == [] and rig.proto.calls == []


def test_registers_json_from_layout_register_and_default_pick_rz(rig: Rig) -> None:
    rig.stop_after_journal_polls(1)

    assert rig.go() == 0

    registers = json.loads((rig.out_dir / "registers.json").read_text(encoding="utf-8"))
    assert registers == {
        "first_x": 320.0,
        "first_y": -440.0,
        "pitch_mm": 0.0,
        "disk_radius_mm": 55.0,
        "line_angle_deg": 90.0,
        "place_z_mm": -132.0,
        "pick_z_mm": -132.0,
        "angle_zero_deg": 0.0,
        "angle_invert": False,
        "use_pitch": True,
        "word_gap_slots": 0,
        "p_pick_rz_deg": -100.0,
    }
    meta = rig.meta()
    assert meta["p_pick_rz_deg_source"].startswith("default")
    assert meta["registers"] == "ok"
    assert rig.proto.calls[0] == ("layout", "introspect.registers", None)


def test_p_pick_rz_taken_from_register_when_present(rig: Rig) -> None:
    rig.proto.layout = {"result": {"registers": {"word_layout": {"first_x": 1.0, "p_pick_rz_deg": -1000.0}}}}
    rig.stop_after_journal_polls(1)

    assert rig.go() == 0

    registers = json.loads((rig.out_dir / "registers.json").read_text(encoding="utf-8"))
    assert registers == {"first_x": 1.0, "p_pick_rz_deg": -1000.0}
    assert rig.meta()["p_pick_rz_deg_source"] == "register"
    assert "first_y" in rig.meta()["registers_missing"]


def test_missing_layout_register_is_logged_and_collection_still_runs(rig: Rig) -> None:
    rig.proto.layout = {"result": {"registers": {}}}
    rig.stop_after_journal_polls(1)

    assert rig.go() == 0

    assert not (rig.out_dir / "registers.json").exists()
    meta = rig.meta()
    assert (meta["registers"], meta["errors"], meta["polls"]) == ("missing", 1, 1)


def test_nonempty_out_dir_data_refused_with_exit_2(rig: Rig) -> None:
    rig.out_dir.mkdir(parents=True)
    (rig.out_dir / "sim_journal.jsonl").write_text('{"t": "x", "side": "in", "text": "old"}\n', encoding="utf-8")

    assert rig.go() == 2

    assert (rig.out_dir / "sim_journal.jsonl").read_text(encoding="utf-8").count("old") == 1
    assert rig.sim.calls == []


@pytest.mark.parametrize("period", ["0", "-1", "abc"])
def test_bad_period_exit_2(rig: Rig, period: str) -> None:
    assert rig.go(["--period", period]) == 2
    assert rig.sim.calls == []


def test_collector_only_reads(rig: Rig) -> None:
    """Все вызовы клиентов — из списка чтения; записывающих команд сим и прототип не получают."""
    rig.sim.objects = [objects_reply({"o1": passport("Е", 1.0, 1.0)})]
    rig.sim.journal = [journal_reply([(1.0, "in", "a")])]
    rig.stop_after_journal_polls(3)

    assert rig.go() == 0

    assert {(t, c) for t, c, _ in rig.sim.calls} == {("ProcessManager", "state.get"), ("robot", "sim_robot.journal")}
    assert [(t, c) for t, c, _ in rig.proto.calls] == [("layout", "introspect.registers")]


# --- настоящее время и настоящие файлы --------------------------------------------------------------------------------


def test_real_clock_real_files_flushed_while_running(tmp_path: Path) -> None:
    """Без фейка времени: данные видны на диске ДО остановки (flush), STOP посреди сна останавливает быстро."""
    out_dir = tmp_path / "live"
    sim, proto = FakeClient(), FakeClient()
    sim.objects = [objects_reply({"o1": passport("Е", 30.0, -12.5)})]
    sim.journal = [journal_reply([(1.0, "in", "W* CMD_SEQ = 11")])]
    result: list[int] = []
    argv = ["--proto-port", "8765", "--sim-port", "8766", "--out-dir", str(out_dir), "--period", "0.2"]

    worker = threading.Thread(
        target=lambda: result.append(
            collect.run(argv, client_factory=lambda port: proto if port == 8765 else sim, err=StringIO())
        ),
        daemon=True,
    )
    worker.start()

    journal = out_dir / "sim_journal.jsonl"
    deadline = time.monotonic() + _DEADLINE_S
    while time.monotonic() < deadline and not (journal.exists() and journal.read_text(encoding="utf-8")):
        time.sleep(0.02)
    seen_before_stop = journal.read_text(encoding="utf-8").splitlines()
    (out_dir / "STOP").write_text("", encoding="utf-8")
    stopped_at = time.monotonic()
    worker.join(_DEADLINE_S)

    assert not worker.is_alive(), "сборщик не остановился по STOP"
    assert time.monotonic() - stopped_at < 1.0  # период 0,2 с: STOP замечен в течение сна, а не через минуты
    assert result == [0]
    assert len(seen_before_stop) == 1 and json.loads(seen_before_stop[0])["text"] == "W* CMD_SEQ = 11"
    assert datetime.strptime(json.loads(seen_before_stop[0])["t"], "%Y-%m-%d %H:%M:%S,%f")
    objects = (out_dir / "sim_objects.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["object_id"] for line in objects] == ["o1"]
    assert json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))["stop_reason"] == "stop_file"
