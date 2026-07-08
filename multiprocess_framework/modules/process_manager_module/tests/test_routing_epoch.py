"""Ф3.1 (routing-epoch): PM bump epoch/incarnation + broadcast routing.refresh.

Через conftest.make_pm/wire_planner (mock-компоненты) + communication-стаб,
записывающий рассылки. Проверяет: switch → ровно один refresh (epoch==1,
incarnation новых bump'нуты), повторный switch → epoch==2, rollback → refresh
уходит, provision поднимает incarnation, env FW_ROUTING_REFRESH=0 глушит рассылку.
"""

import os

from .conftest import make_pm, wire_planner


class _CommSpy:
    """Стаб communication: записывает broadcast'ы routing.refresh."""

    def __init__(self) -> None:
        self.broadcasts: list = []

    def broadcast(self, message, exclude_self: bool = True) -> int:
        self.broadcasts.append((message, exclude_self))
        return 1


def _pm_with_comm(configs: dict | None = None, **kw):
    pm = make_pm(configs or {}, **kw)
    pm.communication = _CommSpy()
    return pm


def _refreshes(pm) -> list:
    return [m for m, _excl in pm.communication.broadcasts if m.get("command") == "routing.refresh"]


class TestSwitchBroadcast:
    def test_switch_broadcasts_one_refresh_epoch1(self) -> None:
        pm = _pm_with_comm({"camera_0": {"class": "m.Cam"}, "detector": {"class": "m.Det"}})
        new_bp = {
            "processes": [
                {"process_name": "cam_hd", "process_class": "m.CamHD"},
                {"process_name": "merger", "process_class": "m.Merge"},
            ]
        }
        result = pm.apply_topology(new_bp)
        assert result["success"] is True

        refreshes = _refreshes(pm)
        assert len(refreshes) == 1, f"ожидался ровно один refresh, было {len(refreshes)}"
        data = refreshes[0]["data"]
        assert data["epoch"] == 1
        assert pm._routing_epoch == 1
        assert result.get("routing_epoch") == 1
        # Новые процессы провижинились → incarnation поднята.
        assert pm._incarnations.get("cam_hd") == 1
        assert pm._incarnations.get("merger") == 1
        # Снимок в payload несёт их incarnation.
        procs = data["processes"]
        assert procs.get("cam_hd", {}).get("incarnation") == 1
        assert procs.get("merger", {}).get("incarnation") == 1

    def test_second_switch_epoch2(self) -> None:
        pm = _pm_with_comm({"camera_0": {"class": "m.Cam"}})
        pm.apply_topology({"processes": [{"process_name": "a", "process_class": "m.A"}]})
        wire_planner(pm)
        r2 = pm.apply_topology({"processes": [{"process_name": "b", "process_class": "m.B"}]})
        assert r2["success"] is True
        assert pm._routing_epoch == 2
        assert r2.get("routing_epoch") == 2
        assert len(_refreshes(pm)) == 2

    def test_no_broadcast_when_disabled_by_env(self) -> None:
        pm = _pm_with_comm({"camera_0": {"class": "m.Cam"}})
        old = os.environ.get("FW_ROUTING_REFRESH")
        os.environ["FW_ROUTING_REFRESH"] = "0"
        try:
            result = pm.apply_topology({"processes": [{"process_name": "x", "process_class": "m.X"}]})
        finally:
            if old is None:
                os.environ.pop("FW_ROUTING_REFRESH", None)
            else:
                os.environ["FW_ROUTING_REFRESH"] = old
        assert result["success"] is True
        # Epoch всё равно поднялся (истина у PM), но рассылки нет.
        assert pm._routing_epoch == 1
        assert _refreshes(pm) == []


class TestRollbackBroadcast:
    def test_rollback_broadcasts_refresh(self) -> None:
        pm = _pm_with_comm({"worker": {"class": "m.W"}})
        pm._process_registry._fail_on_create = {"bad_proc"}
        wire_planner(pm)
        r = pm.apply_topology({"processes": [{"process_name": "bad_proc", "process_class": "m.Bad"}]})
        assert r["success"] is False
        assert r["rolled_back"] is True
        # Rollback пересоздаёт очереди → refresh обязан уйти.
        refreshes = _refreshes(pm)
        assert len(refreshes) >= 1
        assert refreshes[-1]["data"]["reason"] == "rollback"


class TestProvisionIncarnation:
    def test_provision_bumps_incarnation(self) -> None:
        pm = _pm_with_comm({})
        # routing-состояние в mock-PM ленивое (make_pm патчит __init__).
        assert getattr(pm, "_incarnations", {}).get("proc_a", 0) == 0
        pm._topology_provision("proc_a", {"class": "m.P", "queues": {"data": {"maxsize": 5}}})
        assert pm._incarnations.get("proc_a") == 1
        pm._topology_provision("proc_a", {"class": "m.P", "queues": {"data": {"maxsize": 5}}})
        assert pm._incarnations.get("proc_a") == 2
