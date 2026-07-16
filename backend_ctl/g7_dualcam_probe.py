# -*- coding: utf-8 -*-
"""Ф7 G.7 Фаза 3 — мультикамерный smoke: две синтетические камеры, раздельные SHM.

Поднимает ``recipes/dualcam_synth.yaml`` (camera_0/camera_1 → consumer_0/consumer_1)
через :class:`BackendHarness` с флагами движка (env), крутит ``duration`` секунд и
снимает FPS + ``state.shm.*`` каждой из 4 нод. Проверяемый инвариант мультикамеры:
FW_SHM_OWNER_INCARNATION разводит имена SHM-сегментов владельцев → два кольца НЕ
коллизируют, оба тракта текут параллельно, счётчики потерь чисты.

Запуск (полный набор флагов — в env):
  BACKEND_CTL=1 FW_PERF_PROBES=1 FW_SHM_SEQLOCK=1 FW_SHM_OWNER_INCARNATION=1 \
  FW_SHM_HANDLE_CACHE=1 FW_QOS_PROFILES=1 FW_SHM_ZERO_COPY=1 FW_SHM_LOAN_PROTOCOL=1 \
  FW_DATA_PLANE_DICTS=1 FW_USE_KIND_CHANNELS=1 FW_GC_FREEZE=1 \
  python -m backend_ctl.g7_dualcam_probe [duration_sec]

Числа печатаются json → в baseline.md вручную (живой документ плана).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from backend_ctl.g1_perf_probe import _shm_counters

_RECIPES = Path(__file__).resolve().parent.parent / "multiprocess_prototype" / "recipes"
_RECIPE = _RECIPES / "dualcam_synth.yaml"
_PORT = 8792

_CAMERAS = ("camera_0", "camera_1")
_CONSUMERS = ("consumer_0", "consumer_1")
_SRC_WORKER = "source_producer_synthetic_frame_source"
_CON_WORKER = "data_receiver"


def _unwrap(res: dict) -> dict:
    if not isinstance(res, dict):
        return {}
    return res.get("result") if isinstance(res.get("result"), dict) else res


def _fps(drv, process: str, worker: str):
    st = _unwrap(drv.introspect_status(process, timeout=8.0))
    workers = st.get("workers", {}) if isinstance(st, dict) else {}
    return (workers.get(worker, {}) or {}).get("effective_hz")


def _cycles(drv, process: str, worker: str):
    st = _unwrap(drv.introspect_status(process, timeout=8.0))
    workers = st.get("workers", {}) if isinstance(st, dict) else {}
    return (workers.get(worker, {}) or {}).get("cycles")


def _nonzero(counters: dict) -> dict:
    """Только ненулевые счётчики (чтобы не тонуть в нулях)."""
    nz = {k: v for k, v in counters.items() if v and k != "frame_boundary_crossings"}
    return nz or "all-zero(loss)"


def main() -> int:
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
    os.environ.setdefault("BACKEND_CTL", "1")
    os.environ.setdefault("FW_PERF_PROBES", "1")

    from backend_ctl.harness import BackendHarness

    print(f"[g7-dualcam] recipe={_RECIPE.name}, порт={_PORT}, duration={duration}s")
    harness = BackendHarness(recipe=_RECIPE, port=_PORT)
    report: dict = {"recipe": _RECIPE.name, "duration_sec": duration, "cameras": {}}
    with harness as drv:
        time.sleep(duration)

        for cam, con in zip(_CAMERAS, _CONSUMERS):
            src_counters = _shm_counters(drv.introspect_router_stats(cam, timeout=8.0))
            con_counters = _shm_counters(drv.introspect_router_stats(con, timeout=8.0))
            report["cameras"][cam] = {
                "source_fps": _fps(drv, cam, _SRC_WORKER),
                "consumer_fps": _fps(drv, con, _CON_WORKER),
                "frames_produced": _cycles(drv, cam, _SRC_WORKER),
                "frames_consumed": _cycles(drv, con, _CON_WORKER),
                "source_loss": _nonzero(src_counters),
                "consumer_loss": _nonzero(con_counters),
                "handle_cache": con_counters["frame_handle_cache_size"],
            }
        print("[g7-dualcam] результат:")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
