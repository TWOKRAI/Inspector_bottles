# -*- coding: utf-8 -*-
"""Тесты offline-реплея записи (D.4, Steps 3-4).

Round-trip: записанная лента → load_recording → ReplayPlayer прогружает её в
detached (неподключённый) driver; telemetry_snapshot/telemetry_history/events_page
отвечают по записи, ts истории — ЗАПИСАННЫЕ (не время загрузки). Offline-await —
навигация playhead'ом (§5.1).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.recorder import (
    Recorder,
    RecordingError,
    ReplayPlayer,
    load_recording,
)


def _state_push(path: str, value: Any) -> Dict[str, Any]:
    return {"command": "state.changed", "data": {"deltas": [{"path": path, "new_value": value}]}}


def _detached_driver() -> BackendDriver:
    return BackendDriver("127.0.0.1", 8765)


def _wait_written(rec: Recorder, n: int, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while rec._events_written < n and time.monotonic() < deadline:
        time.sleep(0.01)


def _record_fps_session(path: str, values: List[float]) -> None:
    """Записать сессию: серия дельт fps в ходе записи."""
    drv = _detached_driver()
    rec = Recorder(drv, path)
    rec.start()
    for v in values:
        drv._emit_event(_state_push("processes.cam.state.fps", v))
    _wait_written(rec, len(values))
    rec.stop()


# --------------------------------------------------------------------------- #
#  load_recording                                                              #
# --------------------------------------------------------------------------- #


def test_load_recording_round_trips(tmp_path: Path) -> None:
    path = str(tmp_path / "r.jsonl")
    _record_fps_session(path, [10.0, 20.0, 30.0])
    rec = load_recording(path)
    assert rec.truncated is False
    assert len(rec.events) == 3
    assert rec.footer is not None
    assert rec.footer["reason"] == "stopped"


def test_load_rejects_unknown_format(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps({"format": "something-else", "version": 1}) + "\n", encoding="utf-8")
    with pytest.raises(RecordingError, match="не запись bctl-record"):
        load_recording(str(path))


def test_load_rejects_unknown_version(tmp_path: Path) -> None:
    path = tmp_path / "v.jsonl"
    path.write_text(json.dumps({"format": "bctl-record", "version": 999}) + "\n", encoding="utf-8")
    with pytest.raises(RecordingError, match="незнакомая версия"):
        load_recording(str(path))


def test_load_truncated_file_still_loads(tmp_path: Path) -> None:
    """Файл без footer (жёсткий обрыв) → truncated=True, но грузится разобранное."""
    path = str(tmp_path / "r.jsonl")
    _record_fps_session(path, [10.0, 20.0])
    # Срезаем footer (эмулируем crash: файл без чистого завершения).
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    lines = [ln for ln in lines if '"footer"' not in ln]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

    rec = load_recording(path)
    assert rec.truncated is True
    assert len(rec.events) == 2  # разобранное грузится


# --------------------------------------------------------------------------- #
#  ReplayPlayer — position="end"                                              #
# --------------------------------------------------------------------------- #


def test_replay_end_serves_telemetry_snapshot(tmp_path: Path) -> None:
    path = str(tmp_path / "r.jsonl")
    _record_fps_session(path, [10.0, 20.0, 30.0])
    player = ReplayPlayer(load_recording(path), position="end")
    snap = player.driver.telemetry_snapshot()
    # Финальное значение метрики видно сразу (лента прокручена).
    assert snap["metrics"]["processes.cam.state.fps"]["value"] == 30.0
    assert player.playhead == player.total == 3


def test_replay_history_ts_are_recorded_not_load_time(tmp_path: Path) -> None:
    """ts истории при реплее — ЗАПИСАННЫЕ (из событийных строк), не время загрузки."""
    path = str(tmp_path / "r.jsonl")
    _record_fps_session(path, [10.0, 20.0, 30.0])
    # ts, которые recorder проштамповал событиям.
    recorded_ts = [ln["ts"] for ln in load_recording(path).events]

    time.sleep(0.05)  # гарантируем, что «сейчас» != записанные ts
    player = ReplayPlayer(load_recording(path), position="end")
    hist = player.driver.telemetry_history("processes.cam.state.fps")
    replay_ts = [ts for ts, _v in hist["points"]]
    assert replay_ts == recorded_ts, "история должна нести записанные ts, а не время реплея"


def test_replay_events_page_serves_recorded_events(tmp_path: Path) -> None:
    path = str(tmp_path / "r.jsonl")
    _record_fps_session(path, [10.0, 20.0])
    player = ReplayPlayer(load_recording(path), position="end")
    page = player.driver.events_page("all")
    assert page["success"] is True
    assert page["count"] == 2


# --------------------------------------------------------------------------- #
#  ReplayPlayer — position="start" (пошаговый тайм-трэвел)                     #
# --------------------------------------------------------------------------- #


def test_replay_start_leaves_playhead_at_zero(tmp_path: Path) -> None:
    path = str(tmp_path / "r.jsonl")
    _record_fps_session(path, [10.0, 20.0, 30.0])
    player = ReplayPlayer(load_recording(path), position="start")
    assert player.playhead == 0
    assert player.has_more() is True
    # Лента не прокручена — телеметрии финального значения ещё нет.
    snap = player.driver.telemetry_snapshot()
    assert "processes.cam.state.fps" not in snap["metrics"]


def test_replay_pump_advances_playhead(tmp_path: Path) -> None:
    path = str(tmp_path / "r.jsonl")
    _record_fps_session(path, [10.0, 20.0, 30.0])
    player = ReplayPlayer(load_recording(path), position="start")
    pumped = player.pump(2)
    assert pumped == 2
    assert player.playhead == 2
    snap = player.driver.telemetry_snapshot()
    assert snap["metrics"]["processes.cam.state.fps"]["value"] == 20.0


def test_replay_rejects_unknown_position(tmp_path: Path) -> None:
    path = str(tmp_path / "r.jsonl")
    _record_fps_session(path, [10.0])
    with pytest.raises(RecordingError, match="position"):
        ReplayPlayer(load_recording(path), position="middle")
