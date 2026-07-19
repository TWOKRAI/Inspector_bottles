# -*- coding: utf-8 -*-
"""Тесты flight recorder (D.4) — writer/подписчик, лимиты, footer.

Step 2 (этот модуль): механика записи. Реплей/offline-await — в
test_replay.py (Steps 3-4). Драйвер здесь — неподключённый BackendDriver
(detached read-model): subscribe/_emit_event/telemetry работают offline;
system_overview/state.get_subtree деградируют best-effort (IPC недоступен).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

from backend_ctl.driver import BackendDriver
from backend_ctl.recorder import (
    FORMAT,
    REASON_LIMIT,
    REASON_STOPPED,
    VERSION,
    Recorder,
)


def _state_push(path: str, value: Any) -> Dict[str, Any]:
    """Валидный push state.changed (одна дельта) — тот же wire-контракт, что вживую."""
    return {"command": "state.changed", "data": {"deltas": [{"path": path, "new_value": value}]}}


def _detached_driver() -> BackendDriver:
    """Неподключённый driver = рабочий offline read-model (hub/telemetry в __init__)."""
    return BackendDriver("127.0.0.1", 8765)


def _read_lines(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _wait_written(rec: Recorder, n: int, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while rec._events_written < n and time.monotonic() < deadline:
        time.sleep(0.01)


def test_header_written_with_format_and_version(tmp_path: Path) -> None:
    drv = _detached_driver()
    drv._emit_event(_state_push("processes.cam.state.fps", 30.0))
    rec = Recorder(drv, str(tmp_path / "r.jsonl"))
    rec.start()
    rec.stop()

    lines = _read_lines(str(tmp_path / "r.jsonl"))
    header = lines[0]
    assert header["format"] == FORMAT
    assert header["version"] == VERSION
    assert "snapshot" in header
    # telemetry-секция собрана из read-model (offline OK).
    assert header["snapshot"]["telemetry"]["values"]["processes.cam.state.fps"] == 30.0
    assert header["snapshot"]["telemetry"]["history"]["processes.cam.state.fps"]


def test_events_recorded_between_start_and_stop(tmp_path: Path) -> None:
    drv = _detached_driver()
    rec = Recorder(drv, str(tmp_path / "r.jsonl"))
    rec.start()
    drv._emit_event(_state_push("processes.cam.state.fps", 10.0))
    drv._emit_event(_state_push("processes.cam.state.fps", 20.0))
    _wait_written(rec, 2)
    status = rec.stop()

    assert status["events_written"] == 2
    assert status["dropped"] == 0
    lines = _read_lines(str(tmp_path / "r.jsonl"))
    events = [ln for ln in lines if "event" in ln]
    assert len(events) == 2
    # seq — плотный счётчик recorder'а; ts — время приёма.
    assert [e["seq"] for e in events] == [1, 2]
    assert all(isinstance(e["ts"], float) for e in events)
    # event — оригинальный push бит-в-бит.
    assert events[0]["event"] == _state_push("processes.cam.state.fps", 10.0)


def test_footer_marks_clean_stop(tmp_path: Path) -> None:
    drv = _detached_driver()
    rec = Recorder(drv, str(tmp_path / "r.jsonl"))
    rec.start()
    rec.stop()

    lines = _read_lines(str(tmp_path / "r.jsonl"))
    footer = lines[-1]
    assert footer["footer"] is True
    assert footer["reason"] == REASON_STOPPED
    assert footer["events_written"] == 0
    assert footer["dropped"] == 0


def test_stop_is_idempotent(tmp_path: Path) -> None:
    drv = _detached_driver()
    rec = Recorder(drv, str(tmp_path / "r.jsonl"))
    rec.start()
    first = rec.stop()
    second = rec.stop()  # повторный stop не должен ни бросать, ни дописывать footer
    assert first["events_written"] == second["events_written"]
    lines = _read_lines(str(tmp_path / "r.jsonl"))
    footers = [ln for ln in lines if ln.get("footer")]
    assert len(footers) == 1  # ровно один footer


def test_max_events_limit_auto_stops(tmp_path: Path) -> None:
    drv = _detached_driver()
    rec = Recorder(drv, str(tmp_path / "r.jsonl"), max_events=3)
    rec.start()
    for i in range(10):
        drv._emit_event(_state_push("processes.cam.state.fps", float(i)))
    # writer авто-останавливается по достижении лимита.
    deadline = time.monotonic() + 2.0
    while rec.active and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not rec.active
    lines = _read_lines(str(tmp_path / "r.jsonl"))
    footer = lines[-1]
    assert footer["reason"] == REASON_LIMIT
    assert footer["events_written"] == 3


def test_queue_overflow_counts_dropped(tmp_path: Path) -> None:
    """Переполнение очереди writer'а → dropped в footer, не тихая потеря."""
    drv = _detached_driver()
    rec = Recorder(drv, str(tmp_path / "r.jsonl"), queue_maxlen=2)
    rec.start()
    # Забиваем очередь до старта записи на диск: колбэк лёгкий, writer-поток
    # может не успеть — при переполнении новые события считаются в dropped.
    with rec._qlock:
        # Искусственно блокируем слив, наполняя очередь сверх maxlen.
        rec._queue.append((1, time.time(), _state_push("p", 1)))
        rec._queue.append((2, time.time(), _state_push("p", 2)))
    drv._emit_event(_state_push("p", 3))  # очередь полна → dropped++
    assert rec._dropped >= 1
    rec.stop()


def test_start_without_subscriptions_hints(tmp_path: Path) -> None:
    drv = _detached_driver()
    rec = Recorder(drv, str(tmp_path / "r.jsonl"))
    out = rec.start()
    assert out["success"] is True
    # detached driver без активных подписок → hint про пустую ленту.
    assert "hint" in out
    rec.stop()


def test_double_start_rejected(tmp_path: Path) -> None:
    drv = _detached_driver()
    rec = Recorder(drv, str(tmp_path / "r.jsonl"))
    rec.start()
    again = rec.start()
    assert again["success"] is False
    rec.stop()
