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


def discover_processes(drv: Any, timeout: float = 15.0) -> list[str]:
    """Имена процессов живой топологии.

    Через ПУБЛИЧНЫЙ ``system_overview`` (его ключи ``processes`` — и есть список),
    а не через приватный ``drv._discover_processes``. Сами метрики оттуда брать
    нельзя: overview схлопывает воркеров до строк-статусов, теряя ``effective_hz``
    и ``perf_probes`` — их добираем per-process в :func:`_sample`.
    """
    try:
        overview = drv.system_overview(timeout=timeout)
    except Exception:
        return []
    payload = unwrap(overview, leaf=True)
    procs = payload.get("processes") if isinstance(payload, dict) else None
    return sorted(procs) if isinstance(procs, dict) else []


def _worker_metrics(workers: dict) -> dict[str, Any]:
    """Свести воркеров процесса к FPS/циклам/пробам, не зная их имён.

    Универсально по топологии: у синтетики воркеры зовутся
    ``source_producer_*``/``data_receiver``, у прод-рецептов — иначе. Берём
    максимальный ``effective_hz`` как темп процесса (ведущий воркер) и
    сохраняем пробы всех воркеров, у кого они есть.
    """
    if not isinstance(workers, dict):
        return {"fps": None, "cycles": None, "perf_probes": {}}
    hz = [w.get("effective_hz") for w in workers.values() if isinstance(w, dict) and w.get("effective_hz")]
    cycles = [w.get("cycles") for w in workers.values() if isinstance(w, dict) and w.get("cycles")]
    probes = {name: w["perf_probes"] for name, w in workers.items() if isinstance(w, dict) and w.get("perf_probes")}
    return {
        "fps": round(max(hz), 2) if hz else None,
        "cycles": max(cycles) if cycles else None,
        "perf_probes": probes,
    }


