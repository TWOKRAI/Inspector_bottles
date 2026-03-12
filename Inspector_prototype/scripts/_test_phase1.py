"""
Тест Этапа 1: SystemLauncher → ProcessSpawner → ProcessManagerProcess запускается.
Запускать как: python scripts/_test_phase1.py
"""
import sys
import time
from pathlib import Path


def run_test():
    print(f"[TEST] Phase 1 check starting...")

    from multiprocess_framework.refactored.modules.process_manager_module import SystemLauncher
    from multiprocess_framework.refactored.modules.data_schema_module import process
    from multiprocess_prototype.processes.process_1 import Process1Config
    from multiprocess_prototype.processes.process_1.worker_1 import Worker1Config
    from multiprocess_prototype.processes.process_2 import Process2Config
    from multiprocess_prototype.processes.process_2.worker_2 import Worker2_1Config, Worker2_2Config

    print("[TEST] All imports OK")

    launcher = SystemLauncher()
    launcher.add_process(*process(Process1Config(), Worker1Config()))
    launcher.add_process(*process(Process2Config(), Worker2_1Config(), Worker2_2Config()))

    procs_config = launcher._get_processes_config()
    print(f"[TEST] processes_config: {list(procs_config.keys())}")
    for name, cfg in procs_config.items():
        print(f"  [{name}] class={cfg.get('class','?').split('.')[-1]}, queues={list(cfg.get('queues', {}).keys())}")

    from multiprocess_framework.refactored.modules.process_manager_module.launcher.spawner import ProcessSpawner

    spawner = ProcessSpawner(processes_config=procs_config)
    print("[TEST] Starting orchestrator (5 second run)...")

    result = spawner.launch_orchestrator()
    proc = spawner.get_process()
    print(f"[TEST] launch_orchestrator() = {result}")
    print(f"[TEST] ProcessManager PID = {proc.pid if proc else 'N/A'}, alive = {spawner.is_running()}")

    time.sleep(5)

    print(f"[TEST] After 5s: alive = {spawner.is_running()}")
    spawner.stop()
    time.sleep(1)
    print(f"[TEST] After stop: alive = {spawner.is_running()}")
    print("[TEST] Phase 1 PASSED" if not spawner.is_running() else "[TEST] Phase 1 FAILED (still alive)")


if __name__ == "__main__":
    run_test()
