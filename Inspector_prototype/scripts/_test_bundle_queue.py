"""
Тест воспроизводящий ТОЧНО паттерн фреймворка:
- mid_process создаёт queue_registry с очередями для двух процессов
- process_1 получает routing_map (как в фреймворке)
- process_2 получает свои очереди из bundle["queues"]
- Проверяем что сообщение от process_1 доходит до process_2
"""
import multiprocessing as mp
import time
import sys
from queue import Empty


def process_1(bundle):
    """Получает routing_map, берёт q6 (process_2_worker_in), кладёт сообщение."""
    routing_map = bundle["routing_map"]
    q6 = routing_map["process_2"]["worker_in"]
    print(f"[P1] q6 (from routing_map) id={id(q6)}", flush=True)
    time.sleep(0.2)
    q6.put({"command": "ping", "n": 0})
    print(f"[P1] sent ping, qsize={q6.qsize()}", flush=True)

    # Wait for pong on own worker_in
    q3 = bundle["queues"]["worker_in"]
    try:
        msg = q3.get(timeout=5)
        print(f"[P1] got: {msg}", flush=True)
    except Exception as e:
        print(f"[P1] TIMEOUT: {e}", flush=True)


def process_2(bundle):
    """Получает свои очереди из bundle['queues'], читает worker_in."""
    q6 = bundle["queues"]["worker_in"]
    print(f"[P2] q6 (own queues) id={id(q6)}", flush=True)
    try:
        msg = q6.get(timeout=5)
        print(f"[P2] got: {msg}", flush=True)
        # Send pong back
        routing_map = bundle["routing_map"]
        q3 = routing_map["process_1"]["worker_in"]
        q3.put({"command": "pong", "n": msg.get("n", 0) + 1})
        print(f"[P2] sent pong", flush=True)
    except Exception as e:
        print(f"[P2] TIMEOUT: {e}", flush=True)


def mid_process():
    """Exactly replicates ProcessManagerProcess._create_processes_from_config."""
    print("[MID] creating queues...", flush=True)
    # Simulates queue_registry
    registered_queues = {
        "process_1": {
            "system": mp.Queue(100), "data": mp.Queue(100),
            "worker_in": mp.Queue(50),
        },
        "process_2": {
            "system": mp.Queue(100), "data": mp.Queue(100),
            "worker_in": mp.Queue(50),
        },
    }
    q3 = registered_queues["process_1"]["worker_in"]
    q6 = registered_queues["process_2"]["worker_in"]
    print(f"[MID] q3 id={id(q3)}, q6 id={id(q6)}", flush=True)

    # Exactly like _create_process_impl:
    routing_map = dict(registered_queues)  # shallow copy

    bundle_p1 = {
        "queues": registered_queues["process_1"],       # process_1's own queues
        "config": {}, "custom": {},
        "routing_map": routing_map,                     # ALL queues (including q6)
    }
    bundle_p2 = {
        "queues": registered_queues["process_2"],       # process_2's own queues
        "config": {}, "custom": {},
        "routing_map": routing_map,                     # ALL queues (including q3)
    }

    pa = mp.Process(target=process_1, args=(bundle_p1,), name="process_1")
    pb = mp.Process(target=process_2, args=(bundle_p2,), name="process_2")
    pa.start()
    pb.start()
    pa.join(10)
    pb.join(10)
    print("[MID] done", flush=True)


if __name__ == "__main__":
    print("[MAIN] Testing bundle queue pattern...", flush=True)
    mid = mp.Process(target=mid_process, name="mid_process")
    mid.start()
    mid.join(20)
    print("[MAIN] done", flush=True)
