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


def _reason(node: str, reason: str, source: str, severity: str = "failure") -> dict:
    """Причина от самого агрегата (форма — design.md §3.3, как у причин листа); умолчание — ``failure``."""
    return {"node": node, "severity": severity, "reason": reason, "source": source}


def _process_reasons(name: str, leaves: dict, alive: dict, now: float, stale_s: float) -> tuple[list[dict], bool]:
    """Причины одного процесса и признак «молчит»: ``(причины, не жив или нет свежего листа)``."""
    if not alive.get(name, False):
        return [_reason(name, "процесс не жив", "liveness")], True
    leaf = leaves.get(name)
    at = leaf.get("at") if isinstance(leaf, dict) else None
    if not isinstance(at, (int, float)) or now - at > stale_s:
        return [_reason(name, "нет отчёта о готовности", "liveness")], True
    reasons = [dict(r) for r in (leaf.get("reasons") or []) if isinstance(r, dict)]
    if not leaf.get("ready", False) and not any(r.get("severity") == "failure" for r in reasons):
        reasons.append(_reason(name, f"{name} не готов", "report"))
    return reasons, False


def _has_failure(reasons: list[dict]) -> bool:
    return any(r.get("severity") == "failure" for r in reasons)


def _restarting(name: str, silent: bool, reasons: list[dict], auto_restart: frozenset[str], down_since: dict) -> bool:
    """Процесс из ``auto_restart`` в перезапуске: молчит, либо поднялся, но ``failure`` ещё не ушли (запись есть)."""
    return name in auto_restart and (silent or (name in down_since and _has_failure(reasons)))


