"""Ф3.5 (wire-статусы first-class): re-issue при рестарте + honest broken_wires.

Через conftest.make_pm (mock-компоненты) + spy на send_message/communication.
Проверяет:
- _mark_wires_broken_for / _reissue_wires_for — прямые helper'ы (guard'ы, роли);
- restart_process переигрывает wire.configure в новый инстанс, провод снова active;
- ProcessMonitor._publish_wires — broken при мёртвом endpoint, 0 при живой топологии;
- feature-флаг wire_reissue_enabled=False отключает re-issue (откат к старому поведению).
"""

from unittest.mock import MagicMock

from ..monitor.process_monitor import ProcessMonitor
from .conftest import make_pm


class _CommSpy:
    """Стаб communication: считает broadcast'ы (нужен _broadcast_routing_refresh)."""

    def __init__(self) -> None:
        self.broadcasts: list = []

    def broadcast(self, message, exclude_self: bool = True) -> int:
        self.broadcasts.append((message, exclude_self))
        return 1


def _pm_with_wire(*, wire: dict | None = None, configs: dict | None = None):
    """PM с одним wire-проводом, spy на send_message и communication."""
    pm = make_pm(configs or {"cam": {"class": "x.Cam", "priority": "normal"}})
    pm.communication = _CommSpy()
    pm.send_message = MagicMock()
    if wire is not None:
        pm._active_wires = dict(wire)
    return pm


def _wire(source="cam", target="proc", status="active"):
    return {
        "cam→proc": {
            "source_process": source,
            "target_process": target,
            "transport": "router",
            "shm_config": {"shm_name": "frames", "buffer_slots": 4, "owner_process": source},
            "status": status,
        }
    }


# ---------------------------------------------------------------------------
# Helper'ы напрямую
# ---------------------------------------------------------------------------


class TestReissueHelpers:
    def test_mark_broken_touches_matching_wire(self) -> None:
        pm = _pm_with_wire(wire=_wire(source="cam", target="proc"))
        pm._mark_wires_broken_for("cam")
        assert pm._active_wires["cam→proc"]["status"] == "broken"

    def test_mark_broken_ignores_unrelated_process(self) -> None:
        pm = _pm_with_wire(wire=_wire(source="cam", target="proc"))
        pm._mark_wires_broken_for("other")
        assert pm._active_wires["cam→proc"]["status"] == "active"

    def test_reissue_sends_configure_sender_role(self) -> None:
        pm = _pm_with_wire(wire=_wire(source="cam", target="proc"))
        reissued = pm._reissue_wires_for("cam")
        assert reissued == 1
        pm.send_message.assert_called_once()
        target_name, cmd = pm.send_message.call_args[0]
        assert target_name == "cam"
        assert cmd["command"] == "wire.configure"
        assert cmd["data"]["role"] == "sender"
        assert cmd["data"]["shm_name"] == "frames"
        assert pm._active_wires["cam→proc"]["status"] == "active"

    def test_reissue_receiver_role_for_target(self) -> None:
        pm = _pm_with_wire(wire=_wire(source="cam", target="proc"))
        pm._reissue_wires_for("proc")
        _, cmd = pm.send_message.call_args[0]
        assert cmd["data"]["role"] == "receiver"

    def test_reissue_empty_wires_is_noop(self) -> None:
        pm = _pm_with_wire(wire={})
        assert pm._reissue_wires_for("cam") == 0
        pm.send_message.assert_not_called()

    def test_reissue_send_failure_leaves_broken(self) -> None:
        pm = _pm_with_wire(wire=_wire(source="cam", target="proc", status="broken"))
        pm.send_message.side_effect = RuntimeError("dead queue")
        assert pm._reissue_wires_for("cam") == 0
        assert pm._active_wires["cam→proc"]["status"] == "broken"


# ---------------------------------------------------------------------------
# restart_process end-to-end (broken → re-issue → active)
# ---------------------------------------------------------------------------


