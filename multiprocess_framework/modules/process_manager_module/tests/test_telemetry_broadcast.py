# -*- coding: utf-8 -*-
"""PC 3.3: fan-out телеметрии на ВСЕХ детей + центральный троттл оркестратора.

Через conftest.make_pm (mock-компоненты) + communication-спай (как test_routing_epoch):
  - ``telemetry.broadcast {publish}`` → всем живым детям уходит ``telemetry.reconfigure``
    ТЕМ ЖЕ путём comm.broadcast, что routing.refresh; в результате виден охват;
  - ``publish=None`` — валидная команда «выключить gate у всех» — доезжает как под-секция;
  - ``throttle`` → применяется к ЦЕНТРАЛЬНОМУ ThrottleMiddleware оркестратора, детям НЕ шлётся;
  - нет state-plane → throttle.applied=False (виден «нет приёмника»);
  - после hot-swap (apply_topology) broadcast адресуется СВЕЖЕМУ набору детей;
  - общий примитив _broadcast_command строит корректный конверт и возвращает охват;
  - команда telemetry.broadcast зарегистрирована (introspect-видимость).
"""

from __future__ import annotations

from multiprocess_framework.modules.state_store_module.middleware.throttle import (
    ThrottleMiddleware,
)

from .conftest import make_pm


class _CommSpy:
    """Стаб communication: записывает broadcast'ы и возвращает заданный охват."""

    def __init__(self, reach: int = 0) -> None:
        self.broadcasts: list = []
        self.reach = reach

    def broadcast(self, message, exclude_self: bool = True) -> int:
        self.broadcasts.append((message, exclude_self))
        return self.reach


class _FakeStoreManager:
    """Минимальный StateStoreManager: держит живой ThrottleMiddleware по имени."""

    def __init__(self, throttle: ThrottleMiddleware) -> None:
        self._throttle = throttle

    def get_middleware(self, name: str):
        return self._throttle if name == "throttle" else None


class _FakeCommandManager:
    def __init__(self) -> None:
        self.handlers: dict = {}
        self.metadata: dict = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler
        self.metadata[name] = metadata or {}


def _pm(children: dict | None = None, *, reach: int = 0, throttle: ThrottleMiddleware | None = None):
    """PM с comm-спаем + опц. центральным троттлом + зарегистрированными детьми в PSR."""
    pm = make_pm(children or {})
    pm.communication = _CommSpy(reach=reach)
    # Дети видны через shared_resources.get_process_names (источник охвата fan-out).
    for name in children or {}:
        pm.shared_resources.register_process(name, {})
    if throttle is not None:
        pm._state_store_manager = _FakeStoreManager(throttle)
    return pm


def _telemetry_broadcasts(pm) -> list:
    return [m for m, _excl in pm.communication.broadcasts if m.get("command") == "telemetry.reconfigure"]


class TestPublishFanout:
    def test_publish_reaches_all_children(self) -> None:
        pm = _pm({"camera_0": {"class": "m.Cam"}, "detector": {"class": "m.Det"}}, reach=2)
        res = pm._cmd_telemetry_broadcast({"publish": {"metrics": {"fps": {"enabled": False}}}})

        assert res["success"] is True
        # Ровно один broadcast telemetry.reconfigure ушёл детям.
        bcasts = _telemetry_broadcasts(pm)
        assert len(bcasts) == 1
        msg = bcasts[0]
        assert msg["command"] == "telemetry.reconfigure"
        assert msg["type"] == "command"
        assert msg["sender"] == pm.name
        assert msg["queue_type"] == "system"
        assert msg["data"] == {"publish": {"metrics": {"fps": {"enabled": False}}}}
        # exclude_self=True — сам PM не переконфигурируется broadcast'ом.
        assert pm.communication.broadcasts[-1][1] is True
        # Охват виден: 2 цели, доставлено 2, полный.
        assert res["publish"]["target_count"] == 2
        assert res["publish"]["reached"] == 2
        assert res["publish"]["complete"] is True
        assert res["publish"]["targets"] == ["camera_0", "detector"]

    def test_publish_none_disables_gate_for_all(self) -> None:
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1)
        res = pm._cmd_telemetry_broadcast({"publish": None})
        assert res["success"] is True
        # publish=None доехал как валидная под-секция «выключить gate».
        assert _telemetry_broadcasts(pm)[0]["data"] == {"publish": None}

    def test_incomplete_coverage_is_visible(self) -> None:
        """reached < target_count → complete=False (наблюдаемость «no silent caps»)."""
        pm = _pm({"a": {"class": "m.A"}, "b": {"class": "m.B"}, "c": {"class": "m.C"}}, reach=2)
        res = pm._cmd_telemetry_broadcast({"publish": {}})
        assert res["publish"]["target_count"] == 3
        assert res["publish"]["reached"] == 2
        assert res["publish"]["complete"] is False


