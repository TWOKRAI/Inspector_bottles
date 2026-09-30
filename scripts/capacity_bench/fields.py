"""Поля кейса из ответа `introspect_telemetry(proc)["levels"]`."""

from __future__ import annotations

SHM_KEYS = ("bytes_written", "bytes_read", "bytes_mapped", "stale_drops", "torn_reads")


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _dict(x) -> dict:
    return x if isinstance(x, dict) else {}


def _worker_values(workers: dict, key: str) -> list:
    return [w[key] for w in workers.values() if isinstance(w, dict) and _num(w.get(key))]


def extract_fields(levels: dict) -> dict:
    """Поля отчёта; отсутствующее -> None (`plugin_ms` -> {}), не бросает."""
    levels = _dict(levels)
    workers = _dict(levels.get("workers"))
    state = _dict(levels.get("state"))
    cpu = _dict(state.get("cpu"))
    shm = _dict(state.get("shm"))
    plugin_ms = state.get("plugin_ms")

    queue_wait = _worker_values(workers, "queue_wait_ms")
    transport = _worker_values(workers, "transport_ms")
    pacer_late = _worker_values(workers, "pacer_late")
    return {
        "hz": state.get("fps") if _num(state.get("fps")) else None,
        "inner_cores": cpu.get("cores") if _num(cpu.get("cores")) else None,
        "plugin_ms": dict(plugin_ms) if isinstance(plugin_ms, dict) else {},
        "queue_wait_ms": max(queue_wait) if queue_wait else None,
        "transport_ms": max(transport) if transport else None,
        "pacer_late": sum(pacer_late) if pacer_late else None,
        "shm": {k: shm[k] for k in SHM_KEYS if k in shm} or None,
    }


# Накопительные с запуска процесса; `bytes_mapped` — размер отображения (текущее значение).
_DELTA_SHM = ("bytes_written", "bytes_read", "stale_drops", "torn_reads")


def _delta(before, after):
    return after - before if _num(before) and _num(after) else None


def window(before: dict, after: dict) -> dict:
    """Поля окна замера: счётчики — `after - before`, остальное — из `after` как есть.

    Оба аргумента — выход `extract_fields` (снимок на t0 и снимок в конце). Счётчик, которого нет
    хотя бы на одной стороне, даёт None: молча брать абсолют нельзя — он копился с запуска процесса.
    """
    out = dict(after)
    out["pacer_late"] = _delta(before.get("pacer_late"), after.get("pacer_late"))
    shm_after, shm_before = after.get("shm"), _dict(before.get("shm"))
    if isinstance(shm_after, dict):
        out["shm"] = {k: _delta(shm_before.get(k), v) if k in _DELTA_SHM else v for k, v in shm_after.items()}
    return out
