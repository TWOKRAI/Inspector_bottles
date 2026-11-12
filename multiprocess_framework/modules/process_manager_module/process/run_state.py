# -*- coding: utf-8 -*-
"""Машина состояний работы системы (Task 1.1 плана system-run-state, design.md §3.2).

Чистая функция без IO: ``transition(state, event, *, ready, stop_done)`` возвращает новое
состояние и код отказа (``None`` — переход принят или событие — no-op). Держатель состояния,
замок и событие ``run_event`` живут в ``ProcessManagerProcess`` (``_run_apply``); здесь только
таблица.

События:
  * ``start`` / ``stop`` — команды ``system.run.start`` / ``system.run.stop``;
  * ``ack`` — квитирование аварии (Task 1.7), ``stop_done`` читает только ``ack`` в ``fault``;
  * ``apply`` — начало применения топологии (Task 1.5);
  * ``shutdown`` — начало остановки системы (Task 1.4);
  * ``settled`` — подъём/применение топологии закончен (``booting``) или итог STOP (``stopping``);
  * ``tick`` — очередная оценка готовности; потеря готовности в ``running`` — это ``tick`` с
    ``ready=False`` (отдельного события ``fault`` нет).
"""

from __future__ import annotations

from enum import Enum


class RunState(str, Enum):
    """Состояние работы системы (значения — design.md §3.2)."""

    booting = "booting"
    not_ready = "not_ready"
    ready = "ready"
    running = "running"
    stopping = "stopping"
    fault = "fault"
    shutting_down = "shutting_down"


#: Допустимые события машины.
EVENTS: frozenset[str] = frozenset({"start", "stop", "ack", "apply", "shutdown", "settled", "tick"})


#: Степени причины, блокирующие START (К3 CTO: ``check_function`` блокирует START и в ``running`` равен
#: потере готовности); ``out_of_spec`` / ``maintenance`` не блокируют.
BLOCKING_SEVERITIES: frozenset[str] = frozenset({"failure", "check_function"})


def _reason(node: str, reason: str, source: str) -> dict:
    """Причина-``failure`` от самого агрегата (форма — design.md §3.3, как у причин листа)."""
    return {"node": node, "severity": "failure", "reason": reason, "source": source}


def evaluate(expected: list[str], leaves: dict, alive: dict, now: float, stale_s: float) -> tuple[bool, list[dict]]:
    """Готовность системы по процессам набора: ``(ready, reasons)`` (Task 1.3, design.md §3.3).

    Чистая функция без IO и без чтения часов: ``now`` и ``stale_s`` приходят снаружи.

    ``expected`` — имена процессов применённой топологии; ``leaves[name]`` — сам dict ``readiness``
    процесса (``{"ready", "reasons", "paused", "at"}``), нет ключа = нет листа; ``alive[name]`` —
    процесс жив (нет ключа = не жив: молчание = не готов). Процессы вне ``expected`` не читаются.

    Для каждого процесса набора, по порядку ``expected``:
      * не жив -> ``failure`` / ``liveness`` «процесс не жив»;
      * нет листа или ``at`` старше ``stale_s`` (судим по ``at`` — времени расчёта снимка, а не по
        heartbeat: мёртвый поток-наблюдатель при живом heartbeat иначе выглядел бы готовым) ->
        ``failure`` / ``liveness`` «нет отчёта о готовности»;
      * иначе причины листа как есть; лист ``ready: false`` без ``failure`` среди его причин ->
        добавлена ``failure`` / ``report`` «<процесс> не готов».

    ``ready`` = среди итоговых причин нет ``failure`` и ``check_function``.
    """
    reasons: list[dict] = []
    for name in expected:
        if not alive.get(name, False):
            reasons.append(_reason(name, "процесс не жив", "liveness"))
            continue
        leaf = leaves.get(name)
        at = leaf.get("at") if isinstance(leaf, dict) else None
        if not isinstance(at, (int, float)) or now - at > stale_s:
            reasons.append(_reason(name, "нет отчёта о готовности", "liveness"))
            continue
        leaf_reasons = [dict(r) for r in (leaf.get("reasons") or []) if isinstance(r, dict)]
        reasons.extend(leaf_reasons)
        if not leaf.get("ready", False) and not any(r.get("severity") == "failure" for r in leaf_reasons):
            reasons.append(_reason(name, f"{name} не готов", "report"))
    ready = not any(r.get("severity") in BLOCKING_SEVERITIES for r in reasons)
    return ready, reasons


def _r(ready: bool) -> RunState:
    """Ячейка ``R`` таблицы: ``ready`` при ``ready=True``, иначе ``not_ready``."""
    return RunState.ready if ready else RunState.not_ready


def transition(state: RunState, event: str, *, ready: bool, stop_done: bool = False) -> tuple[RunState, str | None]:
    """Один шаг машины: ``(новое состояние, код отказа | None)``.

    Таблица — design.md §3.2 (литералом в Task 1.1, DESIGN п.1). Неизвестное событие —
    ``ValueError("unknown event")``; входные значения в текст не попадают (ADR-PMM-044 п.1).
    """
    if event not in EVENTS:
        raise ValueError("unknown event")
    state = RunState(state)
    S = RunState

    # Общая строка: shutdown из любого состояния ведёт в shutting_down без отказа.
    if event == "shutdown":
        return S.shutting_down, None

    if state is S.shutting_down:
        # Команды отказывают кодом shutting_down; внутренние события — no-op.
        if event in ("start", "stop", "ack", "apply"):
            return state, "shutting_down"
        return state, None

    if event == "ack":
        if state is S.fault:
            if stop_done:
                return _r(ready), None
            return state, "fault_stopping"
        return state, "no_fault"

    if state is S.booting:
        if event == "start":
            return state, "not_ready"
        if event == "settled":
            return _r(ready), None
        return state, None  # stop, apply, tick

    if state is S.not_ready:
        if event == "start":
            return state, "not_ready"
        if event == "apply":
            return S.booting, None
        if event == "tick":
            return _r(ready), None
        return state, None  # stop, settled

    if state is S.ready:
        if event == "start":
            # Готовность пропала между тиком и командой: в ready вернёт только tick.
            if ready:
                return S.running, None
            return S.not_ready, "not_ready"
        if event == "apply":
            return S.booting, None
        if event == "tick":
            return _r(ready), None
        return state, None  # stop, settled

    if state is S.running:
        if event == "start":
            return state, "already_running"
        if event == "stop":
            return S.stopping, None
        if event == "apply":
            return state, "running"
        if event == "tick":
            return (state, None) if ready else (S.fault, None)
        return state, None  # settled

    if state is S.stopping:
        if event in ("start", "apply"):
            return state, "stopping"
        if event == "settled":
            return _r(ready), None
        return state, None  # stop, tick

    # state is S.fault
    if event in ("start", "apply"):
        return state, "fault_unacknowledged"
    return state, None  # stop, settled, tick
