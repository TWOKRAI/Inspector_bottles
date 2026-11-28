# ruff: noqa — материал разбора, не код проекта
"""R2 investigator probes (throwaway). Real RobotDriverV2 + real DeviceHubPlugin on fakes; real StateStoreManager."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from Services.device_hub.tests.test_c29_probe import _Rig, _DEV, _TLM0
from Services.device_hub.tests.test_robot_v2_t53g_windows import _Barrier, _bounded, driver_scope  # noqa: F401
from Services.robot_comm.core.protocol_v2 import REG


def _connect(rig):
    assert rig.cmd("connect")["status"] == "ok"
    _bounded(rig.plugin._process_conn_queue, 5.0, "connect")
    assert rig.drv.is_connected and rig.drv.desired_connected


def _drop_link_robot_reset(rig):
    rig.transport.is_connected = False
    rig.transport.tlm[REG["TLM_SERVO"] - _TLM0] = 0
    rig.transport.tlm[REG["TLM_DO_MASK"] - _TLM0] = 0


def _hook_tcp(rig):
    rig.transport.on_connect = lambda: rig.events.append("tcp_open")
    rig.transport.on_disconnect = lambda: rig.events.append("tcp_close")


def test_c38_window(tmp_path, monkeypatch):
    rig = _Rig(tmp_path, monkeypatch, servo_tlm=0, do_on=True)
    barrier = _Barrier()
    try:
        _connect(rig)
        _hook_tcp(rig)
        _drop_link_robot_reset(rig)
        real = rig.drv._record_reconnect

        def paused():  # between desired check B (driver.py:523) and connect_begin (state.py:331)
            barrier.pause_if_t1()
            real()

        rig.drv._record_reconnect = paused
        box = {}
        t1 = threading.Thread(target=lambda: box.update(snap=rig.drv.tick()), name="c38-tick", daemon=True)
        barrier.t1 = t1
        t1.start()
        assert barrier.entered.wait(5.0), "window not reached"
        soft0, servo0 = rig.client.soft_count(), list(rig.client.servo_calls)
        print("\nC38 cmd disconnect:", rig.cmd("disconnect"))
        _bounded(rig.plugin._process_conn_queue, 5.0, "disconnect")
        print(
            "C38 after full disconnect: pending=",
            rig.drv.disconnect_pending,
            "desired=",
            rig.drv.desired_connected,
            "conn_snapshot=",
            rig.plugin._conn_snapshot.get(_DEV),
        )
        mark = len(rig.events)
        barrier.release.set()
        t1.join(10.0)
        assert not t1.is_alive()
        print("C38 events after disconnect finished:", rig.events[mark:])
        print(
            "C38 servo writes after:",
            rig.client.servo_calls[len(servo0) :],
            "SOFT after:",
            rig.client.soft_count() - soft0,
        )
        print(
            "C38 TLM_SERVO now:",
            rig.transport.tlm[REG["TLM_SERVO"] - _TLM0],
            "transport open:",
            rig.transport.is_connected,
            "drv.is_connected:",
            rig.drv.is_connected,
            "conn_snapshot:",
            rig.plugin._conn_snapshot.get(_DEV),
        )
    finally:
        barrier.release.set()
        rig.close()


def test_operator_servo_off_then_link_blip(tmp_path, monkeypatch):
    rig = _Rig(tmp_path, monkeypatch, servo_tlm=0, do_on=False)
    try:
        _connect(rig)
        cmd = rig.plugin.commands["robot_servo"]
        print("\nSERVO-OFF cmd:", getattr(rig.plugin, cmd)({"device_id": _DEV, "on": False}))
        print("SERVO-OFF TLM_SERVO:", rig.transport.tlm[REG["TLM_SERVO"] - _TLM0])
        n = len(rig.client.servo_calls)
        rig.transport.is_connected = False  # link blip; controller keeps servo OFF
        _bounded(rig.drv.tick, 5.0, "tick")
        print(
            "SERVO-OFF writes by reconnect tick:",
            rig.client.servo_calls[n:],
            "TLM_SERVO now:",
            rig.transport.tlm[REG["TLM_SERVO"] - _TLM0],
            "connected:",
            rig.drv.is_connected,
        )
    finally:
        rig.close()


def test_v1_commands_on_v2_and_inventory(tmp_path, monkeypatch):
    from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2

    rig = _Rig(tmp_path, monkeypatch, servo_tlm=1, do_on=False)
    try:
        _connect(rig)
        robot_cmds = sorted(c for c in rig.plugin.commands if c.startswith("robot_"))
        v2 = set(RobotDriverV2._OPS)
        print("\nINV robot_* commands:", len(robot_cmds))
        print("INV v2 ops:", sorted(v2))
        print("INV commands not served by v2:", [c for c in robot_cmds if c[6:] not in v2])
        print(
            "INV executors:",
            {
                c: rig.plugin.command_options(c).get("executor")
                for c in robot_cmds
                if rig.plugin.command_options(c).get("executor")
            },
        )
        for name, args in [
            ("robot_set_servo", {"on": True}),
            ("robot_jog", {"axis": "x", "step": 1}),
            ("robot_set_manual_mode", {"enabled": True}),
            ("robot_set_mode", {"mode": "manual"}),
            ("robot_send_test_job", {}),
            ("robot_draw_circle", {"r": 10}),
            ("robot_clear_queue", {}),
            ("robot_read_echo", {}),
        ]:
            fn = rig.plugin.commands.get(name)
            res = getattr(rig.plugin, fn)({"device_id": _DEV, **args}) if fn else "NO SUCH COMMAND"
            print(f"V1->V2 {name}: {res}")
    finally:
        rig.close()


def test_q2_real_state_store():
    from multiprocess_framework.modules.state_store_module.manager.state_store_manager import StateStoreManager
    from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy

    sent = []
    proxy_self = SimpleNamespace(_process_name="devices", _server_target="state_store", _send=sent.append)
    mgr = StateStoreManager(router=None, auto_register_ipc=False)

    def via_proxy(kind, path, value):
        sent.clear()
        getattr(StateProxy, kind)(proxy_self, path, value)
        msg = sent[0]
        handler = mgr.handle_state_merge if kind == "merge" else mgr.handle_state_set
        return handler(msg)

    print("\nQ2 seed:", via_proxy("set", "devices.state.rv2.conn", {"conn": "connected"}))
    print("Q2 seed:", via_proxy("merge", "devices.state.rv2.status", {"quality": "good"}))
    print("Q2 seed:", via_proxy("merge", "devices.registry.rv2", {"id": "rv2", "kind": "robot"}))
    print(
        "Q2 last_error str via merge (plugin.py:625/763, driver.py:639):",
        via_proxy("merge", "devices.state.rv2.last_error", "подключение к роботу не удалось"),
    )
    print("Q2 tree last_error:", mgr._store.get("devices.state.rv2.last_error", default="<absent>"))
    print("Q2 remove via merge {} (plugin.py:1140):", via_proxy("merge", "devices.state.rv2", {}))
    print("Q2 tree after remove:", mgr._store.get("devices.state.rv2", default="<absent>"))
    print("Q2 registry remove via merge {} (manager.py:648):", via_proxy("merge", "devices.registry.rv2", {}))
    print("Q2 registry after:", mgr._store.get("devices.registry.rv2", default="<absent>"))
