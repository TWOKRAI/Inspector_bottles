# -*- coding: utf-8 -*-
"""Ф7 G.1 — headless perf-baseline (tier: синтетика) через BackendHarness.

Поднимает минимальный синтетический тракт (``recipes/g1_perf_probe.yaml``:
``synthetic_source`` → ``consumer``, ровно 1 граница IPC на кадр) БЕЗ реального
железа, крутит ``duration`` секунд с включёнными perf-пробами (HP-1,
``FW_PERF_PROBES=1``), затем снимает:

  - FPS источник/потребитель (``get_cycle_metrics().effective_hz`` через
    introspect.status → workers → source_producer_*/data_receiver);
  - latency p50/p99 по этапам capture/send/receive/restore (``perf_probes``
    в том же снимке);
  - границ процесса на кадр (``introspect.router_stats(synthetic_source)
    .frame_boundary_crossings`` / отправленных кадров).

Запуск:
    BACKEND_CTL=1 python -m backend_ctl.g1_perf_probe [duration_sec]

Числа печатаются в консоль (json) — переносятся в baseline.md вручную
(живой документ плана, не генерируется автоматически).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_RECIPES = Path(__file__).resolve().parent.parent / "multiprocess_prototype" / "recipes"
_RECIPE = _RECIPES / "g1_perf_probe.yaml"


def _unwrap(res: dict) -> dict:
    """Достать вложенный handler-результат: request() → {success, result:{...}}."""
    if not isinstance(res, dict):
        return {}
    return res.get("result") if isinstance(res.get("result"), dict) else res


def main() -> int:
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0

    os.environ.setdefault("BACKEND_CTL", "1")
    os.environ.setdefault("FW_PERF_PROBES", "1")  # HP-1: пробы включены для baseline

    from backend_ctl.harness import BackendHarness

    print(f"[g1-probe] поднимаю synthetic-тракт headless (recipe={_RECIPE.name}), duration={duration}s...")
    harness = BackendHarness(recipe=_RECIPE, port=8766)
    with harness as drv:
        time.sleep(duration)

        source_status = _unwrap(drv.introspect_status("synthetic_source", timeout=8.0))
        consumer_status = _unwrap(drv.introspect_status("consumer", timeout=8.0))
        router_stats = _unwrap(drv.introspect_router_stats("synthetic_source", timeout=8.0))

        source_workers = source_status.get("workers", {}) if isinstance(source_status, dict) else {}
        consumer_workers = consumer_status.get("workers", {}) if isinstance(consumer_status, dict) else {}

        producer_metrics = source_workers.get("source_producer_synthetic_frame_source", {})
        receiver_metrics = consumer_workers.get("data_receiver", {})

        boundary_crossings = 0
        if isinstance(router_stats, dict):
            rs = router_stats.get("router_stats", router_stats)
            if isinstance(rs, dict):
                boundary_crossings = int(rs.get("frame_boundary_crossings", 0) or 0)

        report = {
            "tier": "синтетика",
            "recipe": _RECIPE.name,
            "duration_sec": duration,
            "source_fps": producer_metrics.get("effective_hz"),
            "consumer_fps": receiver_metrics.get("effective_hz"),
            "source_perf_probes": producer_metrics.get("perf_probes"),
            "consumer_perf_probes": receiver_metrics.get("perf_probes"),
            "frame_boundary_crossings_total": boundary_crossings,
            "frame_boundary_crossings_per_frame": (
                round(boundary_crossings / producer_metrics.get("cycles"), 3)
                if producer_metrics.get("cycles")
                else None
            ),
            "frames_produced": producer_metrics.get("cycles"),
            "frames_consumed": receiver_metrics.get("cycles"),
        }
        print("[g1-probe] результат:")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
