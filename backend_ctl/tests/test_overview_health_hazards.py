# -*- coding: utf-8 -*-
"""Авторские hazard-тесты чтения health в ``system_overview`` (Ф1 Task 1.5).

Что может сломаться именно в ЭТОМ механизме, given как он построен:
чтение ЧУЖОЙ самопубликации из state-поддерева. Опасности: ветки может не быть
(старый бэкенд / health ещё не публиковался) — отсутствие показания нельзя
выдавать ни за «здоров», ни за аномалию; форма может разойтись (не-dict) —
сводка, первая команда сессии, не имеет права упасть; статус и счётчик —
НЕЗАВИСИМЫЕ сигналы (живой замер стенда Б: errors=1 при status=ok) и обязаны
давать РАЗНЫЕ аномалии, не склеиваться.
"""

from __future__ import annotations

from backend_ctl.driver import BackendDriver
from backend_ctl.tests.test_error_plane_one_connector_overview_health_anomaly_acceptance import (
    _fake_backend_with_health,
)
from backend_ctl.tests.test_overview import _healthy_responses


def _health_anomalies(res):
    return [a for a in res["anomalies"] if "health" in str(a.get("kind", ""))]


class TestHealthBranchAbsence:
    def test_absent_health_branch_keeps_card_and_anomalies_untouched(self, monkeypatch) -> None:
        """Нет ветки → ни ключа ``health`` в карточке, ни health-аномалий (не «здоров», а «нет показания»)."""
        d = BackendDriver()
        _fake_backend_with_health(monkeypatch, d, procs=["cam"], responses=_healthy_responses(), health=None)
        res = d.system_overview()
        assert "health" not in res["processes"]["cam"], res["processes"]["cam"]
        assert _health_anomalies(res) == [], res["anomalies"]

    def test_process_node_that_is_not_a_dict_does_not_kill_the_overview(self, monkeypatch) -> None:
        """Узел процесса не-dict → сводка живёт (major 2 ревью: guard был без теста, его снятие роняло всё)."""
        d = BackendDriver()

        def fake_send(target, command, args=None, *, timeout=None):
            if command == "state.get_subtree":
                return {"success": True, "result": {"subtree": {"cam": "строка вместо узла"}}}
            return _healthy_responses().get(command, {"success": False, "error": "нет ответа (fake)"})

        monkeypatch.setattr(d, "send_command", fake_send)
        res = d.system_overview()
        assert res["success"] is True
        assert "health" not in res["processes"]["cam"]
        assert _health_anomalies(res) == []

    def test_crashed_section_does_not_swallow_health(self, monkeypatch) -> None:
        """Секция упала (raise из fan-out) → health всё равно назван (major 1 ревью).

        Показание health уже в руках (state-поддерево получено ДО fan-out); упавший
        сбор секции — своя аномалия ``introspect_failed``, но глушить чужое показание
        он не имеет права — это тот же дефект «спросили, получили и выбросили».
        """
        d = BackendDriver()
        _fake_backend_with_health(
            monkeypatch,
            d,
            procs=["cam"],
            responses=_healthy_responses(),
            health={
                "cam": {
                    "status": "ok",
                    "errors": 1,
                    "last_error": {
                        "type": "DeviceOpenFailed",
                        "message": "не удалось открыть камеру 7",
                        "context": "capture.start",
                        "ts": 1.0,
                    },
                    "degraded_reason": None,
                }
            },
        )
        monkeypatch.setattr(
            d, "worker_status", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("разрыв соединения"))
        )
        res = d.system_overview()
        kinds = sorted(a["kind"] for a in res["anomalies"])
        assert "introspect_failed" in kinds, res["anomalies"]
        assert "health_errors" in kinds, res["anomalies"]
        assert res["processes"]["cam"]["health"] == {"status": "ok", "errors": 1}

    def test_malformed_health_branch_does_not_crash_the_first_command_of_a_session(self, monkeypatch) -> None:
        """health не-dict (разошлась форма) → сводка живёт, health-аномалий нет."""
        d = BackendDriver()
        sent = []

        def fake_send(target, command, args=None, *, timeout=None):
            sent.append(command)
            if command == "state.get_subtree":
                return {"success": True, "result": {"subtree": {"cam": {"health": "оборванная строка"}}}}
            return _healthy_responses().get(command, {"success": False, "error": "нет ответа (fake)"})

        monkeypatch.setattr(d, "send_command", fake_send)
        res = d.system_overview()
        assert res["success"] is True
        assert "health" not in res["processes"]["cam"]
        assert _health_anomalies(res) == []


class TestStatusAndErrorsAreIndependentSignals:
    def test_degraded_with_errors_yields_both_anomalies(self, monkeypatch) -> None:
        d = BackendDriver()
        _fake_backend_with_health(
            monkeypatch,
            d,
            procs=["cam"],
            responses=_healthy_responses(),
            health={
                "cam": {
                    "status": "degraded",
                    "errors": 3,
                    "last_error": {"type": "DeviceOpenFailed", "message": "m", "context": "c", "ts": 1.0},
                    "degraded_reason": "breaker open",
                }
            },
        )
        res = d.system_overview()
        kinds = sorted(a["kind"] for a in _health_anomalies(res))
        assert kinds == ["health_degraded", "health_errors"], res["anomalies"]

    def test_card_carries_compact_health_when_branch_present(self, monkeypatch) -> None:
        d = BackendDriver()
        _fake_backend_with_health(
            monkeypatch,
            d,
            procs=["cam"],
            responses=_healthy_responses(),
            health={"cam": {"status": "ok", "errors": 0, "last_error": None, "degraded_reason": None}},
        )
        res = d.system_overview()
        assert res["processes"]["cam"]["health"] == {"status": "ok", "errors": 0}

    def test_failed_status_names_its_own_kind(self, monkeypatch) -> None:
        """kind строится из статуса (health_failed ≠ health_degraded): оператор различает без чтения detail."""
        d = BackendDriver()
        _fake_backend_with_health(
            monkeypatch,
            d,
            procs=["cam"],
            responses=_healthy_responses(),
            health={"cam": {"status": "failed", "errors": 0, "last_error": None, "degraded_reason": "give-up"}},
        )
        res = d.system_overview()
        assert [a["kind"] for a in _health_anomalies(res)] == ["health_failed"], res["anomalies"]
