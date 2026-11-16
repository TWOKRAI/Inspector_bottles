"""Deterministic and natural-race reproduction of the heartbeat import deadlock.

Thread "main" plays ProcessModule.run():1518 (from ..heartbeat.process_heartbeat import ProcessHeartbeat).
Thread "msgproc" plays the message_processor thread running the REAL handler
BuiltinCommands._cmd_introspect_status (builtin_commands.py:822 lazy import of heartbeat.cpu_clock).

Modes:
  det      - two loader wrappers pin the interleaving seen on the stand (no lock semantics changed:
             they only wait at exec_module, a point where the interpreter can switch threads anyway).
  natural  - no hooks: both threads released by a barrier; report what happened.
  prewarm  - like natural, but heartbeat.process_heartbeat is imported in main BEFORE threads (proposed fix).
Usage: python repro_import_deadlock.py <mode> <repo_root>
"""
import importlib.abc
import importlib.machinery
import importlib._bootstrap as _bs
import json
import sys
import threading
import time
import traceback
import types

mode, root = sys.argv[1], sys.argv[2]
sys.path.insert(0, root)

# State of a spawned child right before run(): process_module core + builtins imported, heartbeat not.
import multiprocess_framework.modules.process_module.core.process_module  # noqa: E402,F401
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands  # noqa: E402
import cv2  # noqa: E402,F401  runner _apply_cv_threads imports cv2 before the process class is built

H = "multiprocess_framework.modules.process_module.heartbeat"
PH = H + ".process_heartbeat"
CC = H + ".cpu_clock"
pre = {m: (m in sys.modules) for m in (H, PH, CC)}

ev_b_in_init = threading.Event()
ev_a_holds_ph = threading.Event()
tids = {}
res = {}


def blocked(tid):
    lst = _bs._blocking_on.get(tid)
    return bool(lst)


class Wrap(importlib.abc.Loader):
    def __init__(self, real, before):
        self.real, self.before = real, before

    def create_module(self, spec):
        return self.real.create_module(spec)

    def exec_module(self, module):
        self.before()
        return self.real.exec_module(module)


def before_pkg_init():  # runs in msgproc: heartbeat is already in sys.modules, __init__ not executed yet
    ev_b_in_init.set()
    ev_a_holds_ph.wait(5)


def before_ph_body():  # runs in main: it owns lock(process_heartbeat), body not executed yet
    ev_a_holds_ph.set()
    t0 = time.time()
    while not blocked(tids.get("B")) and time.time() - t0 < 5:
        time.sleep(0.001)
    res["B_blocked_seen"] = blocked(tids.get("B"))


class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname not in (H, PH):
            return None
        me = threading.current_thread().name
        if fullname == H and me != "msgproc":
            return None
        if fullname == PH and me != "MainThread":
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        spec.loader = Wrap(spec.loader, before_pkg_init if fullname == H else before_ph_body)
        return spec


fake_self = types.SimpleNamespace(
    _services=types.SimpleNamespace(name="camera_0", worker_manager=None, _current_process_status="ready")
)
barrier = threading.Barrier(2)


def thread_b():
    tids["B"] = threading.get_ident()
    if mode != "det":
        barrier.wait()
    try:
        out = BuiltinCommands._cmd_introspect_status(fake_self)
        res["B"] = "ok success=%s" % out.get("success")
    except BaseException as e:  # noqa: BLE001
        res["B"] = "%s: %s" % (type(e).__name__, e)
        res["B_tb"] = traceback.format_exc().splitlines()[-6:]


if mode == "det":
    sys.meta_path.insert(0, Finder())
if mode.startswith("prewarm"):
    from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import ProcessHeartbeat  # noqa: F401

tb = threading.Thread(target=thread_b, name="msgproc", daemon=True)
tb.start()
if mode == "det":
    ev_b_in_init.wait(5)
else:
    barrier.wait()
    if "delayA:" in mode:
        time.sleep(int(mode.split("delayA:")[1]) / 1e6)
try:
    from multiprocess_framework.modules.process_module.heartbeat.process_heartbeat import ProcessHeartbeat  # noqa: F401,E402

    res["A"] = "ok"
except BaseException as e:  # noqa: BLE001
    res["A"] = "%s: %s" % (type(e).__name__, e)
    res["A_tb"] = [ln for ln in traceback.format_exc().splitlines() if "File" in ln][-4:]
tb.join(10)
res["B_alive_after_join"] = tb.is_alive()
res["pre"] = {k.rsplit(".", 1)[1]: v for k, v in pre.items()}
res["mode"] = mode
print(json.dumps(res, ensure_ascii=False))
