# ruff: noqa — материал разбора, не код проекта
"""R2 journal probe (throwaway): real RobotDriverV2 + real RobotClientV2 over in-process sim E2eRig."""

from __future__ import annotations

import collections
import time

import Services.device_hub.tests.test_robot_v2_park_acceptance as pa
from Services.device_hub.tests.test_robot_v2_park_acceptance import driver_scope  # noqa: F401
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded


def _get(drv, since):
    return drv.call("exchange_log_get", {"since_seq": since, "limit": 5000})


def _dump(drv, since, title):
    res = _get(drv, since)
    lines = res["lines"]
    tags = collections.Counter(l["tag"] or "-" for l in lines)
    print(f"\n=== {title}: {len(lines)} lines, tags={dict(tags)}, last_seq={res['last_seq']}, dropped={res['dropped']}")
    for l in lines[:40]:
        print(f"  #{l['seq']} t={l['t']:.3f} {l['side'] or '--'} [{l['tag']}] {l['text']} x{l['n']} {l['ms']:.1f}ms")
    if len(lines) > 40:
        print(f"  ... {len(lines) - 40} more")
    return res["last_seq"] + 1


def test_journal_scenario():
    with E2eRig() as rig:
        entry = DeviceEntry(
            id="rj",
            name="rj",
            kind="robot",
            protocol="delta_v2",
            transport={"type": "tcp", "host": "127.0.0.1", "port": rig.port, "unit_id": ROBOT_UNIT_ID},
            params={},
        )
        drv = RobotDriverV2(entry, publish=lambda p, v: print(f"  PUBLISH {p} = {v!r}"[:200]), spawn=pa._SCOPE.spawn)
        print("\nrefused before connect (not connected):", drv.call("servo", {"on": True}))
        assert bounded(drv.connect, 60.0) is True
        drv.desired_connected = True
        mark = _dump(drv, 0, "connect (probe, sync_params, on_connect)")
        print("bad args:", drv.call("servo", {"on": "yes"}))
        print("servo on:", drv.call("servo", {"on": True}))
        mark = _dump(drv, mark, "bad-args + servo on")
        print("enqueue_job:", drv.call("enqueue_job", {"x_mm": 300, "y_mm": -150}))
        end = time.monotonic() + 20
        while drv.jobs_done + drv.jobs_failed < 1 and time.monotonic() < end:
            bounded(drv.tick, 20.0)
        print("jobs sent/done/failed:", drv.jobs_sent, drv.jobs_done, drv.jobs_failed)
        mark = _dump(drv, mark, "job + ticks")
        print("park:", drv.call("park", {}))
        end = time.monotonic() + 20
        while time.monotonic() < end:
            bounded(drv.tick, 20.0)
            st = drv.state.park_view()
            if not st.parking:
                break
        mark = _dump(drv, mark, "park + ticks")
        print("job after park:", drv.call("enqueue_job", {"x_mm": 300, "y_mm": -150}))
        print("jog_step after park:", drv.call("jog_step", {"dx": 10, "dy": 0, "spd": 50}))
        mark = _dump(drv, mark, "refused job / jog after park")
        bounded(drv.disconnect, 15.0)
        mark = _dump(drv, mark, "disconnect")
        print("counters:", {k: v["count"] for k, v in _get(drv, 0)["counters"].items()})
        print("ring maxlen:", drv._exchange_log._ring.maxlen)
