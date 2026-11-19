# -*- coding: utf-8 -*-
"""Политика готовности узла: переназначение степени и удержание потери (Task 2.9, ADR-PM-061).

Purpose:
    Рецепт задаёт плагину (узлу) ключ ``readiness: {hold_s, severity}``. ``severity`` переназначает степень
    СОБСТВЕННЫХ причин плагина (например ``out_of_spec`` -> ``check_function``); ``hold_s`` удерживает потерю
    готовности как ``out_of_spec`` до ``hold_s`` секунд, если узел до неё был чист непрерывно не меньше ``hold_s``.
    Модуль — чистые функции и неизменяемые значения: без IO, без замков, часы приходят аргументом (``now``).
    Разрыв между наблюдениями больше ``OBSERVATION_GAP_MAX_S`` обнуляет историю чистоты (расчётный запас над
    периодом снимка: 0,5 с + хуки + ``_send_lock``, не замер). Умолчание (``ReadinessPolicy()``) поведение не меняет.

Public API:
    ``parse_policy(raw)`` — значение ключа рецепта -> ``ReadinessPolicy`` или ``str`` (нарушенное правило);
    ``apply_policy(items, policy, memory, now)`` — пары ``(severity, reason)`` -> пары после политики + новая память;
    ``ReadinessPolicy``, ``NodeMemory``, ``NEVER_CLEAN``; константы ``HOLD_MAX_S``, ``OBSERVATION_GAP_MAX_S``,
    ``CONFIG_INVALID_REASON``. Вызывается из ``PluginOrchestrator._plugin_reasons`` (generic/plugin_orchestrator.py).

Stability:
    Внутренний контракт фреймворка (new-lite): имена и правила — ADR-PM-061; пределы ``HOLD_MAX_S`` и
    ``OBSERVATION_GAP_MAX_S`` меняются только вместе с ADR. Импорт только ``math``, ``dataclasses`` и ``.schema``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .schema import READINESS_BLOCKING_SEVERITIES, READINESS_SEVERITIES

__all__ = [
    "CONFIG_INVALID_REASON",
    "HOLD_MAX_S",
    "NEVER_CLEAN",
    "NodeMemory",
    "OBSERVATION_GAP_MAX_S",
    "ReadinessPolicy",
    "apply_policy",
    "parse_policy",
]

#: Потолок разумности ``hold_s``, сек: ограничивает время маскировки потери и ловит опечатку вида ``hold_s: 100``.
#: К допуску PM не привязан (ADR-PM-061).
HOLD_MAX_S: float = 10.0
#: Самый большой разрыв между соседними наблюдениями узла, который ещё считается наблюдением, сек. Период снимка =
#: 0,5 с (``core/process_module.py``, ``_READINESS_SNAPSHOT_PERIOD_SEC``) + время всех ``readiness()`` процесса +
#: ожидание ``_send_lock`` при отправке push; запас 2,0 с на эти ожидания — расчёт, не замер. Больше — история
#: чистоты обнуляется.
OBSERVATION_GAP_MAX_S: float = 2.5
#: Текст причины ``failure`` (``source: "config"``), которую оркестратор добавляет при негодном ключе ``readiness``.
CONFIG_INVALID_REASON: str = "политика readiness в рецепте негодна"


@dataclass(frozen=True, slots=True)
class ReadinessPolicy:
    """Разобранная политика узла: удержание потери и переназначение степеней (пары ``(из, в)``)."""

    hold_s: float = 0.0
    remap: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class NodeMemory:
    """Память политики узла: начало непрерывной чистоты, начало окна удержания, время последнего наблюдения."""

    clean_since: float | None = None
    held_since: float | None = None
    seen_at: float | None = None


#: Узел ни разу не был чист (boot, разрыв наблюдения, упавший хук): потеря не удерживается.
NEVER_CLEAN = NodeMemory()


def parse_policy(raw: object) -> ReadinessPolicy | str:
    """Ключ ``readiness`` -> ``ReadinessPolicy``; негодный -> ``str`` с нарушенным правилом (без всего ``raw``)."""
    if raw is None:
        return ReadinessPolicy()
    if not isinstance(raw, dict):
        return f"ожидался словарь, получен {type(raw).__name__}"
    unknown = [k for k in raw if k not in ("hold_s", "severity")]
    if unknown:
        return f"неизвестный ключ {unknown[0]!r:.40}"
    hold_s = raw.get("hold_s", 0.0)
    if isinstance(hold_s, bool) or not isinstance(hold_s, (int, float)):
        return f"hold_s: ожидалось число, получен {type(hold_s).__name__}"
    if hold_s < 0 or hold_s > HOLD_MAX_S or not math.isfinite(hold_s):
        return f"hold_s вне [0, {HOLD_MAX_S}]"
    severity = raw.get("severity", {})
    if not isinstance(severity, dict):
        return f"severity: ожидался словарь, получен {type(severity).__name__}"
    scale = READINESS_SEVERITIES
    remap: list[tuple[str, str]] = []
    for k, v in severity.items():
        if k not in scale or v not in scale:
            return f"severity: пара {k!r:.40} -> {v!r:.40} вне шкалы"
        remap.append((scale[scale.index(k)], scale[scale.index(v)]))
    return ReadinessPolicy(hold_s=float(hold_s), remap=tuple(remap))


def apply_policy(
    items: list[tuple[str, str]], policy: ReadinessPolicy, memory: NodeMemory, now: float
) -> tuple[list[tuple[str, str]], NodeMemory]:
    """Применить политику к причинам узла; часы снаружи, вход не мутируется.

    Сначала переназначение степеней, потом удержание: переназначенная в блокирующую причина удерживается так же,
    как собственная. Текст причины не меняется. Правило «был чист» и разрыв наблюдения — ADR-PM-061.
    """
    remap = dict(policy.remap)
    mapped = [(remap.get(s, s), r) for s, r in items]
    if memory.seen_at is not None and now - memory.seen_at > OBSERVATION_GAP_MAX_S:
        memory = NEVER_CLEAN
    if not any(s in READINESS_BLOCKING_SEVERITIES for s, _ in mapped):
        kept = memory.clean_since is not None and memory.held_since is None
        return mapped, NodeMemory(clean_since=memory.clean_since if kept else now, seen_at=now)
    held = [("out_of_spec" if s in READINESS_BLOCKING_SEVERITIES else s, r) for s, r in mapped]
    if policy.hold_s > 0 and memory.held_since is not None and now - memory.held_since < policy.hold_s:
        return held, NodeMemory(clean_since=memory.clean_since, held_since=memory.held_since, seen_at=now)
    armed = memory.clean_since is not None and now - memory.clean_since >= policy.hold_s
    if policy.hold_s > 0 and memory.held_since is None and armed:
        return held, NodeMemory(clean_since=memory.clean_since, held_since=now, seen_at=now)
    return mapped, NodeMemory(seen_at=now)
