# -*- coding: utf-8 -*-
"""Ф7 G.7 Фаза 2 — fault-инъекции на полном наборе флагов (headless).

Поднимает синтетический тракт (``recipes/g1_perf_probe.yaml``: synthetic_source →
consumer) через :class:`BackendHarness` с ВКЛЮЧЁННЫМИ флагами движка (передаются
через env вызывающим — spawn наследует их детям), даёт трафику разогреться, затем
инъецирует отказ и снимает счётчики ``state.shm.*`` до/после для проверки инварианта.

Сценарии (argv[1]):
  kill_reader  (2.1) — SIGKILL читателя ``consumer`` под нагрузкой. Ожидание:
      supervisor (0.3) по confirmed-death шлёт ``shm_reclaim`` владельцу пула →
      ``frame_slots_reclaimed`` растёт, поток кадров источника живёт (FPS ≈ до),
      исчерпания free-list нет.
  kill_writer  (2.2) — SIGKILL писателя ``synthetic_source`` посреди работы.
      Ожидание: seqlock — читатель на in-progress слоте видит нечётный generation
      → torn drop (``frame_torn_reads``), слот НЕ отравлен, консьюмер не падает.

Запуск (флаги — в env; полный набор лесенки Фазы 1):
  BACKEND_CTL=1 FW_PERF_PROBES=1 FW_DATA_PLANE_DICTS=1 FW_SHM_SEQLOCK=1 \
  FW_SHM_OWNER_INCARNATION=1 FW_SHM_HANDLE_CACHE=1 FW_QOS_PROFILES=1 \
  FW_SHM_ZERO_COPY=1 FW_SHM_LOAN_PROTOCOL=1 FW_USE_KIND_CHANNELS=1 FW_GC_FREEZE=1 \
  python -m backend_ctl.probes.g7_fault_probe kill_reader

Числа печатаются json — переносятся в baseline.md вручную (живой документ плана).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from backend_ctl.probes.g1_perf_probe import _shm_counters

_RECIPES = Path(__file__).resolve().parent.parent.parent / "multiprocess_prototype" / "recipes"
_RECIPE = _RECIPES / "g1_perf_probe.yaml"

_SOURCE = "synthetic_source"  # писатель/владелец SHM-пула
_CONSUMER = "consumer"  # читатель (loan-потребитель)
_PORT = 8791  # свой порт (изоляция от общих фикстур/занятых 8765-8779)


def _unwrap(res: dict) -> dict:
    if not isinstance(res, dict):
        return {}
    return res.get("result") if isinstance(res.get("result"), dict) else res


def _fps(drv, process: str, worker: str) -> float | None:
    """effective_hz воркера процесса из introspect.status (None если недоступен)."""
    st = _unwrap(drv.introspect_status(process, timeout=6.0))
    workers = st.get("workers", {}) if isinstance(st, dict) else {}
    return (workers.get(worker, {}) or {}).get("effective_hz")


def _alive(drv, process: str) -> str | None:
    st = _unwrap(drv.introspect_status(process, timeout=6.0))
    return st.get("status") if isinstance(st, dict) else None


def main() -> int:
    scenario = sys.argv[1] if len(sys.argv) > 1 else "kill_reader"
    os.environ.setdefault("BACKEND_CTL", "1")
    os.environ.setdefault("FW_PERF_PROBES", "1")

    from backend_ctl.harness import BackendHarness

    victim = _CONSUMER if scenario == "kill_reader" else _SOURCE
    print(f"[g7-fault] сценарий={scenario}, жертва={victim}, recipe={_RECIPE.name}, порт={_PORT}")

    harness = BackendHarness(recipe=_RECIPE, port=_PORT)
    report: dict = {"scenario": scenario, "victim": victim}
    with harness as drv:
        time.sleep(3.0)  # разогрев: трафик пошёл, слоты займы/чтения активны

        source_before = _shm_counters(drv.introspect_router_stats(_SOURCE, timeout=8.0))
        consumer_before = _shm_counters(drv.introspect_router_stats(_CONSUMER, timeout=8.0))
        src_fps_before = _fps(drv, _SOURCE, "source_producer_synthetic_frame_source")

        killed_pid = harness.kill_child(victim)  # PID-точечный SIGKILL (не глобально)
        report["killed_pid"] = killed_pid

        # Дать супервизору поймать confirmed-death (poll 0.5с) → broadcast shm_reclaim →
        # owner реклеймит; + пронаблюдать, что источник продолжает лить кадры.
        time.sleep(5.0)

        source_after = _shm_counters(drv.introspect_router_stats(_SOURCE, timeout=8.0))
        consumer_after = _shm_counters(drv.introspect_router_stats(_CONSUMER, timeout=8.0))
        src_fps_after = _fps(drv, _SOURCE, "source_producer_synthetic_frame_source")

        def delta(a: dict, b: dict) -> dict:
            return {k: b.get(k, 0) - a.get(k, 0) for k in a}

        report.update(
            {
                "source_fps_before": src_fps_before,
                "source_fps_after": src_fps_after,
                "source_alive_after": _alive(drv, _SOURCE),
                "consumer_alive_after": _alive(drv, _CONSUMER),
                "source_counters_before": source_before,
                "source_counters_after": source_after,
                "source_delta": delta(source_before, source_after),
                "consumer_delta": delta(consumer_before, consumer_after),
            }
        )
        print("[g7-fault] результат:")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
