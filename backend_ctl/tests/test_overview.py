# -*- coding: utf-8 -*-
"""Тесты B.3: system_overview — компактная сводка + anomalies на подставных счётчиках.

Acceptance плана: сводка компактна; аномалии детектятся на fake-ответах;
ноль новых IPC-команд (fan-out только существующими ручками).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from backend_ctl.driver import BackendDriver


def _line(msg: Dict[str, Any]) -> bytes:
    return json.dumps(msg, ensure_ascii=False).encode("utf-8")


def _feed_state(d: BackendDriver, path: str, value: Any) -> None:
    d.dispatch_raw(_line({"command": "state.changed", "data": {"deltas": [{"path": path, "new_value": value}]}}))


def _fake_backend(
    monkeypatch, d: BackendDriver, *, procs: List[str], responses: Dict[str, Dict[str, Any]]
) -> List[str]:
    """Подставной send_command: канонические ответы по (command) + журнал команд."""
    sent: List[str] = []

    def fake_send(target: str, command: str, args: Any = None, *, timeout: Any = None) -> Dict[str, Any]:
        sent.append(command)
        if command == "state.get_subtree":
            return {"success": True, "result": {"subtree": {p: {} for p in procs}}}
        per_target = responses.get(f"{command}@{target}")
        if per_target is not None:
            return per_target
        return responses.get(command, {"success": False, "error": "нет ответа (fake)"})

    monkeypatch.setattr(d, "send_command", fake_send)
    return sent


def _healthy_responses() -> Dict[str, Dict[str, Any]]:
    return {
        "introspect.status": {
            "success": True,
            "process": "p",
            "status": "running",
            "workers": {"w1": {"status": "running"}},
        },
        "introspect.router_stats": {
            "success": True,
            "router_stats": {"sent_ok": 10, "received": 20, "middleware_dropped": 0, "errors": 0},
        },
        "introspect.queues": {"success": True, "queue_sizes": {"system": 1, "data": 2}},
        "introspect.memory": {"success": True, "memory": {}, "pool": {}, "queues": {}, "shm_registry": {}},
    }


class TestOverviewShape:
    def test_compact_summary_healthy_system(self, monkeypatch) -> None:
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=_healthy_responses())
        res = d.system_overview()
        assert res["success"] is True
        card = res["processes"]["cam"]
        assert card["status"] == "running"
        assert card["workers"] == {"w1": "running"}  # компактно: имя → статус-строка
        assert card["router"]["middleware_dropped"] == 0
        assert "raw" not in json.dumps(card)  # сырые ответы в сводку не протекают
        assert res["anomaly_count"] == 0

    def test_zero_new_ipc_commands(self, monkeypatch) -> None:
        """Fan-out только существующими ручками — новых IPC-команд ноль."""
        d = BackendDriver()
        sent = _fake_backend(monkeypatch, d, procs=["cam", "gui"], responses=_healthy_responses())
        d.system_overview()
        allowed = {
            "state.get_subtree",
            "introspect.status",
            "introspect.router_stats",
            "introspect.queues",
            "introspect.memory",
        }
        assert set(sent) <= allowed

    def test_empty_topology_hint(self, monkeypatch) -> None:
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=[], responses={})
        res = d.system_overview()
        assert res["processes"] == {}
        assert any(a["kind"] == "empty_topology" for a in res["anomalies"])


class TestAnomalies:
    def test_router_dropped_and_queue_depth_detected(self, monkeypatch) -> None:
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.router_stats"] = {
            "success": True,
            "router_stats": {"sent_ok": 5, "received": 9, "middleware_dropped": 3, "errors": 1},
        }
        responses["introspect.queues"] = {"success": True, "queue_sizes": {"data": 120}}
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        kinds = {a["kind"] for a in res["anomalies"]}
        assert {"router_dropped", "router_errors", "queue_depth"} <= kinds

    def test_fps_zero_while_running_detected(self, monkeypatch) -> None:
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=_healthy_responses())
        _feed_state(d, "processes.cam.workers.w1.state.fps", 0)  # локальный read-model
        res = d.system_overview()
        hits = [a for a in res["anomalies"] if a["kind"] == "fps_zero_while_running"]
        assert hits and hits[0]["process"] == "cam"

    def test_fps_zero_on_stopped_process_not_flagged(self, monkeypatch) -> None:
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.status"] = {"success": True, "process": "cam", "status": "stopped", "workers": {}}
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        _feed_state(d, "processes.cam.workers.w1.state.fps", 0)
        res = d.system_overview()
        kinds = {a["kind"] for a in res["anomalies"]}
        assert "fps_zero_while_running" not in kinds  # fps=0 у остановленного — норма
        assert "process_not_running" in kinds

    def test_recovery_and_driver_counters_surface(self, monkeypatch) -> None:
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=_healthy_responses())
        _feed_state(d, "processes.cam.supervisor.event", "recovered")
        d._late_replies = 2  # подставной счётчик driver'а
        res = d.system_overview()
        kinds = {a["kind"] for a in res["anomalies"]}
        assert {"recent_recovery", "late_replies"} <= kinds
        assert res["driver"]["late_replies"] == 2

    def test_events_evicted_visible(self, monkeypatch) -> None:
        d = BackendDriver(event_queue_maxlen=2)
        _fake_backend(monkeypatch, d, procs=[], responses={})
        for i in range(5):
            _feed_state(d, "processes.cam.state.fps", i)  # переполняем кольца
        res = d.system_overview()
        assert any(a["kind"] == "events_evicted" for a in res["anomalies"])
        assert res["driver"]["events_evicted"]["state"] == 3

    def test_introspect_failure_is_honest(self, monkeypatch) -> None:
        d = BackendDriver()
        responses = _healthy_responses()
        del responses["introspect.router_stats"]  # ручка «не отвечает» (fake error)
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        assert res["processes"]["cam"]["ok"] is False
        assert any(a["kind"] == "introspect_failed" for a in res["anomalies"])
