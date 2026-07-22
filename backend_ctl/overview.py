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

#: Доля целевого темпа, ниже которой воркер помечается ``hz_degraded``. Снимок, не
#: тренд: грубый порог-подсказка (философия модуля — «подсказать, куда смотреть»),
#: тонкий разбор темпа — целевым ``telemetry_history``.
HZ_DEGRADED_FRACTION: float = 0.5


def _is_positive(value: Any) -> bool:
    """Счётчик строго больше нуля. ``None`` («показания нет») порогом НЕ считается.

    Отдельный хелпер, а не ``value > 0``: после строгого края счётчик может быть
    ``None``, и сравнение роняло бы всю сводку — первую команду сессии.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _num(value: Any) -> Optional[float]:
    """Число из сырого статуса воркера или ``None`` (bool/строка/отсутствие — не число)."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _process_hz(workers: Optional[Dict[str, Any]]) -> tuple[Optional[float], List[Dict[str, Any]]]:
    """Темп процесса и подсказки о деградации из СЫРЫХ статусов воркеров.

    ``system_overview`` схлопывает воркеров до строк-статусов (компактность), теряя
    главный перф-сигнал ``effective_hz`` — тот же, что тянет soak-проба отдельным
    обходом. Возвращаем его прямо в сводку.

    Ведущий темп процесса — максимум ``effective_hz`` по воркерам (как soak-проба):
    один медленный воркер не занижает картину. Отдельно — список воркеров, чей
    ``effective_hz`` строго ниже :data:`HZ_DEGRADED_FRACTION` своего целевого темпа
    (``1000/target_interval_ms``): каждый — подсказка ``hz_degraded``. Воркер без
    объявленного target порогом не судится (не с чем сравнивать).

    Returns:
        ``(ведущий effective_hz | None, [{worker, effective_hz, target_hz}])``.
    """
    if not isinstance(workers, dict):
        return None, []
    rates: List[float] = []
    degraded: List[Dict[str, Any]] = []
    for name, w in workers.items():
        if not isinstance(w, dict):
            continue
        hz = _num(w.get("effective_hz"))
        if hz is not None:
            rates.append(hz)
        target_ms = _num(w.get("target_interval_ms"))
        if hz is not None and target_ms is not None and target_ms > 0:
            target_hz = 1000.0 / target_ms
            if hz < HZ_DEGRADED_FRACTION * target_hz:
                degraded.append({"worker": name, "effective_hz": round(hz, 2), "target_hz": round(target_hz, 2)})
    leading = round(max(rates), 2) if rates else None
    return leading, degraded


