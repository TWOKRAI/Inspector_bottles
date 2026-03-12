"""
Тестовый скрипт для Этапа 3: ping-pong коммуникация через RouterManager.

Запускать из Inspector_prototype/:
  python scripts/_test_phase3.py

Ожидаемый вывод — чередующиеся строки:
  [worker_1]   ОТПРАВИЛ старт ping n=0
  [worker_2_2] ПРИНЯЛ ping n=0, отправляю pong n=1
  [worker_1]   ПРИНЯЛ pong n=1, отправляю ping n=2
  [worker_2_2] ПРИНЯЛ ping n=2, отправляю pong n=3
  ...

Архитектура коммуникации:
  Worker1 (process_1) → router.send(channel="process_2_worker_in") → Queue →
  Worker2_2 (process_2) читает из queues["worker_in"] →
  router.send(channel="process_1_worker_in") → Queue →
  Worker1 читает из queues["worker_in"] → ...
"""
import sys
import time
import traceback

WAIT_SECONDS = 15  # Достаточно для нескольких обменов ping-pong (interval=1s)


if __name__ == "__main__":
    print("[test_phase3] Starting ping-pong test...", flush=True)
    try:
        from multiprocess_framework.refactored.modules.process_manager_module import SystemLauncher
        from multiprocess_framework.refactored.modules.data_schema_module import process
        from multiprocess_prototype.processes.process_1 import Process1Config
        from multiprocess_prototype.processes.process_1.worker_1 import Worker1Config
        from multiprocess_prototype.processes.process_2 import Process2Config
        from multiprocess_prototype.processes.process_2.worker_2 import Worker2_1Config, Worker2_2Config

        print("[test_phase3] Imports OK", flush=True)

        # Используем быстрый интервал опроса для ping-pong (0.1s вместо 1s)
        w1_cfg = Worker1Config()
        w1_cfg.interval = 0.2

        w2_2_cfg = Worker2_2Config()
        w2_2_cfg.interval = 0.1

        launcher = SystemLauncher()
        launcher.add_process(*process(Process1Config(), w1_cfg))
        launcher.add_process(*process(Process2Config(), Worker2_1Config(), w2_2_cfg))

        print("[test_phase3] Configs added, calling start()...", flush=True)
        launcher.start()
        print(
            f"[test_phase3] start() returned (non-blocking), waiting {WAIT_SECONDS}s...",
            flush=True,
        )

        for i in range(WAIT_SECONDS):
            time.sleep(1)
            status = launcher.get_status()
            pm = status.get("process", {})
            alive = pm.get("is_alive", False) if pm else False
            pid = pm.get("pid") if pm else None
            print(
                f"[test_phase3] t={i+1:2d}s  ProcessManager alive={alive} pid={pid}",
                flush=True,
            )

        print("[test_phase3] Shutting down...", flush=True)
        launcher.shutdown()
        print("[test_phase3] Done.", flush=True)
        sys.exit(0)

    except Exception as e:
        print(f"[test_phase3] FAILED: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)