class TestThrottleToOrchestrator:
    def test_throttle_applied_to_central_middleware_not_broadcast(self) -> None:
        throttle = ThrottleMiddleware({"old.rule": 9.0})
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1, throttle=throttle)
        res = pm._cmd_telemetry_broadcast({"throttle": {"processes.**.state.fps": 2.0}})

        assert res["success"] is True
        assert res["throttle"] == {"requested": True, "applied": True}
        # set_rules ПОЛНОСТЬЮ заменяет набор (PC 0.1 семантика).
        assert throttle.rules == {"processes.**.state.fps": 2.0}
        # throttle НЕ рассылается детям — comm.broadcast не звали.
        assert _telemetry_broadcasts(pm) == []
        assert pm.communication.broadcasts == []

    def test_throttle_without_state_store_reports_no_receiver(self) -> None:
        pm = _pm({"camera_0": {"class": "m.Cam"}}, reach=1)  # без _state_store_manager
        res = pm._cmd_telemetry_broadcast({"throttle": {"a": 1.0}})
        assert res["success"] is True
        assert res["throttle"] == {"requested": True, "applied": False}


class TestBothPlanes:
    def test_publish_and_throttle_in_one_command(self) -> None:
        throttle = ThrottleMiddleware({})
        pm = _pm({"camera_0": {"class": "m.Cam"}, "detector": {"class": "m.Det"}}, reach=2, throttle=throttle)
        res = pm._cmd_telemetry_broadcast(
            {"publish": {"metrics": {"shm": {"enabled": False}}}, "throttle": {"p.q": 4.0}}
        )
        # publish разослан детям, throttle применён к оркестратору.
        assert res["publish"]["reached"] == 2
        assert res["throttle"]["applied"] is True
        assert throttle.rules == {"p.q": 4.0}
        assert _telemetry_broadcasts(pm)[0]["data"] == {"publish": {"metrics": {"shm": {"enabled": False}}}}


class TestValidation:
    def test_empty_command_is_error(self) -> None:
        pm = _pm({"camera_0": {"class": "m.Cam"}})
        res = pm._cmd_telemetry_broadcast({})
        assert res["success"] is False
        assert "publish" in res["reason"] or "throttle" in res["reason"]
        assert pm.communication.broadcasts == []


class TestAfterHotSwap:
    def test_broadcast_reaches_fresh_children_after_apply_topology(self) -> None:
        """После hot-swap fan-out адресуется СВЕЖЕМУ набору детей (актуальный PSR PM).

        apply_topology cleanup'ит старых (unregister_process) и provision'ит новых
        (register_process) → get_process_names отражает новый набор. Broadcast идёт
        тем же comm-путём, что и routing.refresh (PM держит свежие очереди) — так же
        надёжно долетает до пересозданных процессов.
        """
        pm = _pm({"camera_0": {"class": "m.Cam"}, "detector": {"class": "m.Det"}}, reach=2)
        new_bp = {
            "processes": [
                {"process_name": "cam_hd", "process_class": "m.CamHD"},
                {"process_name": "merger", "process_class": "m.Merge"},
            ]
        }
        result = pm.apply_topology(new_bp)
        assert result["success"] is True
        # Свежий PSR — новые дети.
        assert sorted(pm.shared_resources.get_process_names()) == ["cam_hd", "merger"]

        # Отбрасываем routing.refresh-рассылки switch'а, меряем только telemetry.
        pm.communication.broadcasts.clear()
        res = pm._cmd_telemetry_broadcast({"publish": {}})

        assert res["publish"]["targets"] == ["cam_hd", "merger"]
        assert res["publish"]["target_count"] == 2
        assert len(_telemetry_broadcasts(pm)) == 1


class TestBroadcastPrimitive:
    def test_broadcast_command_builds_envelope_and_returns_reach(self) -> None:
        pm = _pm({"a": {"class": "m.A"}}, reach=3)
        count = pm._broadcast_command("custom.cmd", {"k": "v"})
        assert count == 3
        msg, exclude = pm.communication.broadcasts[-1]
        assert msg == {
            "type": "command",
            "command": "custom.cmd",
            "sender": pm.name,
            "queue_type": "system",
            "data": {"k": "v"},
        }
        assert exclude is True

    def test_broadcast_command_no_comm_is_noop(self) -> None:
        pm = make_pm({})  # без communication
        pm.communication = None
        assert pm._broadcast_command("x", {}) == 0


class TestRegistration:
    def test_telemetry_broadcast_registered_with_description(self) -> None:
        pm = make_pm({})
        pm.command_manager = _FakeCommandManager()
        pm._register_builtin_commands()
        assert "telemetry.broadcast" in pm.command_manager.handlers
        # Description непустой → introspect.capabilities/handlers покажет команду.
        assert pm.command_manager.metadata["telemetry.broadcast"]["description"]
        # Handler — это _cmd_telemetry_broadcast.
        assert pm.command_manager.handlers["telemetry.broadcast"] == pm._cmd_telemetry_broadcast