def evaluate(
    expected: list[str],
    leaves: dict,
    alive: dict,
    now: float,
    stale_s: float,
    *,
    running: bool = False,
    auto_restart: frozenset[str] = frozenset(),
    down_since: dict[str, float] | None = None,
    grace_s: float = 30.0,
    given_up: frozenset[str] = frozenset(),
) -> tuple[bool, list[dict]]:
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

    Автоперезапуск в работе (Task 1.8) — только при ``running=True``; иначе флаг не действует и мёртвый
    процесс остаётся ``failure``. Процесс из ``auto_restart``, который молчит (не жив / нет свежего листа)
    или поднялся, но его ``failure`` ещё не ушли и запись в ``down_since`` есть, вместо ВСЕХ своих причин
    даёт одну (``node`` = процесс, ``source`` = ``liveness``):
      * процесс в ``given_up`` (супервизор отказался) -> ``failure`` «<процесс>: супервизор отказался от
        перезапуска» — выигрывает у окна и действует сразу;
      * ``now - down_since[процесс] >= grace_s`` -> ``failure`` «<процесс>: перезапуск не завершён за
        <grace_s> с» (записи нет — окно началось сейчас, ``0``);
      * иначе ``out_of_spec`` «перезапуск <процесс>»: на ``ready`` не влияет.
    Ведёт ``down_since`` не эта функция, а ``restart_window``.

    ``ready`` = среди итоговых причин нет ``failure`` и ``check_function``.
    """
    since = down_since or {}
    reasons: list[dict] = []
    for name in expected:
        process_reasons, silent = _process_reasons(name, leaves, alive, now, stale_s)
        if running and _restarting(name, silent, process_reasons, auto_restart, since):
            reasons.append(restart_reason(name, now - since.get(name, now), grace_s, name in given_up))
        else:
            reasons.extend(process_reasons)
    ready = not has_blocking(reasons)
    return ready, reasons


def restart_reason(name: str, elapsed_s: float, grace_s: float, given_up: bool) -> dict:
    """Единственная причина процесса в перезапуске (см. ``evaluate``); ``elapsed_s`` — сколько идёт окно."""
    if given_up:
        return _reason(name, f"{name}: супервизор отказался от перезапуска", "liveness")
    if elapsed_s >= grace_s:
        return _reason(name, f"{name}: перезапуск не завершён за {grace_s:g} с", "liveness")
    return _reason(name, f"перезапуск {name}", "liveness", severity="out_of_spec")


def auto_restart_config_reason(name: str) -> dict:
    """Причина «флаг ``run_auto_restart`` без ``enabled: true``»: супервизор такой процесс не поднимет (Task 1.8)."""
    return _reason(name, f"{name}: `run_auto_restart` требует `enabled: true`", "config")


def restart_window(
    expected: list[str],
    leaves: dict,
    alive: dict,
    now: float,
    stale_s: float,
    *,
    running: bool,
    auto_restart: frozenset[str],
    down_since: dict[str, float],
) -> dict[str, float]:
    """Новый ``down_since`` после очередного тика: ``{процесс: когда началось окно перезапуска}`` (Task 1.8).

    Чистая функция без IO: возвращает новый словарь, ``down_since`` не меняет. Вне ``running`` окон нет (``{}``):
    запись не переживает ``running -> stopping -> ready``. В ``running`` запись есть только у процесса из
    ``auto_restart`` из ``expected``:
      * молчит (не жив / нет свежего листа) -> запись сохраняется, а у нового — ``now``;
      * в перезапуске (``_restarting``: молчит, либо поднялся, но ``failure`` ещё не ушли) -> запись сохраняется, у
        нового — ``now``. Сбой живого процесса со свежим листом, у которого записи не было, — не перезапуск;
      * иначе (жив, лист свежий, ``failure`` нет) записи нет: окно закрыто, следующее падение откроет новое.
    Процесс, вышедший из ``expected`` / ``auto_restart``, из записи уходит (она не растёт).
    """
    if not running:
        return {}
    window: dict[str, float] = {}
    for name in expected:
        if name not in auto_restart:
            continue
        process_reasons, silent = _process_reasons(name, leaves, alive, now, stale_s)
        if _restarting(name, silent, process_reasons, auto_restart, down_since):
            window[name] = down_since.get(name, now)
    return window


def unconfirmed_stop(
    expected: list[str], unconfirmed: dict[str, float], leaves: dict, alive: dict
) -> tuple[dict[str, float], list[dict]]:
    """Множество «не подтвердили остановку» после оценки: ``(оставшиеся, причины)`` (Task 1.4, design.md §3.2 п.3).

    Чистая функция без IO. ``unconfirmed`` — ``{процесс: N}``, где ``N`` — срок ожидания ``paused``, за который
    процесс не ответил. Процесс выходит из множества, когда его лист показывает ``paused: true``, или он не жив
    (``alive == False``: остановленным считается мёртвый), или его нет в ``expected`` (топология сменилась).
    Для каждого оставшегося, по порядку ``expected``, — ``failure`` / ``report`` «<процесс> не подтвердил остановку
    за <N> с» (``node`` = процесс; тот же текст на каждой оценке, не накапливается).
    """
    remaining: dict[str, float] = {}
    reasons: list[dict] = []
    for name in expected:
        n = unconfirmed.get(name)
        if n is None:
            continue
        leaf = leaves.get(name)
        if not alive.get(name, False) or (isinstance(leaf, dict) and leaf.get("paused") is True):
            continue
        remaining[name] = n
        reasons.append(stop_unconfirmed_reason(name, n))
    return remaining, reasons


def stop_unconfirmed_reason(name: str, timeout_s: float) -> dict:
    """Причина «<процесс> не подтвердил остановку за <N> с» (``{:g}``: 0.5 -> «0.5», 10.0 -> «10»)."""
    return _reason(name, f"{name} не подтвердил остановку за {timeout_s:g} с", "report")


def has_blocking(reasons: list[dict]) -> bool:
    """Среди причин есть блокирующая START (``failure`` / ``check_function``)."""
    return any(r.get("severity") in BLOCKING_SEVERITIES for r in reasons)


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