def _sample(drv: Any, elapsed: float, processes: list[str]) -> dict[str, Any]:
    """Снимок ВСЕХ процессов топологии: FPS, циклы, perf-пробы, счётчики, RSS.

    Раньше проба была зашита под 2-процессный синтетический тракт
    (``synthetic_source``/``consumer``). Прод-рецепты (``webcam_sketch`` — 7
    процессов с живой камерой) требуют универсального обхода, иначе soak
    реального тракта невозможен.
    """
    per_process: dict[str, Any] = {}
    for proc in processes:
        try:
            status = unwrap(drv.introspect_status(proc, timeout=8.0), leaf=True)
        except Exception as exc:  # noqa: BLE001 — один больной процесс не рушит сэмпл
            per_process[proc] = {"error": repr(exc)}
            continue
        if not isinstance(status, dict):
            per_process[proc] = {"error": "status не dict"}
            continue
        entry = _worker_metrics(status.get("workers", {}))
        entry["pid"] = status.get("pid")
        entry["rss_mb"] = _rss_mb(status.get("pid"))
        try:
            entry["counters"] = _counters(drv.introspect_router_stats(proc, timeout=8.0))
        except Exception:  # noqa: BLE001
            entry["counters"] = dict.fromkeys(_COUNTER_KEYS, 0)
        per_process[proc] = entry

    return {"elapsed_sec": round(elapsed, 1), "processes": per_process}


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
    fps_first_last: dict[str, list] = {}
    rss_first_last: dict[str, list] = {}

    for proc, entry in (last.get("processes") or {}).items():
        if "error" in entry:
            findings.append(f"{proc}: сэмпл не снялся — {entry['error']}")
            continue
        prev = (first.get("processes") or {}).get(proc, {})

        counters = entry.get("counters") or {}
        for key in _LEAK_KEYS:
            if counters.get(key):
                findings.append(f"{proc}.{key} = {counters[key]} (ожидалось 0)")

        cache_first = (prev.get("counters") or {}).get("frame_handle_cache_size", 0)
        cache_last = counters.get("frame_handle_cache_size", 0)
        if cache_last > cache_first:
            findings.append(
                f"{proc}.frame_handle_cache_size рос {cache_first} -> {cache_last} "
                "(резидуал G.5: рост кэша на инкарнацию под zero-copy)"
            )

        if entry.get("pid") and prev.get("pid") and entry["pid"] != prev["pid"]:
            findings.append(f"{proc}: pid сменился {prev['pid']} -> {entry['pid']} (был рестарт процесса)")

        rss_first, rss_last = prev.get("rss_mb"), entry.get("rss_mb")
        if rss_first and rss_last:
            rss_first_last[proc] = [rss_first, rss_last]
            if rss_last > rss_first * 1.20:
                findings.append(f"{proc} RSS {rss_first} -> {rss_last} МБ (рост > 20% — проверить утечку)")

        fps_first_last[proc] = [prev.get("fps"), entry.get("fps")]

    return {
        "samples": len(samples),
        "duration_sec": last["elapsed_sec"],
        "fps_first_last": fps_first_last,
        "rss_first_last_mb": rss_first_last,
        "counters_last": {p: e.get("counters") for p, e in (last.get("processes") or {}).items() if "error" not in e},
        "verdict": "CLEAN" if not findings else "FINDINGS",
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ф7 G.7 Фаза 3 — длинный soak (синтетика)")
    parser.add_argument("--duration", type=float, default=7200.0, help="длительность, сек (умолч. 2ч)")
    parser.add_argument("--interval", type=float, default=300.0, help="период снятия, сек (умолч. 5 мин)")
    parser.add_argument("--out", type=Path, default=Path("logs/g7_soak.jsonl"), help="путь JSONL")
    parser.add_argument("--port", type=int, default=8766, help="порт backend_ctl харнесса")
    parser.add_argument(
        "--recipe",
        type=str,
        default=_RECIPE.name,
        help="имя рецепта в multiprocess_prototype/recipes (умолч. синтетика g1_perf_probe.yaml; "
        "прод-тракт — webcam_sketch.yaml)",
    )
    args = parser.parse_args()

    recipe = _RECIPES / args.recipe
    if not recipe.exists():
        print(f"[g7-soak] нет рецепта {recipe}")
        return 2

    os.environ.setdefault("BACKEND_CTL", "1")
    os.environ.setdefault("FW_PERF_PROBES", "1")
    for flag in _SOAK_FLAGS:
        os.environ.setdefault(flag, "1")

    args.out.parent.mkdir(parents=True, exist_ok=True)

    from backend_ctl.harness import BackendHarness

    print(f"[g7-soak] recipe={recipe.name} duration={args.duration}s interval={args.interval}s")
    print(f"[g7-soak] флаги ON: {', '.join(_SOAK_FLAGS)} (+FW_PERF_PROBES; FW_GC_SCHEDULED намеренно OFF)")
    print(f"[g7-soak] JSONL: {args.out}")

    samples: list[dict[str, Any]] = []
    started = time.monotonic()
    harness = BackendHarness(recipe=recipe, port=args.port)

    with harness as drv, args.out.open("w", encoding="utf-8") as fp:
        processes = discover_processes(drv)
        if not processes:
            print("[g7-soak] топология пуста — бэкенд не поднялся или не прогрет")
            return 2
        print(f"[g7-soak] процессов в топологии: {len(processes)} — {', '.join(processes)}")

        while True:
            elapsed = time.monotonic() - started
            if elapsed >= args.duration:
                break
            # Спим ДО снятия: на elapsed=0 тракт ещё не прогрет (FPS/пробы пустые).
            time.sleep(min(args.interval, args.duration - elapsed))

            try:
                sample = _sample(drv, time.monotonic() - started, processes)
            except Exception as exc:  # noqa: BLE001 — soak не должен падать из-за одного сэмпла
                sample = {"elapsed_sec": round(time.monotonic() - started, 1), "error": repr(exc)}
                print(f"[g7-soak] сэмпл упал: {exc!r} (soak продолжается)")
            else:
                # Агрегат по всей топологии — построчный дамп 7 процессов нечитаем.
                agg = {k: 0 for k in ("frame_torn_reads", "frame_stale_drops", "frame_loan_exhausted")}
                fps_line = []
                rss_total = 0.0
                for proc, entry in sample["processes"].items():
                    if "error" in entry:
                        continue
                    for k in agg:
                        agg[k] += (entry.get("counters") or {}).get(k, 0)
                    if entry.get("fps"):
                        fps_line.append(f"{proc}={entry['fps']}")
                    rss_total += entry.get("rss_mb") or 0.0
                print(
                    f"[g7-soak] t={sample['elapsed_sec']:>6.0f}s "
                    f"fps[{' '.join(fps_line)}] "
                    f"torn={agg['frame_torn_reads']} stale={agg['frame_stale_drops']} "
                    f"exhausted={agg['frame_loan_exhausted']} rss_total={rss_total:.0f}МБ"
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
