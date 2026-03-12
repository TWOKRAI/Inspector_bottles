"""
Тестовый скрипт для Этапа 2: запуск дочерних процессов.
Запускать из Inspector_prototype/:
  python scripts/_test_phase2.py

Использует start() (неблокирующий) + ожидание + shutdown().
Вывод дочерних процессов идёт в общий stdout т.к. они spawn-процессы.
"""
import sys
import time
import traceback

if __name__ == "__main__":
    print("[test_phase2] Starting...", flush=True)
    try:
        from multiprocess_framework.refactored.modules.process_manager_module import SystemLauncher
        from multiprocess_framework.refactored.modules.data_schema_module import process
        from multiprocess_prototype.processes.process_1 import Process1Config
        from multiprocess_prototype.processes.process_1.worker_1 import Worker1Config
        from multiprocess_prototype.processes.process_2 import Process2Config
        from multiprocess_prototype.processes.process_2.worker_2 import Worker2_1Config, Worker2_2Config

        print("[test_phase2] Imports OK", flush=True)

        launcher = SystemLauncher()
        launcher.add_process(*process(Process1Config(), Worker1Config()))
        launcher.add_process(*process(Process2Config(), Worker2_1Config(), Worker2_2Config()))

        print("[test_phase2] Configs added, calling start()...", flush=True)
        launcher.start()
        print("[test_phase2] start() returned (non-blocking), waiting 8s...", flush=True)

        for i in range(8):
            time.sleep(1)
            status = launcher.get_status()
            pm = status.get("process", {})
            alive = pm.get("is_alive", False) if pm else False
            pid = pm.get("pid") if pm else None
            registered = status.get("registered_processes", [])
            print(
                f"[test_phase2] t={i+1}s  ProcessManager alive={alive} pid={pid}"
                f"  registered={registered}",
                flush=True,
            )

        print("[test_phase2] Shutting down...", flush=True)
        launcher.shutdown()
        print("[test_phase2] Done.", flush=True)
        sys.exit(0)

    except Exception as e:
        print(f"[test_phase2] FAILED: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)
