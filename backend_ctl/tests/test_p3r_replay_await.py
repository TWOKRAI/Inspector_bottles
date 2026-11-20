# -*- coding: utf-8 -*-
"""P3r (доработка по minor ревью): ``ReplayPlayer.await_condition("state_path", узел)``.

REDS 6 в ``test_p3r_node_read.py`` покрывает ``ReplayPlayer.state_get``; здесь — тот же
узел через ``await_condition`` над записью. Настоящий ``ReplayPlayer``, узел попадает в
read-model обоими маршрутами реплея: header (``state``-дерево / ``telemetry.values``) и
события ``state.changed``. Ожидаемые значения — литералы.

  * позиция ``end``: узел уже в read-model -> ``success``, ``matched.source == "read-model"``;
  * позиция ``start`` (маршрут событий): лента прокручивается -> ``source == "delta"``;
  * ожидание ДРУГОГО dict -> таймаут-эквивалент, ``last_seen.value`` — вложенный dict.

Каждый вызов идёт в daemon-потоке с join-дедлайном: двойной захват обычного
``drv._telemetry_lock`` даёт зависание, а не исключение.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict

import pytest

from backend_ctl.driver import BackendDriver
from backend_ctl.recorder import Recorder, ReplayPlayer, load_recording

_DEADLINE_SEC = 5.0

_SPEC_NODE = {"path": "a.n", "value": {"x": 3}}
_SPEC_OTHER = {"path": "a.n", "value": {"x": 4}}


def _bounded(fn: Callable[[], Any], what: str) -> Any:
    """Выполнить ``fn`` в daemon-потоке с join-дедлайном; зависание -> pytest.fail."""
    box: Dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в основной поток
            box["error"] = exc

    th = threading.Thread(target=run, daemon=True, name=f"p3r-await-{what}")
    th.start()
    th.join(_DEADLINE_SEC)
    if th.is_alive():
        pytest.fail(f"зависание: {what} не вернулся за {_DEADLINE_SEC} с (вероятен двойной захват _telemetry_lock)")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _header_only_recording(tmp_path: Path, snapshot: Dict[str, Any]) -> str:
    """Запись только с header-снимком (событий нет)."""
    path = tmp_path / "hdr.jsonl"
    lines = [
        {"format": "bctl-record", "version": 1, "snapshot": snapshot},
        {"footer": True, "events_written": 0, "dropped": 0, "reason": "stopped"},
    ]
    path.write_text("\n".join(json.dumps(ln) for ln in lines) + "\n", encoding="utf-8")
    return str(path)


def _events_recording(tmp_path: Path, value: Any) -> str:
    """Настоящий Recorder пишет событие ``state.changed`` по ``a.n`` (узел целиком)."""
    drv = BackendDriver("127.0.0.1", 8765)
    out = str(tmp_path / "ev.jsonl")
    rec = Recorder(drv, out)
    rec.start()
    drv._emit_event({"command": "state.changed", "data": {"deltas": [{"path": "a.n", "new_value": value}]}})
    deadline = time.monotonic() + 2.0
    while rec._events_written < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    rec.stop()
    return out


def _player_header_state(tmp_path: Path, position: str) -> ReplayPlayer:
    """Узел из header: секция ``state`` (дерево) -> prime."""
    snapshot = {"state": {"status": "ok", "value": {"a": {"n": {"x": 3}}}}}
    return ReplayPlayer(load_recording(_header_only_recording(tmp_path, snapshot)), position=position)


def _player_header_telemetry(tmp_path: Path, position: str) -> ReplayPlayer:
    """Узел из header: плоский ``telemetry.values`` (так пишет Recorder из read-model)."""
    snapshot = {"telemetry": {"values": {"a.n.x": 3}, "history": {}}}
    return ReplayPlayer(load_recording(_header_only_recording(tmp_path, snapshot)), position=position)


def _player_events(tmp_path: Path, position: str) -> ReplayPlayer:
    """Узел из событий ``state.changed`` записи (header пуст)."""
    return ReplayPlayer(load_recording(_events_recording(tmp_path, {"x": 3})), position=position)


_ROUTES = {
    "header-state-tree": _player_header_state,
    "header-telemetry-values": _player_header_telemetry,
    "events-state-changed": _player_events,
}


@pytest.mark.parametrize("route", sorted(_ROUTES))
def test_replay_await_node_at_end_matches_from_read_model(tmp_path: Path, route: str) -> None:
    """Позиция end: узел уже в read-model -> success, ``matched.source == "read-model"``."""
    player = _ROUTES[route](tmp_path, "end")
    res = _bounded(lambda: player.await_condition("state_path", _SPEC_NODE), "await(end)")
    assert res["success"] is True, res
    assert res["matched"] == {"path": "a.n", "value": {"x": 3}, "source": "read-model"}, res


def test_replay_await_node_at_start_scrolls_to_delta(tmp_path: Path) -> None:
    """Позиция start (узел только в событиях): прокрутка -> success, ``matched.source == "delta"``."""
    player = _player_events(tmp_path, "start")
    res = _bounded(lambda: player.await_condition("state_path", _SPEC_NODE), "await(start)")
    assert res["success"] is True, res
    assert res["matched"]["source"] == "delta", res
    assert res["matched"]["path"] == "a.n", res
    assert res["matched"]["value"] == {"x": 3}, res
    assert res["replay"]["position"] == 1, res


@pytest.mark.parametrize("route", sorted(_ROUTES))
def test_replay_await_other_dict_times_out_with_nested_last_seen(tmp_path: Path, route: str) -> None:
    """Ожидание другого dict (позиция end) -> таймаут-эквивалент; ``last_seen.value`` — вложенный dict."""
    player = _ROUTES[route](tmp_path, "end")
    res = _bounded(lambda: player.await_condition("state_path", _SPEC_OTHER), "await(other, end)")
    assert res["success"] is False, res
    assert res["timed_out"] is True, res
    assert res["end_of_recording"] is True, res
    assert res["last_seen"]["path"] == "a.n", res
    assert res["last_seen"]["value"] == {"x": 3}, res


def test_replay_await_other_dict_from_start_keeps_nested_last_seen(tmp_path: Path) -> None:
    """Позиция start, другой dict: лента проиграна до конца, ``last_seen.value`` — вложенный dict дельты."""
    player = _player_events(tmp_path, "start")
    res = _bounded(lambda: player.await_condition("state_path", _SPEC_OTHER), "await(other, start)")
    assert res["success"] is False, res
    assert res["end_of_recording"] is True, res
    assert res["last_seen"]["value"] == {"x": 3}, res
    assert res["last_seen"]["source"] == "delta", res