def system_overview(drv: Any, *, timeout: Optional[float] = None) -> Dict[str, Any]:
    """Компактная сводка системы + аномалии (см. докстроку модуля).

    Returns:
        ``{"success": True, "processes": {name: {ok, status, workers, router,
        queues, memory_ok, hz, missing?}}, "telemetry": {"fps": {path: value}},
        "driver": {late_replies, event_errors, watch_resub_errors,
        events_evicted}, "anomalies": [...], "anomaly_count": N}``. Пустая
        топология (бэкенд не прогрет) → ``processes == {}`` + hint.

        Счётчики в ``router`` могут быть ``None`` — «показания нет» (строгий край
        ``protocol.py``), это НЕ ноль. Ключ ``missing`` появляется только при
        расхождении формы ответа и дублируется аномалией ``counter_missing``.
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
    def _collect(proc: str) -> Any:
        """Секция одного процесса; ЛЮБОЙ сбой возвращается значением, не исключением.

        Контракт модуля — best-effort: «не ответившая ручка — честная пометка, остальные
        секции работают». Но исключение внутри пула (не error-dict, а именно raise:
        разрыв соединения, кривой ответ) пробивалось наружу через ``pool.map`` и роняло
        ВЕСЬ overview — первая команда сессии падала целиком из-за одного больного
        процесса. Возвращаем исключение как значение и разбираем ниже.
        """
        try:
            return (
                drv.worker_status(proc, timeout=timeout),
                drv.router_stats(proc, timeout=timeout),
                drv.queues(proc, timeout=timeout),
                drv.introspect_memory(proc, timeout=timeout),
            )
        except Exception as exc:  # noqa: BLE001 — сбой одного процесса не должен рушить сводку
            return exc

    collected: Dict[str, tuple] = {}
    if procs:
        with ThreadPoolExecutor(max_workers=min(8, len(procs)), thread_name_prefix="bctl-overview") as pool:
            collected = dict(zip(procs, pool.map(_collect, procs)))

    for proc in procs:
        section = collected[proc]
        if isinstance(section, BaseException):
            processes[proc] = {
                "ok": False,
                "error": f"{type(section).__name__}: {section}",
                "process": proc,
            }
            anomalies.append(
                {
                    "kind": "introspect_failed",
                    "process": proc,
                    "detail": f"сбор секции упал: {type(section).__name__}: {section}",
                }
            )
            continue
        ws, rs, qd, mem = section
        # Воркеры — до статус-строки: сводка компактна, детали — get_status.
        workers = {name: (w.get("status") if isinstance(w, dict) else w) for name, w in (ws.workers or {}).items()}
        # Главный перф-сигнал воркеров (effective_hz) сводка теряла, схлопывая их до
        # статус-строк — за ним приходилось идти в introspect.status отдельно. Ведём
        # ведущий темп процесса прямо в карточке; отставание от target — подсказка.
        leading_hz, hz_degraded = _process_hz(ws.workers)
        failed_handles = [
            name
            for name, ok in (("status", ws.ok), ("router_stats", rs.ok), ("queues", qd.ok), ("memory", mem.ok))
            if not ok
        ]
        # Ключи, по которым ручка данных не дала. Пусто при здоровой форме — карточка
        # тогда байт-в-байт прежняя, лишнего шума в типовой сводке нет.
        missing_by_source = {
            source: names
            for source, names in (
                ("router", rs.missing),
                ("queues", qd.missing),
                ("status", ws.missing),
                ("memory", mem.missing),
            )
            if names
        }
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
            "hz": leading_hz,
        }
        if missing_by_source:
            processes[proc]["missing"] = missing_by_source

        if failed_handles:
            anomalies.append(
                {
                    "kind": "introspect_failed",
                    "process": proc,
                    "detail": f"не ответили ручки: {', '.join(failed_handles)}",
                }
            )
        # Отсутствующий счётчик — аномалия сам по себе, а не тихий пропуск: раньше
        # ответ без секции ``router_stats`` давал «0 и тишину», и агент читал это как
        # доказанное «трафика не было». Ручка, ответившая не тем, отличается от
        # не ответившей — поэтому причина названа в detail.
        for source, keys in (("router_stats", rs.missing), ("queues", qd.missing)):
            if not keys:
                continue
            answered = rs.ok if source == "router_stats" else qd.ok
            cause = "ручка ответила, форма разошлась" if answered else "ручка не ответила"
            anomalies.append(
                {
                    "kind": "counter_missing",
                    "process": proc,
                    "detail": f"{source}: нет показаний по {', '.join(keys)} ({cause})",
                }
            )
        if _is_positive(rs.middleware_dropped):
            anomalies.append(
                {"kind": "router_dropped", "process": proc, "detail": f"middleware_dropped={rs.middleware_dropped}"}
            )
        if _is_positive(rs.errors):
            anomalies.append({"kind": "router_errors", "process": proc, "detail": f"errors={rs.errors}"})
        if ws.ok and ws.status not in (None, "running"):
            anomalies.append({"kind": "process_not_running", "process": proc, "detail": f"status={ws.status!r}"})
        for hit in hz_degraded:
            anomalies.append(
                {
                    "kind": "hz_degraded",
                    "process": proc,
                    "detail": f"воркер {hit['worker']!r}: {hit['effective_hz']} Гц < {HZ_DEGRADED_FRACTION:.0%} "
                    f"от target {hit['target_hz']} Гц",
                }
            )
        for qname, depth in (qd.sizes or {}).items():
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

    # Счётчики driver'а КУМУЛЯТИВНЫ: одна давняя ошибка светилась аномалией в КАЖДОЙ
    # последующей сводке, и «свежая беда» была неотличима от «шрама» (Task 5.3).
    # Флагаем только прирост с прошлого overview; lifetime-значения остаются в ответе
    # плоскими ключами (на них опираются потребители), дельты — рядом в ``deltas``.
    totals = {
        "late_replies": drv.late_replies,
        "event_errors": drv.event_errors,
        "watch_resub_errors": drv.watch_resub_errors,
    }
    seen = getattr(drv, "_overview_counters_seen", None) or {}
    deltas = {key: value - seen.get(key, 0) for key, value in totals.items()}
    try:
        drv._overview_counters_seen = dict(totals)  # noqa: SLF001 — память сводки на этом driver'е
    except Exception:  # noqa: BLE001 — fake-driver без сеттера не должен ронять сводку
        pass

    driver_section = {
        **totals,
        "deltas": deltas,
        "events_evicted": events_evicted,
    }
    if deltas["late_replies"] > 0:
        anomalies.append(
            {
                "kind": "late_replies",
                "detail": f"late_replies +{deltas['late_replies']} (всего {totals['late_replies']})",
            }
        )
    if deltas["event_errors"] > 0:
        anomalies.append(
            {
                "kind": "event_callback_errors",
                "detail": f"event_errors +{deltas['event_errors']} (всего {totals['event_errors']})",
            }
        )
    if deltas["watch_resub_errors"] > 0:
        anomalies.append(
            {
                "kind": "watch_resub_errors",
                "detail": f"watch_resub_errors +{deltas['watch_resub_errors']} (всего {totals['watch_resub_errors']})",
            }
        )
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


__all__ = ["system_overview", "QUEUE_DEPTH_HINT", "HZ_DEGRADED_FRACTION"]
