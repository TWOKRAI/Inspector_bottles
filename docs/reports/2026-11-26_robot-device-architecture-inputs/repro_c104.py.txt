"""Throwaway repro (C-104): word_layout -> robot_io -> fake hub client -> real RobotDriverV2 -> SimRobotServer."""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from multiprocess_framework.modules.base_manager import open_scope
from Plugins.io.robot_io.plugin import RobotIoPlugin
from Plugins.processing.word_layout.plugin import WordLayoutPlugin
from Services.device_hub.kinds import DEFAULT_KINDS, DriverContext
from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.core.params_v2 import PARAM_ID
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2
from Services.robot_comm.server.sim_robot import SimRobotServer
from Services.robot_comm.store import RobotDataStore
from Services.robot_comm.tests.e2e_rig_v2 import free_port

DEV = "robot_main"
T0 = time.monotonic()
SCOPE = open_scope("repro_c104", budget_s=5.0)


def p(name, value):
    print(f"{name} = {value}", flush=True)


def wait(pred, deadline_s, what):
    end = time.monotonic() + deadline_s
    while not pred():
        if time.monotonic() >= end:
            p("WAIT_TIMEOUT", f"{what} ({deadline_s}s)")
            return False
        time.sleep(0.02)
    return True


class Sim:
    def __init__(self):
        self.core = RobotSimCoreV2()
        self.port = free_port()
        self.server = SimRobotServer("127.0.0.1", self.port, ROBOT_UNIT_ID, core=self.core)
        self.server.start()

    def stop(self):
        self.server.stop()


