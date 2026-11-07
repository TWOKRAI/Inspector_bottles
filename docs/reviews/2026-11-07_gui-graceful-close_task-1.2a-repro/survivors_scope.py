"""Repro: does the real Scope call _ChildrenStop.close() when children survive (join_until False twice)?"""
import time
from multiprocess_framework.modules.base_manager.core.lifetime import open_scope
from multiprocess_framework.modules.process_manager_module.tests.test_supervision_status_system_stop import _Light

for join_result in (True, False):
    lt = _Light(join_result=join_result, group_result={"stuck": join_result})
    lt.shutdown(None)  # begin command-driven stop
    root = open_scope("pm-root", budget_s=2.0, kill_reserve_s=0.5) if True else None
    work = root.child("work", budget_s=1.0, kill_reserve_s=0.3)
    work.own(lt.cs, name="processes", kind="process")
    t0 = time.monotonic()
    rep = root.close()
    print("join_result", join_result, "survivors", getattr(rep, "survivors", None), "killed", getattr(rep, "killed", None))
    print("  journal:", lt.journal)
    print("  phase after scope close:", lt.pm._system_stop_snapshot()["phase"])
