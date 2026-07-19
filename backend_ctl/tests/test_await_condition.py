# -*- coding: utf-8 -*-
"""Тесты B.2: await_condition — серверное ожидание вместо поллинга.

Acceptance плана: синтетический поток дельт → условие срабатывает на нужной;
таймаут возвращает диагноз (что ждали / что видели), не пустоту.

Поток имитируется producer-потоком, кормящим dispatch_raw (как reader-поток),
пока клиентский поток блокируется в await_condition — ноль поллинга, без сокета.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List

from backend_ctl.driver import BackendDriver


def _line(msg: Dict[str, Any]) -> bytes:
    return json.dumps(msg, ensure_ascii=False).encode("utf-8")


def _state_line(path: str, value: Any) -> bytes:
    return _line({"command": "state.changed", "data": {"deltas": [{"path": path, "new_value": value}]}})


def _feed_later(d: BackendDriver, lines: List[bytes], delay: float = 0.05) -> threading.Thread:
    """Producer: подать строки в dispatch_raw после паузы (клиент уже ждёт)."""

    def run() -> None:
        time.sleep(delay)
        for raw in lines:
            d.dispatch_raw(raw)

    th = threading.Thread(target=run)
    th.start()
    return th


class TestStatePath:
    def test_triggers_on_matching_delta_only(self) -> None:
        d = BackendDriver()
        th = _feed_later(
            d,
            [
                _state_line("processes.cam.state.status", "starting"),  # не то значение
                _state_line("processes.cam2.state.status", "running"),  # не тот путь
                _state_line("processes.cam.state.status", "running"),  # цель
            ],
        )
        res = d.await_condition("state_path", {"path": "processes.cam.state.status", "value": "running"}, timeout=2.0)
        th.join()
        assert res["success"] is True
        assert res["matched"]["value"] == "running"
        assert res["matched"]["source"] == "delta"

    def test_already_satisfied_returns_immediately(self) -> None:
        d = BackendDriver()
        d.dispatch_raw(_state_line("processes.cam.state.status", "running"))  # уже в read-model
        t0 = time.monotonic()
        res = d.await_condition("state_path", {"path": "processes.cam.state.status", "value": "running"}, timeout=5.0)
        assert res["success"] is True
        assert res["matched"]["source"] == "read-model"
        assert time.monotonic() - t0 < 1.0  # не ждал таймаута

    def test_missing_marker_is_not_a_value(self) -> None:
        d = BackendDriver()
        th = _feed_later(d, [_state_line("processes.cam.state.status", "__MISSING__")])
        res = d.await_condition("state_path", {"path": "processes.cam.state.status", "value": None}, timeout=0.3)
        th.join()
        assert res["success"] is False  # удаление узла не матчится как значение


class TestMetricThreshold:
    def test_triggers_when_threshold_crossed(self) -> None:
        d = BackendDriver()
        th = _feed_later(
            d,
            [
                _state_line("processes.cam.state.fps", 5),
                _state_line("processes.cam.state.fps", 9),
                _state_line("processes.cam.state.fps", 11),  # пересекла порог
            ],
        )
        res = d.await_condition(
            "metric_threshold", {"path": "processes.cam.state.fps", "op": ">=", "value": 10}, timeout=2.0
        )
        th.join()
        assert res["success"] is True
        assert res["matched"]["value"] == 11
        assert res["matched"]["op"] == ">="

    def test_timeout_diagnosis_carries_last_seen(self) -> None:
        d = BackendDriver()
        th = _feed_later(d, [_state_line("processes.cam.state.fps", 7)])
        res = d.await_condition(
            "metric_threshold", {"path": "processes.cam.state.fps", "op": ">", "value": 100}, timeout=0.3
        )
        th.join()
        assert res["success"] is False and res["timed_out"] is True
        assert res["waited"]["op"] == ">"
        assert res["last_seen"]["value"] == 7  # диагноз: что видели последним, не пустота
        assert res["events_seen"] >= 1

    def test_invalid_op_teaches(self) -> None:
        d = BackendDriver()
        res = d.await_condition("metric_threshold", {"path": "p", "op": "~", "value": 1}, timeout=0.1)
        assert res["success"] is False
        assert "op" in res["error"]


class TestEventMatches:
    def test_matches_plane_event_by_glob(self) -> None:
        d = BackendDriver()
        th = _feed_later(
            d,
            [
                _line({"command": "log.record", "data": {"record": {}}}),  # чужая плоскость
                _line({"command": "ui.event", "data": {"record": {"kind": "button"}}}),
            ],
        )
        res = d.await_condition("event_matches", {"plane": "ui", "pattern": "ui.*"}, timeout=2.0)
        th.join()
        assert res["success"] is True
        assert res["matched"]["matched_target"] == "ui.event"
        assert res["matched"]["event"]["command"] == "ui.event"

    def test_matches_delta_path_in_state_plane(self) -> None:
        d = BackendDriver()
        th = _feed_later(d, [_state_line("devices.plc.link", "up")])
        res = d.await_condition("event_matches", {"plane": "state", "pattern": "devices.*.link"}, timeout=2.0)
        th.join()
        assert res["success"] is True
        assert res["matched"]["matched_target"] == "devices.plc.link"

    def test_unknown_plane_teaches(self) -> None:
        d = BackendDriver()
        res = d.await_condition("event_matches", {"plane": "нет", "pattern": "*"}, timeout=0.1)
        assert res["success"] is False
        assert "plane" in res["error"]


class TestContract:
    def test_unknown_kind_and_bad_spec(self) -> None:
        d = BackendDriver()
        assert d.await_condition("wait_for", {}, timeout=0.1)["success"] is False
        assert d.await_condition("state_path", None, timeout=0.1)["success"] is False

    def test_timeout_hint_when_no_deltas_at_all(self) -> None:
        d = BackendDriver()
        res = d.await_condition("state_path", {"path": "processes.x.y", "value": 1}, timeout=0.2)
        assert res["success"] is False
        assert "подписка" in res["hint"]  # диагноз подсказывает вероятную причину

    def test_listener_removed_after_wait(self) -> None:
        d = BackendDriver()
        subs_before = d.events_stats()["subscribers"]
        d.await_condition("state_path", {"path": "p.q", "value": 1}, timeout=0.1)
        assert d.events_stats()["subscribers"] == subs_before  # временный подписчик снят
