# -*- coding: utf-8 -*-
"""overview.py — system_overview: «один вызов = вся картина» (B.3).

Первая команда любой сессии: компактная сводка по процессам + секция
``anomalies`` — ПОДСКАЗКИ (hints), не вердикты. Аналог ``kubectl get all``+``top``,
Grafana health, Erlang observer.

Fan-out на стороне driver'а СУЩЕСТВУЮЩИМИ ручками — ноль новых IPC-команд:
``introspect.status`` / ``introspect.router_stats`` / ``introspect.queues`` /
``introspect.memory`` по каждому процессу из state-топологии
(``state.get_subtree``), плюс ЛОКАЛЬНЫЕ источники без IPC: telemetry read-model
(fps, supervisor-события) и счётчики самого driver'а (late_replies,
event_errors, вытеснения из колец B.1).

Best-effort: не ответившая ручка — честная пометка в сводке и hint
``introspect_failed``, остальные секции работают. Каждая аномалия —
``{"kind", "process"?, "detail"}``; детект порогов сознательно грубый
(подсказать, куда смотреть), тонкая диагностика — целевыми инструментами.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

#: Глубина очереди, с которой подсвечивается backpressure-hint. Снимок — не тренд:
#: «очередь растёт» без истории не доказать, но глубокая очередь — повод смотреть.
QUEUE_DEPTH_HINT: int = 50


def system_overview(drv: Any, *, timeout: Optional[float] = None) -> Dict[str, Any]:
    """Компактная сводка системы + аномалии (см. докстроку модуля).

    Returns:
        ``{"success": True, "processes": {name: {ok, status, workers, router,
        queues, memory_ok}}, "telemetry": {"fps": {path: value}}, "driver":
        {late_replies, event_errors, watch_resub_errors, events_evicted},
        "anomalies": [...], "anomaly_count": N}``. Пустая топология (бэкенд не
        прогрет) → ``processes == {}`` + hint.
    """
    anomalies: List[Dict[str, Any]] = []
    processes: Dict[str, Dict[str, Any]] = {}

    procs = drv._discover_processes(timeout=timeout)
    if not procs:
        anomalies.append(
            {"kind": "empty_topology", "detail": "state-топология пуста — бэкенд не прогрет или нет соединения"}
        )

    # Fan-out параллельно по процессам: request() конкурентно-безопасен by design
    # (pending-слоты по request_id, один reader), а 4 серийных round-trip'а × N
    # процессов превращали бы «один вызов = вся картина» в серийный обход.
    def _collect(proc: str) -> tuple:
        return (
            drv.worker_status(proc, timeout=timeout),
            drv.router_stats(proc, timeout=timeout),
            drv.queues(proc, timeout=timeout),
            drv.introspect_memory(proc, timeout=timeout),
        )

    collected: Dict[str, tuple] = {}
    if procs:
        with ThreadPoolExecutor(max_workers=min(8, len(procs)), thread_name_prefix="bctl-overview") as pool:
            collected = dict(zip(procs, pool.map(_collect, procs)))

    for proc in procs:
        ws, rs, qd, mem = collected[proc]
        # Воркеры — до статус-строки: сводка компактна, детали — get_status.
        workers = {name: (w.get("status") if isinstance(w, dict) else w) for name, w in ws.workers.items()}
        failed_handles = [
            name
            for name, ok in (("status", ws.ok), ("router_stats", rs.ok), ("queues", qd.ok), ("memory", mem.ok))
            if not ok
        ]
        processes[proc] = {
            "ok": not failed_handles,
            "status": ws.status,
            "workers": workers,
            "router": {
                "sent_ok": rs.sent_ok,
                "received": rs.received,
                "middleware_dropped": rs.middleware_dropped,
                "errors": rs.errors,
            },
            "queues": qd.sizes,
            "memory_ok": mem.ok,
        }

        if failed_handles:
            anomalies.append(
                {
                    "kind": "introspect_failed",
                    "process": proc,
                    "detail": f"не ответили ручки: {', '.join(failed_handles)}",
                }
            )
        if rs.middleware_dropped > 0:
            anomalies.append(
                {"kind": "router_dropped", "process": proc, "detail": f"middleware_dropped={rs.middleware_dropped}"}
            )
        if rs.errors > 0:
            anomalies.append({"kind": "router_errors", "process": proc, "detail": f"errors={rs.errors}"})
        if ws.ok and ws.status not in (None, "running"):
            anomalies.append({"kind": "process_not_running", "process": proc, "detail": f"status={ws.status!r}"})
        for qname, depth in qd.sizes.items():
            if isinstance(depth, int) and depth >= QUEUE_DEPTH_HINT:
                anomalies.append(
                    {"kind": "queue_depth", "process": proc, "detail": f"очередь {qname!r} глубиной {depth}"}
                )

    # Локальные источники (0 IPC): ОДИН снимок read-model (двойной full-copy под
    # общим с reader-потоком локом был бы лишним) + фильтрация по суффиксам локально.
    snapshot = drv.telemetry_snapshot()
    fps: Dict[str, Any] = {}
    for path, rec in snapshot.get("metrics", {}).items():
        if drv._telemetry_matches_metric(path, "fps"):
            fps[path] = rec.get("value")
            proc = rec.get("process")
            running = proc in processes and processes[proc].get("status") == "running"
            if running and rec.get("value") == 0:
                anomalies.append({"kind": "fps_zero_while_running", "process": proc, "detail": path})
        elif drv._telemetry_matches_metric(path, "supervisor.event") and rec.get("value") == "recovered":
            anomalies.append({"kind": "recent_recovery", "process": rec.get("process"), "detail": f"{path}=recovered"})

    events_stats = drv.events_stats()
    events_evicted = {plane: st["evicted"] for plane, st in events_stats.get("planes", {}).items() if st.get("evicted")}
    driver_section = {
        "late_replies": drv.late_replies,
        "event_errors": drv.event_errors,
        "watch_resub_errors": drv.watch_resub_errors,
        "events_evicted": events_evicted,
    }
    if drv.late_replies > 0:
        anomalies.append({"kind": "late_replies", "detail": f"late_replies={drv.late_replies}"})
    if drv.event_errors > 0:
        anomalies.append({"kind": "event_callback_errors", "detail": f"event_errors={drv.event_errors}"})
    if drv.watch_resub_errors > 0:
        anomalies.append({"kind": "watch_resub_errors", "detail": f"watch_resub_errors={drv.watch_resub_errors}"})
    for plane, evicted in events_evicted.items():
        anomalies.append(
            {"kind": "events_evicted", "detail": f"плоскость {plane!r}: вытеснено {evicted} (читатели отстают)"}
        )

    return {
        "success": True,
        "processes": processes,
        "telemetry": {"fps": fps},
        "driver": driver_section,
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
    }


__all__ = ["system_overview", "QUEUE_DEPTH_HINT"]
