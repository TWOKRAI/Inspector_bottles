"""Repro: can a client forge initiator via data._sender? envelope (process.command) vs direct command."""
import time
from multiprocess_framework.modules.process_manager_module.tests.test_pm_responsive_during_children_stop import Rig
from multiprocess_framework.modules.process_manager_module.tests.test_supervision_status_system_stop import _gui_msg

def run(route):
    rig = Rig(5.0)
    rig.start()
    try:
        rig.add_child("hold", mode="slow", exit_after_s=3.0)
        if route == "envelope":
            msg = _gui_msg({"_sender": "forged"}, sender="gui")
            rig.pm._handle_process_command(msg)
        elif route == "envelope-no-sender":
            msg = _gui_msg({"_sender": "forged"}, sender=None)
            rig.pm._handle_process_command(msg)
        else:  # direct command on system queue, as in Rig.send
            rig.send("system.shutdown", {"_sender": "forged"})
        rig.wait_until(lambda: rig.pm._system_stop_snapshot() is not None, 10.0)
        snap = rig.pm._system_stop_snapshot()
        print(route, "->", snap and snap["initiator"])
    finally:
        rig.close()

for r in ("envelope", "envelope-no-sender", "direct"):
    run(r)
