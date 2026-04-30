"""
Минимальный тест: работает ли multiprocessing.Queue между 3 уровнями subprocess
(main → mid_process → worker_a + worker_b) на Windows spawn.
"""
import multiprocessing as mp
import time
import sys


def worker_a(q_send, q_recv):
    """Отправляет ping в q_send, ждёт pong из q_recv."""
    print(f"[A] started, q_send id={id(q_send)}, q_recv id={id(q_recv)}", flush=True)
    time.sleep(0.2)
    q_send.put({"msg": "ping from A", "n": 0})
    print("[A] sent ping", flush=True)
    try:
        msg = q_recv.get(timeout=5)
        print(f"[A] got: {msg}", flush=True)
    except Exception as e:
        print(f"[A] TIMEOUT: {e}", flush=True)


def worker_b(q_send, q_recv):
    """Ждёт ping из q_recv, отправляет pong в q_send."""
    print(f"[B] started, q_send id={id(q_send)}, q_recv id={id(q_recv)}", flush=True)
    try:
        msg = q_recv.get(timeout=5)
        print(f"[B] got: {msg}", flush=True)
        q_send.put({"msg": "pong from B", "n": msg.get("n", 0) + 1})
        print("[B] sent pong", flush=True)
    except Exception as e:
        print(f"[B] TIMEOUT: {e}", flush=True)


def mid_process(q_ab, q_ba):
    """Запускает worker_a и worker_b в отдельных subprocess."""
    print(f"[MID] started, q_ab id={id(q_ab)}, q_ba id={id(q_ba)}", flush=True)
    pa = mp.Process(target=worker_a, args=(q_ab, q_ba), name="worker_a")
    pb = mp.Process(target=worker_b, args=(q_ba, q_ab), name="worker_b")
    pa.start()
    pb.start()
    pa.join(10)
    pb.join(10)
    print("[MID] done", flush=True)


if __name__ == "__main__":
    print("[MAIN] Starting 3-level Queue test...", flush=True)

    q_ab = mp.Queue()  # A → B
    q_ba = mp.Queue()  # B → A

    print(f"[MAIN] q_ab id={id(q_ab)}, q_ba id={id(q_ba)}", flush=True)

    mid = mp.Process(target=mid_process, args=(q_ab, q_ba), name="mid_process")
    mid.start()
    mid.join(15)

    print("[MAIN] done", flush=True)
    sys.exit(0)
