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
    BACKEND_CTL=1 python -m backend_ctl.probes.g1_perf_probe [duration_sec]

Числа печатаются в консоль (json) — переносятся в baseline.md вручную
(живой документ плана, не генерируется автоматически).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_RECIPES = Path(__file__).resolve().parent.parent.parent / "multiprocess_prototype" / "recipes"
_RECIPE = _RECIPES / "g1_perf_probe.yaml"


def _unwrap(res: dict) -> dict:
    """Достать вложенный handler-результат: request() → {success, result:{...}}."""
    if not isinstance(res, dict):
        return {}
    return res.get("result") if isinstance(res.get("result"), dict) else res


#: Счётчики потерь/здоровья SHM-тракта, агрегируемые ``RouterManager.get_stats``
#: (Ф7 G.7 лесенка §0/§1): гейт каждого шага требует их = 0 или объяснимы.
_COUNTER_KEYS: tuple[str, ...] = (
    "frame_boundary_crossings",  # G.6: границ процесса на кадр
    "frame_pickle_fallbacks",  # G.3d: кадр ушёл медленным pickle-путём (сбой SHM-write)
    "frame_torn_reads",  # G.3b seqlock: torn/in-progress чтение дропнуто
    "frame_stale_drops",  # G.5c zero-copy: слот перезаписан под живым view
    "frame_loan_exhausted",  # G.5d loan: free-list исчерпан (читатели отстали)
    "frame_slots_released",  # G.5d loan: слотов освобождено release'ами (здоровье цикла)
    "frame_slots_reclaimed",  # G.5e loan: реклейм после смерти читателя (kill-9 без release)
    "frame_handle_cache_size",  # G.7 0.5: размер reader-кэша handle (рост = утечка под zero-copy)
    "queue_data_evicted",  # G.4a QoS: дроп из полной data-очереди (drop_oldest)
    "queue_system_evict_blocked",  # G.4a QoS: system-очередь никогда молча не дропает
)


def _shm_counters(router_stats_res: dict) -> dict:
    """Достать набор ``_COUNTER_KEYS`` из ответа ``introspect.router_stats``.

    Робастно к обёртке: ответ приходит либо ``{..., "router_stats": {<counters>}}``,
    либо (реже) плоско. Отсутствующий счётчик → ``0`` (int). Чистая функция над
    dict-контрактом — юнит-тестируется без запуска системы.
    """
    payload = _unwrap(router_stats_res)
    rs = payload.get("router_stats", payload) if isinstance(payload, dict) else {}
    if not isinstance(rs, dict):
        rs = {}
    return {k: int(rs.get(k, 0) or 0) for k in _COUNTER_KEYS}


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
        # Ф7 G.7 лесенка: счётчики потерь SHM обоих концов тракта (source = владелец/
        # писатель кольца → slots_released/reclaimed/loan_exhausted/queue_data_evicted;
        # consumer = reader → torn_reads/stale_drops/handle_cache_size). Гейт шага (§0)
        # требует их = 0 или объяснимы — поэтому дампим оба конца, а не только источник.
        source_counters = _shm_counters(drv.introspect_router_stats("synthetic_source", timeout=8.0))
        consumer_counters = _shm_counters(drv.introspect_router_stats("consumer", timeout=8.0))

        source_workers = source_status.get("workers", {}) if isinstance(source_status, dict) else {}
        consumer_workers = consumer_status.get("workers", {}) if isinstance(consumer_status, dict) else {}

        producer_metrics = source_workers.get("source_producer_synthetic_frame_source", {})
        receiver_metrics = consumer_workers.get("data_receiver", {})

        boundary_crossings = source_counters["frame_boundary_crossings"]

        report = {
            "tier": "синтетика",
            "recipe": _RECIPE.name,
            "duration_sec": duration,
            "source_fps": producer_metrics.get("effective_hz"),
            "consumer_fps": receiver_metrics.get("effective_hz"),
            "source_perf_probes": producer_metrics.get("perf_probes"),
            "consumer_perf_probes": receiver_metrics.get("perf_probes"),
            # Ф7 G.7: счётчики потерь/здоровья SHM обоих концов — для гейта шага лесенки.
            "shm_counters": {"source": source_counters, "consumer": consumer_counters},
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