class Drv:
    """Real driver built by the hub kind table, with a manual tick thread."""

    def __init__(self, port, params):
        self.published = []
        entry = DeviceEntry(
            id=DEV,
            name=DEV,
            kind="robot",
            protocol="delta_v2",
            transport={"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": ROBOT_UNIT_ID},
            params=dict(params),
        )
        self.store_dir = Path(tempfile.mkdtemp(prefix="c104_robot_"))
        ctx = DriverContext(
            publish=lambda path, data: self.published.append((path, data)),
            spawn=SCOPE.spawn,
            robot_store=RobotDataStore(self.store_dir),
            options={},
            resolve_device=lambda _i: None,
        )
        row = next(k for k in DEFAULT_KINDS if k.kind == "robot")
        self.d = row.create(entry, None, ctx)
        self.stop_ev = threading.Event()
        self.tick_errors = []
        self.thread = None
        p("connect", self.d.connect())
        self.d.desired_connected = True
        p("is_connected", self.d.is_connected)

    def start_tick(self):
        def body():
            while not self.stop_ev.is_set():
                try:
                    self.d.tick(self.stop_ev)
                except Exception as exc:  # noqa: BLE001
                    self.tick_errors.append(repr(exc))
                self.stop_ev.wait(0.05)

        self.thread = threading.Thread(target=body, name="repro-tick", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_ev.set()
        if self.thread:
            self.thread.join(10.0)
            p("tick_thread_alive_after_join", self.thread.is_alive())
        self.d.disconnect()
        if self.tick_errors:
            p("tick_errors", self.tick_errors[:3])


class FakeHubClient:
    def __init__(self, driver):
        self.driver = driver
        self.replies = []

    def request(self, command, payload, timeout=1.0):
        args = {k: v for k, v in payload.items() if k != "device_id"}
        reply = self.driver.call(command.removeprefix("robot_"), args)
        self.replies.append((command, args, reply))
        return reply


def mkctx(config):
    ctx = MagicMock()
    ctx.config = dict(config)
    ctx.registers = None
    ctx.state_proxy = MagicMock()
    ctx.process_name = "layout"
    return ctx


class Chain:
    def __init__(self, drv):
        self.wl = WordLayoutPlugin()
        self.wl.configure(
            mkctx(
                {
                    "target_word": "МИР",
                    "word_source": "signal_2",
                    "use_pitch": True,
                    "first_x": 320.0,
                    "first_y": -440.0,
                    "line_angle_deg": 90.0,
                    "pitch_mm": 0.0,
                    "last_x": 320.0,
                    "last_y": 300.0,
                    "place_z_mm": -132.0,
                    "disk_radius_mm": 55.0,
                    "word_gap_slots": 1,
                    "angle_zero_deg": 0.0,
                    "angle_invert": False,
                    "min_confidence": 0.5,
                    "settle_frames": 1,
                    "use_trigger": False,
                    "pick_source": "pick_xy",
                    "encoder_source": "e_capture",
                    "require_pick": True,
                    "pick_z_mm": -132.0,
                }
            )
        )
        self.rio = RobotIoPlugin()
        self.rio_ctx = mkctx({"device_id": DEV, "job_source": "robot_job"})
        self.rio.configure(self.rio_ctx)
        self.client = FakeHubClient(drv.d)
        self.rio._client = self.client
        self.stop, self.pause = threading.Event(), threading.Event()
        self.thread = threading.Thread(target=self.rio._forwarder_loop, args=(self.stop, self.pause), daemon=True)
        self.thread.start()
        self.fed = 0

    def feed(self, label, track, pick=(450.0, -250.0)):
        item = {
            "predictions": [{"label": label, "confidence": 0.95, "angle_deg": 0.0, "angle_valid": True}],
            "pick_xy": {"x_mm": pick[0], "y_mm": pick[1]},
            "sidecar": {"track_id": track},
        }
        out = self.wl.process([item])[0]
        p(f"feed '{label}' track={track} robot_job_emitted", "robot_job" in out)
        if "robot_job" in out:
            self.fed += 1
        self.rio.process([out])
        wait(lambda: not self.rio._deque and len(self.client.replies) >= self.fed, 5.0, "robot_io deque empty")
        time.sleep(0.15)
        if self.client.replies:
            cmd, args, reply = self.client.replies[-1]
            p("  hub_command", cmd)
            p("  hub_args", args)
            p("  hub_reply", reply)

    def close(self):
        self.stop.set()
        self.thread.join(3.0)


def dump_wl(c):
    r = c.wl._reg
    for k in ("assembled", "slots_filled", "done", "jobs_emitted"):
        p(f"word_layout.{k}", repr(getattr(r, k)))


def dump_rio(c):
    r = c.rio._reg
    for k in ("jobs_forwarded", "jobs_dropped", "last_error", "last_dropped_job", "forward_ok"):
        p(f"robot_io.{k}", repr(getattr(r, k)))
    p("robot_io.health.report_error.call_count", c.rio_ctx.health.report_error.call_count)


def dump_drv(drv):
    s = drv.d.snapshot()
    for k in ("queue_len", "jobs_sent", "jobs_done", "jobs_failed"):
        p(f"driver.{k}", s.get(k))
    p("driver.published_last_error_all", [v for path, v in drv.published if path.endswith(".last_error")])


def park(drv):
    reply = drv.d.call("park", {})
    p("park_reply", reply)
    if drv.thread is None:
        drv.start_tick()
    if reply.get("status") == "ok":
        p("park_terminal", drv.d.park_wait(reply["seq"], 40.0))


def finished(drv):
    return drv.d.jobs_done + drv.d.jobs_failed


def s1():
    sim = Sim()
    drv = Drv(sim.port, {"robot_params": {"P_ZONE_MAX": 6000}, "telemetry_interval_s": 0.5})
    c = None
    try:
        drv.start_tick()
        time.sleep(0.3)
        p("sim.P_ZONE_MAX_raw", sim.core._values[PARAM_ID["P_ZONE_MAX"]])
        c = Chain(drv)
        park(drv)
        p("sim.TLM_SERVO", sim.core.regs[REG["TLM_SERVO"]])
        c.feed("М", 1)
        time.sleep(1.0)
        print("-- after disc 1 (parked) --")
        dump_wl(c)
        dump_rio(c)
        dump_drv(drv)
        p("servo_on_reply", drv.d.call("servo", {"on": True}))
        c.feed("И", 2)
        c.feed("Р", 3)
        wait(lambda: finished(drv) >= 2, 60.0, "jobs_done+jobs_failed >= 2")
        print("-- at jobs_done+jobs_failed >= 2 --")
        dump_wl(c)
        dump_rio(c)
        dump_drv(drv)
        time.sleep(5.0)
        print("-- 5 s later (settle check) --")
        dump_drv(drv)
    finally:
        if c:
            c.close()
        drv.close()
        sim.stop()


def s2():
    sim = Sim()
    drv = Drv(sim.port, {"robot_params": {"P_ZONE_MAX": 6000}, "telemetry_interval_s": 0.5})
    c = None
    try:
        c = Chain(drv)
        p("sim.TLM_SERVO", sim.core.regs[REG["TLM_SERVO"]])
        c.feed("М", 1)
        print("-- after disc 1 (tick not started) --")
        dump_wl(c)
        dump_rio(c)
        dump_drv(drv)
        park(drv)
        time.sleep(1.0)
        print("-- after park terminal --")
        dump_wl(c)
        dump_rio(c)
        dump_drv(drv)
    finally:
        if c:
            c.close()
        drv.close()
        sim.stop()


def s3():
    sim = Sim()
    drv = Drv(sim.port, {})
    c = None
    try:
        drv.start_tick()
        time.sleep(0.3)
        p("sim.P_ZONE_MAX_raw", sim.core._values[PARAM_ID["P_ZONE_MAX"]])
        c = Chain(drv)
        c.feed("М", 1, pick=(497.4, -328.0))
        wait(lambda: finished(drv) >= 1, 30.0, "jobs_done+jobs_failed >= 1")
        time.sleep(0.5)
        errs = [(path, v) for path, v in drv.published if path.endswith(".last_error")]
        p("driver.last_error_last_published", errs[-1] if errs else None)
        dump_wl(c)
        dump_rio(c)
        dump_drv(drv)
    finally:
        if c:
            c.close()
        drv.close()
        sim.stop()


def s4():
    sim = Sim()
    try:
        pid = PARAM_ID["P_ZONE_MAX"]
        print("-- driver A (no robot_params) --")
        a = Drv(sim.port, {})
        a.close()
        p("A._epoch", a.d._epoch)
        p("sim.P_ZONE_MAX_raw", sim.core._values[pid])
        p("sim.TLM_CFG_EPOCH", sim.core.regs[REG["TLM_CFG_EPOCH"]])
        print("-- driver B (robot_params P_ZONE_MAX=6000, no config_epoch) --")
        b = Drv(sim.port, {"robot_params": {"P_ZONE_MAX": 6000}})
        try:
            b.start_tick()
            time.sleep(1.0)
            p("B._epoch", b.d._epoch)
            p("sim.P_ZONE_MAX_raw", sim.core._values[pid])
            p("sim.TLM_CFG_EPOCH", sim.core.regs[REG["TLM_CFG_EPOCH"]])
            p("B._values['P_ZONE_MAX']", b.d._values["P_ZONE_MAX"])
            p("B.params.yaml_exists", (b.store_dir / DEV / "params.yaml").exists())
            p("driver.published_last_error_all", [v for path, v in b.published if path.endswith(".last_error")])
        finally:
            b.close()
    finally:
        sim.stop()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    failed = []
    for fn in (s1, s2, s3, s4):
        print(f"\n==================== {fn.__name__.upper()} ====================", flush=True)
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            failed.append((fn.__name__, repr(exc)))
        p("elapsed_s", round(time.monotonic() - T0, 1))
    report = SCOPE.close()
    p("scope_survivors", list(report.survivors))
    p("failed_scenarios", failed)
