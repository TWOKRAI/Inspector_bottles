"""Repro in the LIVE rig: a child that survives terminate/kill -> does the PM ever publish system.stop.phase=done?"""
import time
from multiprocess_framework.modules.process_manager_module.tests.test_pm_responsive_during_children_stop import Rig
from multiprocess_framework.modules.process_manager_module.tests.test_supervision_status_system_stop import _gui_msg

rig = Rig(1.0)
rig.start()
try:
    log = []
    ssm = rig.pm._state_store_manager
    real = ssm.handle_state_set
    def spy(msg, *a, **k):
        d = msg["data"] if isinstance(msg.get("data"), dict) else msg
        if str(d.get("path", "")).startswith("system.stop."):
            log.append((d["path"], d["value"]))
        return real(msg, *a, **k)
    ssm.handle_state_set = spy
    child = rig.add_child("stuck", mode="terminate")
    child.terminate = lambda: None   # survives terminate
    child.kill = lambda: None        # survives kill
    rig.pm._handle_process_command(_gui_msg(sender="gui"))
    closed = rig.wait_root_closed(60.0)
    print("root closed:", closed)
    print("child alive:", child.is_alive())
    print("system_stop dict after root close:", {k: v for k, v in (rig.pm._system_stop_snapshot() or {}).items() if k in ("phase", "mode", "initiator")})
    print("store writes:", [(p.split('.')[-1], v if p.endswith(('phase','mode','initiator')) else '...') for p, v in log])
finally:
    rig.close()
