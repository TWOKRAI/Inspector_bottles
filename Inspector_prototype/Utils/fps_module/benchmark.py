"""
Бенчмарк: python3 -m Utils.fps_module.benchmark
"""

import sys
import time

from . import FrameFPS, RingBufferFPS, AverageFPS


def main() -> None:
    print("=" * 50)
    print("FPS MODULE BENCHMARK")
    print("=" * 50)

    print("\n--- Размер ---")
    print(f"FrameFPS:      {sys.getsizeof(FrameFPS())} B")
    print(f"RingBufferFPS: {sys.getsizeof(RingBufferFPS())} B")
    print(f"AverageFPS:    {sys.getsizeof(AverageFPS(average_samples=10))} B")

    print("\n--- update() ops/sec ---")
    n = 1_000_000
    for name, obj in [
        ("FrameFPS", FrameFPS(interval=10.0)),
        ("RingBufferFPS", RingBufferFPS(window_seconds=10.0, max_samples=10000)),
        ("AverageFPS", AverageFPS(interval=10.0, average_samples=10)),
    ]:
        t0 = time.perf_counter()
        for _ in range(n):
            obj.update()
        elapsed = time.perf_counter() - t0
        print(f"{name}: {n/elapsed:,.0f} ops/sec")

    print("\n--- 60 FPS симуляция (600 кадров) ---")
    for name, obj in [
        ("FrameFPS", FrameFPS(1.0)),
        ("RingBufferFPS", RingBufferFPS(1.0)),
        ("AverageFPS", AverageFPS(1.0, average_samples=5)),
    ]:
        times = []
        t0 = time.perf_counter()
        next_frame = t0
        for _ in range(600):
            t1 = time.perf_counter()
            obj.update()
            times.append((time.perf_counter() - t1) * 1e6)
            next_frame += 0.016666
            sleep = next_frame - time.perf_counter()
            if sleep > 0:
                time.sleep(sleep)
        avg = sum(times) / len(times)
        print(f"{name}: avg={avg:.2f}µs, max={max(times):.2f}µs")


if __name__ == "__main__":
    main()
