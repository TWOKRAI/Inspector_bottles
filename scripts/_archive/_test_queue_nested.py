"""
Тест: Queue создаётся В mid_process (не в main), затем передаётся worker_a и worker_b.
Это точно воспроизводит паттерн фреймворка.
"""

import multiprocessing as mp
import time
import sys


def worker_a(q_send, q_recv):
    print("[A] started", flush=True)
    time.sleep(0.3)
    q_send.put({"msg": "ping from A"})
    print("[A] sent ping", flush=True)
    try:
        msg = q_recv.get(timeout=5)
        print(f"[A] got: {msg}", flush=True)
    except Exception as e:
        print(f"[A] TIMEOUT or ERROR: {e}", flush=True)


def worker_b(q_send, q_recv):
    print("[B] started", flush=True)
    try:
        msg = q_recv.get(timeout=5)
        print(f"[B] got: {msg}", flush=True)
        q_send.put({"msg": "pong from B"})
        print("[B] sent pong", flush=True)
    except Exception as e:
        print(f"[B] TIMEOUT or ERROR: {e}", flush=True)


def mid_process():
    """Creates queues HERE, then spawns workers."""
    print("[MID] started, creating queues...", flush=True)
    # Queues created in mid_process (subprocess), just like in the framework
    q_ab = mp.Queue(maxsize=50)
    q_ba = mp.Queue(maxsize=50)
    print(f"[MID] q_ab={id(q_ab)}, q_ba={id(q_ba)}", flush=True)

    pa = mp.Process(target=worker_a, args=(q_ab, q_ba), name="worker_a")
    pb = mp.Process(target=worker_b, args=(q_ba, q_ab), name="worker_b")
    pa.start()
    pb.start()
    pa.join(10)
    pb.join(10)
    print("[MID] done", flush=True)


if __name__ == "__main__":
    print("[MAIN] Testing queue created in subprocess...", flush=True)
    mid = mp.Process(target=mid_process, name="mid_process")
    mid.start()
    mid.join(15)
    print("[MAIN] done", flush=True)
    sys.exit(0)