class TestRestartReissue:
    def test_restart_reissues_wire_to_new_instance(self) -> None:
        pm = _pm_with_wire(wire=_wire(source="cam", target="proc"))
        ok = pm.restart_process("cam")
        assert ok is True
        # wire.configure ушёл в перезапущенный инстанс cam (role=sender)
        configure_calls = [
            c for c in pm.send_message.call_args_list
            if c[0][1].get("command") == "wire.configure" and c[0][0] == "cam"
        ]
        assert len(configure_calls) == 1
        assert configure_calls[0][0][1]["data"]["role"] == "sender"
        # Итоговый статус — снова active (broken в окне рестарта → active после re-issue)
        assert pm._active_wires["cam→proc"]["status"] == "active"

    def test_restart_disabled_flag_skips_reissue(self) -> None:
        pm = _pm_with_wire(wire=_wire(source="cam", target="proc"))
        base_get_config = pm.get_config

        def _cfg(key):
            if key == "wire_reissue_enabled":
                return False
            return base_get_config(key)

        pm.get_config = _cfg
        pm.restart_process("cam")
        # Флаг off → wire.configure НЕ отправлялся, статус не менялся
        assert not any(
            c[0][1].get("command") == "wire.configure" for c in pm.send_message.call_args_list
        )
        assert pm._active_wires["cam→proc"]["status"] == "active"

    def test_restart_unrelated_wire_untouched(self) -> None:
        pm = _pm_with_wire(
            wire=_wire(source="other_a", target="other_b"),
            configs={"cam": {"class": "x.Cam", "priority": "normal"}},
        )
        pm.restart_process("cam")
        # Провод не задевает cam → не переигрывается, остаётся active
        assert pm._active_wires["cam→proc"]["status"] == "active"
        assert not any(
            c[0][1].get("command") == "wire.configure" for c in pm.send_message.call_args_list
        )


# ---------------------------------------------------------------------------
# ProcessMonitor: honest broken_wires + system.wires.*
# ---------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, alive: bool) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


class _FakeRegistry:
    def __init__(self, alive_map: dict) -> None:
        self._procs = {n: _FakeProc(a) for n, a in alive_map.items()}

    def get_process_by_name(self, name: str):
        return self._procs.get(name)


def _monitor_with_wires(wires: dict, alive: dict | None = None) -> tuple[ProcessMonitor, dict]:
    """ProcessMonitor + захват публикаций; ``alive`` — карта {process: is_alive}."""
    published: dict = {}
    pm = MagicMock()
    pm.name = "ProcessManager"
    pm._active_wires = wires
    pm._process_registry = _FakeRegistry(alive or {})
    pm.worker_manager.create_worker = lambda *a, **kw: None

    ssm = MagicMock()

    def _set(payload):
        d = payload["data"]
        published[d["path"]] = d["value"]

    ssm.handle_state_set.side_effect = _set
    ssm.handle_state_get.return_value = {"status": "error"}
    pm._state_store_manager = ssm

    return ProcessMonitor(pm), published


class TestBrokenWiresMonitor:
    def test_broken_when_target_dead(self) -> None:
        wires = _wire(source="cam", target="proc")
        # cam жив, proc мёртв (is_alive False) → провод broken
        monitor, published = _monitor_with_wires(wires, alive={"cam": True, "proc": False})
        monitor._publish_health({"cam": {"status": "running"}})
        assert published["system.health.broken_wires"] == 1
        assert published["system.wires.cam→proc.status"] == "broken"

    def test_zero_when_all_alive(self) -> None:
        wires = _wire(source="cam", target="proc")
        monitor, published = _monitor_with_wires(wires, alive={"cam": True, "proc": True})
        monitor._publish_health({"cam": {"status": "running"}, "proc": {"status": "running"}})
        assert published["system.health.broken_wires"] == 0
        assert published["system.wires.cam→proc.status"] == "active"

    def test_explicit_broken_status_counted(self) -> None:
        wires = _wire(source="cam", target="proc", status="broken")
        # Оба endpoint'а живы, но статус помечен broken (окно рестарта) → broken
        monitor, published = _monitor_with_wires(wires, alive={"cam": True, "proc": True})
        monitor._publish_health({"cam": {"status": "running"}, "proc": {"status": "running"}})
        assert published["system.health.broken_wires"] == 1

    def test_alive_process_stale_status_not_broken(self) -> None:
        """Живой (is_alive) процесс со stale-статусом 'stopped' — НЕ broken endpoint.

        Регресс: liveness через status-снимок ложно держал провод broken после
        restart (монитор не промотировал stopped→running). Теперь истина — is_alive.
        """
        wires = _wire(source="cam", target="proc")
        monitor, published = _monitor_with_wires(wires, alive={"cam": True, "proc": True})
        # all_states отдаёт stale 'stopped' для proc, но is_alive=True → active
        monitor._publish_health({"cam": {"status": "running"}, "proc": {"status": "stopped"}})
        assert published["system.health.broken_wires"] == 0
        assert published["system.wires.cam→proc.status"] == "active"

    def test_no_wires_healthy_zero(self) -> None:
        monitor, published = _monitor_with_wires({})
        monitor._publish_health({"cam": {"status": "running"}})
        assert published["system.health.broken_wires"] == 0
