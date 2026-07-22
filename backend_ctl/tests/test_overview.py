# -*- coding: utf-8 -*-
"""Тесты B.3: system_overview — компактная сводка + anomalies на подставных счётчиках.

Acceptance плана: сводка компактна; аномалии детектятся на fake-ответах;
ноль новых IPC-команд (fan-out только существующими ручками).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from backend_ctl.driver import BackendDriver


from backend_ctl.tests.conftest import (  # noqa: E402 — общие хелперы
    ROUTER_COUNTERS,
    full_router_stats,
)
from backend_ctl.tests.conftest import wire_line as _line  # noqa: E402 — общий хелпер


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
        "introspect.router_stats": {"success": True, "router_stats": full_router_stats()},
        "introspect.queues": {"success": True, "queue_sizes": {"system": 1, "data": 2}},
        "introspect.memory": {
            "success": True,
            "memory": {},
            "pool": {},
            "queues": {},
            "shm_registry": {},
            "os": {"rss": 12345, "vms": 23456, "pid": 1},
        },
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
            "router_stats": full_router_stats(sent_ok=5, received=9, middleware_dropped=3, errors=1),
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

    def test_missing_router_stats_is_loud_not_zero(self, monkeypatch) -> None:
        """Ручка ответила успехом, но без секции счётчиков → counter_missing.

        Плечо «OFF» пары: раньше такой ответ давал ``sent_ok=0`` и НИ ОДНОЙ аномалии
        — «0 и тишина», неотличимое от доказанного «трафика не было».
        """
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.router_stats"] = {"success": True, "process": "cam"}  # секции нет
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()

        hits = [a for a in res["anomalies"] if a["kind"] == "counter_missing"]
        assert hits, "отсутствие счётчиков обязано быть слышно"
        assert hits[0]["process"] == "cam"
        assert "sent_ok" in hits[0]["detail"]
        assert "ручка ответила" in hits[0]["detail"], "причина обязана отличать «не ответила» от «форма разошлась»"

        card = res["processes"]["cam"]
        assert card["router"]["sent_ok"] is None, "нет показания ≠ ноль"
        assert card["missing"] == {"router": list(ROUTER_COUNTERS)}

    def test_healthy_shape_has_no_missing_key(self, monkeypatch) -> None:
        """Плечо «ON» той же пары: полная форма → ни аномалии, ни ключа missing."""
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=_healthy_responses())
        res = d.system_overview()
        assert not [a for a in res["anomalies"] if a["kind"] == "counter_missing"]
        assert "missing" not in res["processes"]["cam"], "шум в здоровой сводке недопустим"
        assert res["processes"]["cam"]["router"]["sent_ok"] == 10

    def test_missing_queue_sizes_flagged(self, monkeypatch) -> None:
        """Пустые очереди и отсутствующая секция очередей — разные факты."""
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.queues"] = {"success": True, "process": "cam"}
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        hits = [a for a in res["anomalies"] if a["kind"] == "counter_missing"]
        assert hits and "queue_sizes" in hits[0]["detail"]
        assert res["processes"]["cam"]["queues"] is None

    def test_none_counters_do_not_crash_thresholds(self, monkeypatch) -> None:
        """Пороговые проверки None-safe: сводка обязана собраться, а не упасть.

        До строгого края ``rs.middleware_dropped > 0`` было сравнением int'а;
        с ``None`` оно бросило бы TypeError и убило первую команду сессии.
        """
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.router_stats"] = {"success": True, "router_stats": {"sent_ok": 3}}
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        assert res["success"] is True
        kinds = {a["kind"] for a in res["anomalies"]}
        assert "router_dropped" not in kinds, "None — не превышение порога"
        assert "router_errors" not in kinds
        assert "counter_missing" in kinds

    def test_memory_failure_flags_process(self, monkeypatch) -> None:
        """Отказ introspect.memory — тоже introspect_failed, а не тихий memory_ok=False.

        Ревью фазы B: mem.ok выпадал из агрегата ok — агент, читающий только
        ok/anomalies, считал процесс здоровым при сломанном memory-канале.
        """
        d = BackendDriver()
        responses = _healthy_responses()
        del responses["introspect.memory"]
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        assert res["processes"]["cam"]["ok"] is False
        hits = [a for a in res["anomalies"] if a["kind"] == "introspect_failed"]
        assert hits and "memory" in hits[0]["detail"]


class TestEffectiveHz:
    """Task 3.2 — effective_hz per-process в сводке + аномалия hz_degraded (пара ON/OFF)."""

    @staticmethod
    def _status_with_workers(workers: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True, "process": "cam", "status": "running", "workers": workers}

    def test_effective_hz_surfaces_in_card(self, monkeypatch) -> None:
        """Ведущий темп процесса виден в карточке — не теряется при схлопывании воркеров."""
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.status"] = self._status_with_workers(
            {"fast": {"status": "running", "effective_hz": 21.3}, "slow": {"status": "running", "effective_hz": 0.5}}
        )
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        assert res["processes"]["cam"]["hz"] == 21.3  # максимум по воркерам — ведущий темп
        assert not [a for a in res["anomalies"] if a["kind"] == "hz_degraded"]

    def test_hz_degraded_flagged_below_target(self, monkeypatch) -> None:
        """ON-плечо: effective_hz ниже доли target → hz_degraded с названным воркером."""
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.status"] = self._status_with_workers(
            {"w1": {"status": "running", "effective_hz": 5.0, "target_interval_ms": 33.0}}  # target ~30 Гц, 5 < 15
        )
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        hits = [a for a in res["anomalies"] if a["kind"] == "hz_degraded"]
        assert hits and hits[0]["process"] == "cam"
        assert "w1" in hits[0]["detail"]

    def test_hz_at_target_not_flagged(self, monkeypatch) -> None:
        """OFF-плечо той же пары: темп у цели → карточка несёт hz, аномалии нет."""
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.status"] = self._status_with_workers(
            {"w1": {"status": "running", "effective_hz": 25.0, "target_interval_ms": 33.0}}  # 25 >= 15
        )
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        assert res["processes"]["cam"]["hz"] == 25.0
        assert not [a for a in res["anomalies"] if a["kind"] == "hz_degraded"]

    def test_hz_without_target_not_judged(self, monkeypatch) -> None:
        """Воркер без target порогом не судится: hz в карточке есть, hz_degraded — нет."""
        d = BackendDriver()
        responses = _healthy_responses()
        responses["introspect.status"] = self._status_with_workers(
            {"w1": {"status": "running", "effective_hz": 0.1}}  # медленно, но не с чем сравнить
        )
        _fake_backend(monkeypatch, d, procs=["cam"], responses=responses)
        res = d.system_overview()
        assert res["processes"]["cam"]["hz"] == 0.1
        assert not [a for a in res["anomalies"] if a["kind"] == "hz_degraded"]

    def test_no_hz_reported_is_none(self, monkeypatch) -> None:
        """Воркер без effective_hz → hz=None (running-процесс без темпа — сам по себе сигнал)."""
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=_healthy_responses())
        res = d.system_overview()
        assert res["processes"]["cam"]["hz"] is None

    def test_seven_process_summary_under_byte_cap(self, monkeypatch) -> None:
        """Приёмка: свод 7 процессов с воркерами+hz остаётся под RESPONSE_BYTE_CAP."""
        from backend_ctl.mcp_tools import RESPONSE_BYTE_CAP

        procs = [f"proc_{i}" for i in range(7)]
        responses = _healthy_responses()
        responses["introspect.status"] = self._status_with_workers(
            {"capture": {"status": "running", "effective_hz": 21.3, "target_interval_ms": 33.0}}
        )
        _fake_backend(monkeypatch, d := BackendDriver(), procs=procs, responses=responses)
        res = d.system_overview()
        assert all("hz" in res["processes"][p] for p in procs)
        payload = json.dumps(res, ensure_ascii=False).encode("utf-8")
        assert len(payload) < RESPONSE_BYTE_CAP, f"свод {len(payload)}Б превысил cap {RESPONSE_BYTE_CAP}"


class TestOverviewResilience:
    """Task 5.3 — сводка не падает целиком и не помнит старые беды вечно."""

    def test_throwing_process_does_not_kill_whole_overview(self, monkeypatch) -> None:
        """Исключение по ОДНОМУ процессу → у него error-секция, остальные собраны.

        Контракт модуля — best-effort, но raise внутри пула (разрыв связи, кривой ответ)
        пробивался через pool.map и ронял ВЕСЬ overview: первая команда сессии падала
        целиком из-за одного больного процесса.
        """
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam", "плохой"], responses=_healthy_responses())

        healthy_worker_status = d.worker_status

        def boom(proc: str, **kw: Any) -> Any:
            if proc == "плохой":
                raise ConnectionError("процесс не отвечает")
            return healthy_worker_status(proc, **kw)

        monkeypatch.setattr(d, "worker_status", boom)
        res = d.system_overview()

        assert res["success"] is True, "сводка обязана собраться, несмотря на больной процесс"
        assert res["processes"]["cam"]["status"] == "running", "здоровый процесс обязан быть собран"
        bad = res["processes"]["плохой"]
        assert bad["ok"] is False
        assert "ConnectionError" in bad["error"], "причина обязана быть названа, а не проглочена"
        assert any(a["kind"] == "introspect_failed" and a.get("process") == "плохой" for a in res["anomalies"])

    def test_cumulative_counter_flags_once_not_forever(self, monkeypatch) -> None:
        """Счётчик тикнул один раз → аномалия в первой сводке, но не во второй.

        Счётчики driver'а кумулятивны: раньше одна давняя ошибка светилась в КАЖДОЙ
        последующей сводке, и свежая беда была неотличима от старого шрама.
        """
        d = BackendDriver()
        _fake_backend(monkeypatch, d, procs=["cam"], responses=_healthy_responses())

        d._late_replies = 2  # подставной счётчик driver'а
        first = d.system_overview()
        assert any(a["kind"] == "late_replies" for a in first["anomalies"]), "первый раз обязан быть виден"
        assert first["driver"]["late_replies"] == 2, "lifetime-значение обязано остаться в ответе"
        assert first["driver"]["deltas"]["late_replies"] == 2

        second = d.system_overview()
        assert not any(a["kind"] == "late_replies" for a in second["anomalies"]), (
            "старый шрам не должен светиться снова"
        )
        assert second["driver"]["late_replies"] == 2, "lifetime-значение никуда не девается"
        assert second["driver"]["deltas"]["late_replies"] == 0

        d._late_replies = 5  # новая беда — снова видна
        third = d.system_overview()
        assert any(a["kind"] == "late_replies" for a in third["anomalies"]), "прирост обязан снова поднять аномалию"
        assert third["driver"]["deltas"]["late_replies"] == 3
