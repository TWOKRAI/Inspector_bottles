# -*- coding: utf-8 -*-
"""Ф7 G.7 Фаза 3 — длинный soak на полном наборе флагов (tier: синтетика).

Отличие от :mod:`g1_perf_probe` (разовый замер): тот снимает ОДИН снимок в конце,
а soak ищет **тренды** — утечку слотов/handle-кэша, дрейф p99, рост RSS. Поэтому
здесь тракт поднимается один раз, а метрики снимаются периодически (§1 плана:
«снапшот раз в 5 мин soak-скриптом») и пишутся в JSONL.

Полный набор флагов лесенки Фазы 1 включается ЯВНО: дефолты в реестре G.F пока
``False`` (флип дефолтов — пункт 4 приёмки Фазы 3, ПОСЛЕ этого soak).
``FW_GC_SCHEDULED`` намеренно остаётся OFF — он measurement-gated по дизайну G.9
и на шаге 9 лесенки условие активации не выполнилось (GC-выбросов p99 нет).

Запуск (Windows, из корня репозитория)::

    python -m backend_ctl.probes.g7_soak_probe --duration 7200 --interval 300

Результат: JSONL с сэмплами + итоговая сводка с дельтами «первый → последний»
сэмпл и вердиктом по утечкам. Числа переносятся в baseline.md вручную
(живой документ плана, не генерируется автоматически).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from backend_ctl.protocol import unwrap

_RECIPES = Path(__file__).resolve().parent.parent.parent / "multiprocess_prototype" / "recipes"
_RECIPE = _RECIPES / "g1_perf_probe.yaml"

#: Полный набор лесенки Фазы 1 (9 флагов, все прошли гейт 2026-07-16).
#: ``FW_GC_SCHEDULED`` НЕ включаем — measurement-gated, см. докстринг модуля.
_SOAK_FLAGS: tuple[str, ...] = (
    "FW_DATA_PLANE_DICTS",
    "FW_SHM_SEQLOCK",
    "FW_SHM_OWNER_INCARNATION",
    "FW_SHM_HANDLE_CACHE",
    "FW_QOS_PROFILES",
    "FW_SHM_ZERO_COPY",
    "FW_SHM_LOAN_PROTOCOL",
    "FW_USE_KIND_CHANNELS",
    "FW_GC_FREEZE",
)

#: Счётчики SHM-тракта (те же, что в гейте лесенки — g1_perf_probe._COUNTER_KEYS).
_COUNTER_KEYS: tuple[str, ...] = (
    "frame_boundary_crossings",
    "frame_torn_reads",
    "frame_stale_drops",
    "frame_slots_released",
    "frame_slots_reclaimed",
    "frame_loan_exhausted",
    "frame_handle_cache_size",
    "frame_pickle_fallbacks",
    "queue_data_evicted",
    "system_evict_blocked",
)

#: Счётчики, рост которых на soak = ДЕФЕКТ (утечка/потеря), а не норма.
#: ``frame_slots_released`` и ``frame_boundary_crossings`` растут по построению.
_LEAK_KEYS: tuple[str, ...] = (
    "frame_torn_reads",
    "frame_stale_drops",
    "frame_loan_exhausted",
    "frame_pickle_fallbacks",
    "queue_data_evicted",
    "system_evict_blocked",
)


def _counters(router_stats_res: dict) -> dict[str, int]:
    """Достать ``_COUNTER_KEYS`` из ответа ``introspect.router_stats``.

    Робастно к обёртке (см. g1_perf_probe._shm_counters): ответ приходит либо
    ``{..., "router_stats": {...}}``, либо плоско. Отсутствующий счётчик → 0.
    """
    payload = unwrap(router_stats_res, leaf=True)
    rs = payload.get("router_stats", payload) if isinstance(payload, dict) else {}
    if not isinstance(rs, dict):
        rs = {}
    return {k: int(rs.get(k, 0) or 0) for k in _COUNTER_KEYS}


def _rss_mb(pid: int | None) -> float | None:
    """RSS процесса в МБ по pid, или ``None`` если процесс/psutil недоступны.

    Через ``psutil``, а НЕ через ``introspect.memory``: последний отдаёт инвентарь
    SHM/пула/очередей (см. ``MemoryStats``), а не RSS ОС — процессной памяти там
    нет. Soak не должен падать из-за необязательной метрики: любая ошибка → None.
    """
    if not pid:
        return None
    try:
        import psutil

        return round(psutil.Process(int(pid)).memory_info().rss / (1024 * 1024), 1)
    except Exception:
        return None


def _sample(drv: Any, elapsed: float) -> dict[str, Any]:
    """Один снимок обоих концов тракта: FPS, perf-пробы, счётчики, RSS."""
    source_status = unwrap(drv.introspect_status("synthetic_source", timeout=8.0), leaf=True)
    consumer_status = unwrap(drv.introspect_status("consumer", timeout=8.0), leaf=True)

    source_workers = source_status.get("workers", {}) if isinstance(source_status, dict) else {}
    consumer_workers = consumer_status.get("workers", {}) if isinstance(consumer_status, dict) else {}
    producer = source_workers.get("source_producer_synthetic_frame_source", {})
    receiver = consumer_workers.get("data_receiver", {})

    return {
        "elapsed_sec": round(elapsed, 1),
        "source_fps": producer.get("effective_hz"),
        "consumer_fps": receiver.get("effective_hz"),
        "frames_produced": producer.get("cycles"),
        "frames_consumed": receiver.get("cycles"),
        "source_perf_probes": producer.get("perf_probes"),
        "consumer_perf_probes": receiver.get("perf_probes"),
        "counters": {
            "source": _counters(drv.introspect_router_stats("synthetic_source", timeout=8.0)),
            "consumer": _counters(drv.introspect_router_stats("consumer", timeout=8.0)),
        },
        # pid берём из уже снятого status — без лишнего IPC-раунда на сэмпл.
        "rss_mb": {
            "synthetic_source": _rss_mb(source_status.get("pid") if isinstance(source_status, dict) else None),
            "consumer": _rss_mb(consumer_status.get("pid") if isinstance(consumer_status, dict) else None),
        },
    }


def _summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Сводка «первый → последний» + вердикт по утечкам.

    Вердикт намеренно грубый и громкий: любой ненулевой leak-счётчик или рост
    handle-кэша попадает в ``findings``. Разбор — глазами, скрипт только не даёт
    дефекту утонуть в 24 сэмплах JSONL.
    """
    if not samples:
        return {"verdict": "NO_SAMPLES", "findings": ["soak не снял ни одного сэмпла"]}

    first, last = samples[0], samples[-1]
    findings: list[str] = []

    for end in ("source", "consumer"):
        for key in _LEAK_KEYS:
            val = last["counters"][end].get(key, 0)
            if val:
                findings.append(f"{end}.{key} = {val} (ожидалось 0)")
        cache_first = first["counters"][end].get("frame_handle_cache_size", 0)
        cache_last = last["counters"][end].get("frame_handle_cache_size", 0)
        if cache_last > cache_first:
            findings.append(
                f"{end}.frame_handle_cache_size рос {cache_first} -> {cache_last} "
                "(резидуал G.5: рост кэша на инкарнацию под zero-copy)"
            )

    for proc in ("synthetic_source", "consumer"):
        rss_first = (first.get("rss_mb") or {}).get(proc)
        rss_last = (last.get("rss_mb") or {}).get(proc)
        if rss_first and rss_last and rss_last > rss_first * 1.20:
            findings.append(f"{proc} RSS {rss_first} -> {rss_last} МБ (рост > 20% — проверить утечку)")

    return {
        "samples": len(samples),
        "duration_sec": last["elapsed_sec"],
        "fps_first_last": {
            "source": [first["source_fps"], last["source_fps"]],
            "consumer": [first["consumer_fps"], last["consumer_fps"]],
        },
        "rss_first_last_mb": {"first": first.get("rss_mb"), "last": last.get("rss_mb")},
        "counters_last": last["counters"],
        "verdict": "CLEAN" if not findings else "FINDINGS",
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ф7 G.7 Фаза 3 — длинный soak (синтетика)")
    parser.add_argument("--duration", type=float, default=7200.0, help="длительность, сек (умолч. 2ч)")
    parser.add_argument("--interval", type=float, default=300.0, help="период снятия, сек (умолч. 5 мин)")
    parser.add_argument("--out", type=Path, default=Path("logs/g7_soak.jsonl"), help="путь JSONL")
    parser.add_argument("--port", type=int, default=8766, help="порт backend_ctl харнесса")
    args = parser.parse_args()

    os.environ.setdefault("BACKEND_CTL", "1")
    os.environ.setdefault("FW_PERF_PROBES", "1")
    for flag in _SOAK_FLAGS:
        os.environ.setdefault(flag, "1")

    args.out.parent.mkdir(parents=True, exist_ok=True)

    from backend_ctl.harness import BackendHarness

    print(f"[g7-soak] recipe={_RECIPE.name} duration={args.duration}s interval={args.interval}s")
    print(f"[g7-soak] флаги ON: {', '.join(_SOAK_FLAGS)} (+FW_PERF_PROBES; FW_GC_SCHEDULED намеренно OFF)")
    print(f"[g7-soak] JSONL: {args.out}")

    samples: list[dict[str, Any]] = []
    started = time.monotonic()
    harness = BackendHarness(recipe=_RECIPE, port=args.port)

    with harness as drv, args.out.open("w", encoding="utf-8") as fp:
        while True:
            elapsed = time.monotonic() - started
            if elapsed >= args.duration:
                break
            # Спим ДО снятия: на elapsed=0 тракт ещё не прогрет (FPS/пробы пустые).
            time.sleep(min(args.interval, args.duration - elapsed))

            try:
                sample = _sample(drv, time.monotonic() - started)
            except Exception as exc:  # noqa: BLE001 — soak не должен падать из-за одного сэмпла
                sample = {"elapsed_sec": round(time.monotonic() - started, 1), "error": repr(exc)}
                print(f"[g7-soak] сэмпл упал: {exc!r} (soak продолжается)")
            else:
                cs = sample["counters"]["source"]
                cc = sample["counters"]["consumer"]
                print(
                    f"[g7-soak] t={sample['elapsed_sec']:>6.0f}s "
                    f"fps={sample['source_fps']}/{sample['consumer_fps']} "
                    f"torn={cc['frame_torn_reads']} stale={cc['frame_stale_drops']} "
                    f"released={cs['frame_slots_released']} exhausted={cs['frame_loan_exhausted']} "
                    f"cache={cc['frame_handle_cache_size']} rss={sample['rss_mb']}"
                )

            samples.append(sample)
            fp.write(json.dumps(sample, ensure_ascii=False) + "\n")
            fp.flush()  # soak длинный — не терять данные при обрыве

        summary = _summarize([s for s in samples if "error" not in s])
        fp.write(json.dumps({"summary": summary}, ensure_ascii=False) + "\n")

    print("\n[g7-soak] СВОДКА:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("verdict") == "CLEAN" else 1


if __name__ == "__main__":
    sys.exit(main())
