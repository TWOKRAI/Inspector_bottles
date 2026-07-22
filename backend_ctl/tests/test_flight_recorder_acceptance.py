# -*- coding: utf-8 -*-
"""Сквозной acceptance flight recorder (D.4, Step 7) — §Acceptance родителя.

Запись на live-сессии → record_stop → загрузка в ОТДЕЛЬНОЙ сессии БЕЗ живого
бэкенда (factory бросает): snapshot/history/await_condition/events отвечают ПО
ЗАПИСИ (оба position); файл без footer → truncated:true, но грузится.

Live-бэкенд эмулируется detached driver'ом (тот же read-model, что вживую);
replay-сессия физически не имеет бэкенда — доказывает offline-загрузку.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.mcp_driver_session import MODE_REPLAY, DriverSession
from backend_ctl.dispatch import dispatch_tool, resolve_record_path


def _state_push(path: str, value: Any) -> Dict[str, Any]:
    return {"command": "state.changed", "data": {"deltas": [{"path": path, "new_value": value}]}}


@pytest.fixture
def record_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("BACKEND_CTL_RECORD_DIR", str(tmp_path / "records"))
    return tmp_path


def _no_backend() -> BackendDriver:
    raise OSError("нет живого бэкенда (replay-сессия)")


def _record_flight(name: str) -> None:
    """Записать сессию на живом (detached) driver'е: три fps-дельты."""
    drv = BackendDriver("127.0.0.1", 8765)
    live = DriverSession(driver_factory=lambda: drv)
    assert dispatch_tool(live, "record_start", {"name": name})["success"] is True
    for v in (10.0, 20.0, 30.0):
        drv._emit_event(_state_push("processes.cam.state.fps", v))
    deadline = time.monotonic() + 2.0
    while live._recorder._events_written < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    dispatch_tool(live, "record_stop", {})
    live.close()  # живая система ушла


def test_acceptance_replay_without_live_system_position_end(record_dir: Path) -> None:
    _record_flight("flight1")

    # Отдельная сессия БЕЗ живого бэкенда (factory бросает — доказательство offline).
    replay = DriverSession(driver_factory=_no_backend)
    load = dispatch_tool(replay, "record_load", {"name": "flight1", "position": "end"})
    assert load["success"] is True
    assert replay.mode == MODE_REPLAY

    # snapshot по записи.
    snap = dispatch_tool(replay, "telemetry_snapshot", {})
    assert snap["metrics"]["processes.cam.state.fps"]["value"] == 30.0

    # history по записи.
    hist = dispatch_tool(replay, "telemetry_history", {"path": "processes.cam.state.fps"})
    assert hist["count"] == 3

    # events_page по записи.
    page = dispatch_tool(replay, "events_page", {"plane": "all"})
    assert page["count"] == 3

    # await_condition по записи — мгновенный успех по достигнутому финалу.
    aw = dispatch_tool(
        replay, "await_condition", {"kind": "state_path", "spec": {"path": "processes.cam.state.fps", "value": 30.0}}
    )
    assert aw["success"] is True
    assert aw["replay"]["position"] == 3


def test_acceptance_replay_position_start_time_travel(record_dir: Path) -> None:
    _record_flight("flight2")

    replay = DriverSession(driver_factory=_no_backend)
    load = dispatch_tool(replay, "record_load", {"name": "flight2", "position": "start"})
    assert load["success"] is True

    # Лента не прокручена — финального значения ещё нет.
    snap0 = dispatch_tool(replay, "telemetry_snapshot", {})
    assert "processes.cam.state.fps" not in snap0["metrics"]

    # await прокручивает playhead до промежуточного значения 20.
    aw = dispatch_tool(
        replay, "await_condition", {"kind": "state_path", "spec": {"path": "processes.cam.state.fps", "value": 20.0}}
    )
    assert aw["success"] is True
    assert aw["replay"]["position"] == 2
    # snapshot после await = состояние момента срабатывания (20, не финал 30).
    snap = dispatch_tool(replay, "telemetry_snapshot", {})
    assert snap["metrics"]["processes.cam.state.fps"]["value"] == 20.0


def test_acceptance_truncated_file_loads(record_dir: Path) -> None:
    _record_flight("flight3")
    path = resolve_record_path("flight3")
    # Эмулируем жёсткий обрыв: срезаем footer.
    lines = [ln for ln in Path(path).read_text(encoding="utf-8").splitlines() if '"footer"' not in ln]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

    replay = DriverSession(driver_factory=_no_backend)
    load = dispatch_tool(replay, "record_load", {"name": "flight3"})
    assert load["success"] is True
    assert load["truncated"] is True  # честно помечено
    # Но разобранное грузится и обслуживается.
    snap = dispatch_tool(replay, "telemetry_snapshot", {})
    assert snap["metrics"]["processes.cam.state.fps"]["value"] == 30.0


def test_acceptance_footer_present_on_clean_stop(record_dir: Path) -> None:
    _record_flight("flight4")
    path = resolve_record_path("flight4")
    lines = [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines[-1]["footer"] is True
    assert lines[-1]["reason"] == "stopped"
    assert lines[-1]["events_written"] == 3
