# -*- coding: utf-8 -*-
"""Тесты driver-обёрток телеметрии (PC 3.2/3.3): telemetry_reconfigure / telemetry_set.

Форма, а не логика: обёртки строят правильные router-сообщения и прокидывают наверх
результат применения. Транспорт мокается (``send_command`` записывает вызовы) — тот же
приём, что TestDebugSession / TestSetRegisterVerified в test_driver.py. Проверяем:

  - адресный кейс → ``telemetry.broadcast`` на PM с ``target=<процесс>`` (Task 1.4:
    транзит через PM ради cap-детекции на per-process пути);
  - fan-out (``process="all"``/``None``/``"*"``) → ``telemetry.broadcast`` на PM без ``target``;
  - ``publish=None`` доезжает как валидная под-секция (сентинел ≠ None);
  - ``telemetry_set`` строит верные args для publisher- и throttle-плоскостей;
  - результат применения (``applied`` / охват) прокидывается наверх (``_leaf_result``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from backend_ctl.driver import BackendDriver


def _recorder(monkeypatch, response: Dict[str, Any] | None = None) -> Tuple[BackendDriver, List[tuple]]:
    """Driver с замоканным send_command, записывающим (process, command, args)."""
    d = BackendDriver()
    calls: List[tuple] = []

    def fake_send(process, command, args=None, **kw):
        calls.append((process, command, args))
        return response if response is not None else {"success": True}

    monkeypatch.setattr(d, "send_command", fake_send)
    return d, calls


class TestTelemetryReconfigureAddressing:
    def test_addressed_process_routes_via_pm_with_target(self, monkeypatch) -> None:
        """Task 1.4: адресный кейс идёт через PM (target), а НЕ напрямую ребёнку —
        чтобы PM детектил capped_by_throttle своим central-троттлом."""
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure("camera_0", publish={"metrics": {"fps": {"enabled": False}}})
        assert len(calls) == 1
        process, command, args = calls[0]
        assert (process, command) == ("ProcessManager", "telemetry.broadcast")
        assert args == {"publish": {"metrics": {"fps": {"enabled": False}}}, "target": "camera_0"}

    def test_all_process_sends_broadcast_to_pm(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure("all", publish={"default_interval_sec": 2.0})
        process, command, args = calls[0]
        assert (process, command) == ("ProcessManager", "telemetry.broadcast")
        assert args == {"publish": {"default_interval_sec": 2.0}}

    def test_none_process_is_fanout(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure(None, throttle={"a.b": 1.0})
        assert calls[0][1] == "telemetry.broadcast"
        assert calls[0][0] == "ProcessManager"

    def test_star_process_is_fanout(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure("*", publish={})
        assert calls[0][1] == "telemetry.broadcast"

    def test_custom_pm_name(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure("all", publish={}, pm_name="Orchestrator")
        assert calls[0][0] == "Orchestrator"


class TestTelemetryReconfigureArgs:
    def test_publish_none_is_sent_as_subsection(self, monkeypatch) -> None:
        """publish=None — валидная команда «выключить gate»: доезжает как ключ (+ target)."""
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure("camera_0", publish=None)
        assert calls[0][2] == {"publish": None, "target": "camera_0"}

    def test_both_planes_in_one_call(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure("camera_0", publish={"x": 1}, throttle={"p.q": 2.0})
        assert calls[0][2] == {"publish": {"x": 1}, "throttle": {"p.q": 2.0}, "target": "camera_0"}

    def test_no_subsection_is_error_and_sends_nothing(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        res = d.telemetry_reconfigure("camera_0")
        assert res["success"] is False
        assert "publish" in res["error"] or "throttle" in res["error"]
        assert calls == []  # ничего не отправлено

    def test_applied_result_propagated(self, monkeypatch) -> None:
        """Результат применения (handler: applied) прокидывается наверх через _leaf_result."""
        response = {"success": True, "result": {"success": True, "process": "camera_0", "applied": {"publish": True}}}
        d, _calls = _recorder(monkeypatch, response=response)
        res = d.telemetry_reconfigure("camera_0", publish={})
        assert res["applied"] == {"publish": True}

    def test_no_receiver_visible_in_result(self, monkeypatch) -> None:
        """«Нет приёмника» (throttle на процесс без StateStoreManager) виден наверху."""
        response = {"success": True, "result": {"applied": {"throttle": False}}}
        d, _calls = _recorder(monkeypatch, response=response)
        res = d.telemetry_reconfigure("camera_0", throttle={"a": 1.0})
        assert res["applied"] == {"throttle": False}


class TestTelemetryFanoutCoverage:
    def test_fanout_coverage_propagated(self, monkeypatch) -> None:
        """Агрегированный охват fan-out (reached/target_count) виден наверху."""
        response = {
            "success": True,
            "result": {
                "success": True,
                "process": "ProcessManager",
                "publish": {"requested": True, "target_count": 3, "reached": 3, "complete": True},
            },
        }
        d, _calls = _recorder(monkeypatch, response=response)
        res = d.telemetry_reconfigure("all", publish={})
        assert res["publish"]["reached"] == 3
        assert res["publish"]["target_count"] == 3
        assert res["publish"]["complete"] is True

    def test_fanout_incomplete_coverage_visible(self, monkeypatch) -> None:
        """Недоставка части детей (reached < target_count) видна — «no silent caps»."""
        response = {
            "success": True,
            "result": {"publish": {"target_count": 3, "reached": 2, "complete": False}},
        }
        d, _calls = _recorder(monkeypatch, response=response)
        res = d.telemetry_reconfigure("all", publish={})
        assert res["publish"]["complete"] is False
        assert res["publish"]["reached"] < res["publish"]["target_count"]


class TestTelemetryReconfigureMode:
    """Task 1.1: driver прокидывает mode на провод только при merge (replace — бит-в-бит)."""

    def test_replace_default_omits_mode_on_wire(self, monkeypatch) -> None:
        """mode='replace' (дефолт) → telemetry_mode НЕ добавляется (прежний конверт)."""
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure("camera_0", publish={"metrics": {"fps": {"enabled": False}}})
        assert "telemetry_mode" not in calls[0][2]

    def test_merge_adds_mode_on_wire(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_reconfigure("camera_0", publish={"x": 1}, mode="merge")
        assert calls[0][2]["telemetry_mode"] == "merge"
        assert calls[0][2]["publish"] == {"x": 1}


class TestTelemetrySet:
    def test_publisher_enabled_builds_metric_override(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_set("camera_0", "fps", enabled=False)
        process, command, args = calls[0]
        # Task 1.4: адресный кейс → PM с target (транзит ради cap-детекции).
        assert (process, command) == ("ProcessManager", "telemetry.broadcast")
        # Task 1.1: telemetry_set обещает точечность → merge (сохраняет соседей).
        assert args == {
            "publish": {"metrics": {"fps": {"enabled": False}}},
            "telemetry_mode": "merge",
            "target": "camera_0",
        }

    def test_publisher_interval_only(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_set("camera_0", "latency_ms", interval_sec=5.0)
        assert calls[0][2] == {
            "publish": {"metrics": {"latency_ms": {"interval_sec": 5.0}}},
            "telemetry_mode": "merge",
            "target": "camera_0",
        }

    def test_publisher_enabled_and_interval(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_set("camera_0", "shm", enabled=True, interval_sec=10.0)
        assert calls[0][2] == {
            "publish": {"metrics": {"shm": {"enabled": True, "interval_sec": 10.0}}},
            "telemetry_mode": "merge",
            "target": "camera_0",
        }

    def test_publisher_requires_a_field(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        res = d.telemetry_set("camera_0", "fps")
        assert res["success"] is False
        assert calls == []

    def test_throttle_plane_builds_rule(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_set("all", "processes.**.state.fps", interval_sec=1.0, plane="throttle")
        process, command, args = calls[0]
        assert (process, command) == ("ProcessManager", "telemetry.broadcast")
        # Task 1.1: throttle-плоскость тоже merge (update_rule, не set_rules).
        assert args == {"throttle": {"processes.**.state.fps": 1.0}, "telemetry_mode": "merge"}

    def test_throttle_plane_requires_interval(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        res = d.telemetry_set("camera_0", "a.b", enabled=True, plane="throttle")
        assert res["success"] is False
        assert "interval_sec" in res["error"]
        assert calls == []

    def test_unknown_plane_is_error(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        res = d.telemetry_set("camera_0", "fps", enabled=True, plane="bogus")
        assert res["success"] is False
        assert calls == []

    def test_set_all_is_fanout(self, monkeypatch) -> None:
        d, calls = _recorder(monkeypatch)
        d.telemetry_set("all", "fps", enabled=False)
        assert calls[0][0] == "ProcessManager"
        assert calls[0][1] == "telemetry.broadcast"
