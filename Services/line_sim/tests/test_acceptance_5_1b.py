# -*- coding: utf-8 -*-
"""RED-приёмка Task 5.1b — причина «те же X/Y, новый энкодер» ПЕРЕЕЗЖАЕТ в TruthLedger.

Независимый tester, worktree на коммите контракта лида (602be8ec, до реализации).
Контракт — ТОЛЬКО ``plans/line-sim/phase-5-contract-5.1b.md`` §2:
``TruthLedger.on_match(result, job=None)`` (``Services/line_sim/core/truth.py``) должен
запоминать недавние задания (в пределах ``frozen_window_s``, ctor, дефолт 10.0, по
``job.t``) и на ``no_object`` с недавним заданием на расстоянии
``hypot(Δx,Δy) < frozen_radius_mm`` (ctor, дефолт 5.0) и ДРУГИМ ``ecap`` —
``false_alarm_frozen_xy += 1`` (подмножество ``false_alarm``, а не отдельный
исход). Новый ключ ``counters()`` — ``false_alarm_frozen_xy``; ``reset()`` зануляет
его и забывает недавние задания.

Сегодня ``TruthLedger`` (``Services/line_sim/tests/test_sim_journal_causes.py`` читать
НЕ пытались — эталон контракта 5.2 в ``truth.py`` самой) НЕ принимает параметр
``job`` в ``on_match`` и НЕ имеет ключа ``false_alarm_frozen_xy`` — ожидаемый провал:
``TypeError`` на лишний именованный аргумент ``job=`` (сигнатура ``on_match(self,
result)`` без него) для тестов, которые его передают, и ``KeyError``/``AssertionError``
на отсутствующий ключ.

Литералы: FACTOR_MM/BELT_UX/BELT_UY не участвуют — проверка frozen-xy плоская
(``hypot(Δx,Δy)``, без поправки на проезд ленты), в отличие от невязки трекинга
``match_job``/старого ``SimJournal._find_origin``.
"""

from __future__ import annotations

import pytest

from Services.line_sim.core.matching import JobDone, MatchResult
from Services.line_sim.core.truth import TruthLedger
from Services.line_sim.interfaces import ObjectPassport

pytestmark = pytest.mark.timeout(30)


def _job(index: int, x_mm: float, y_mm: float, ecap: int, t: float) -> JobDone:
    return JobDone(index=index, x_mm=x_mm, y_mm=y_mm, ecap=ecap, t=t)


def _matched(residual_mm: float = 0.5, object_id: str = "obj-1") -> MatchResult:
    return MatchResult(outcome="matched", object_id=object_id, residual_mm=residual_mm)


def _no_object() -> MatchResult:
    return MatchResult(outcome="no_object", object_id=None, residual_mm=None)


# --------------------------------------------------------------------------- #
# Литерал 1 — та же точка, другой энкодер, внутри окна -> frozen             #
# --------------------------------------------------------------------------- #


def test_no_object_same_xy_is_frozen() -> None:
    """(10.0, 20.0, e=1000) matched, затем (10.0, 20.0, e=1362) no_object,
    Δt=1с < frozen_window_s=10.0 -> false_alarm_frozen_xy=1, false_alarm=1."""
    ledger = TruthLedger()
    ledger.on_match(_matched(), job=_job(1, 10.0, 20.0, 1000, 100.0))
    ledger.on_match(_no_object(), job=_job(2, 10.0, 20.0, 1362, 101.0))

    counters = ledger.counters()
    assert counters["false_alarm"] == 1
    assert counters["false_alarm_frozen_xy"] == 1


# --------------------------------------------------------------------------- #
# Литерал 2 — та же точка, другой энкодер, ЗА окном -> НЕ frozen             #
# --------------------------------------------------------------------------- #


def test_outside_window_not_frozen() -> None:
    """Δt=11с > frozen_window_s=10.0 -> обычный false_alarm, не frozen."""
    ledger = TruthLedger()
    ledger.on_match(_matched(), job=_job(1, 10.0, 20.0, 1000, 100.0))
    ledger.on_match(_no_object(), job=_job(2, 10.0, 20.0, 1900, 111.0))

    counters = ledger.counters()
    assert counters["false_alarm"] == 1
    assert counters["false_alarm_frozen_xy"] == 0


# --------------------------------------------------------------------------- #
# Литерал 3 — другая точка (разные детали) -> НЕ frozen                      #
# --------------------------------------------------------------------------- #


def test_distinct_disks_at_trigger_not_frozen() -> None:
    """(10.0, 20.0) и (60.0, 20.0) — 50мм >> frozen_radius_mm=5.0 -> не frozen."""
    ledger = TruthLedger()
    ledger.on_match(_matched(), job=_job(1, 10.0, 20.0, 1000, 100.0))
    ledger.on_match(_no_object(), job=_job(2, 60.0, 20.0, 1900, 101.0))

    counters = ledger.counters()
    assert counters["false_alarm"] == 1
    assert counters["false_alarm_frozen_xy"] == 0


# --------------------------------------------------------------------------- #
# Литерал 4 — пустое место, вообще без недавних заданий -> НЕ frozen         #
# --------------------------------------------------------------------------- #


def test_empty_space_not_frozen() -> None:
    """Первое же задание — no_object, недавних заданий нет вовсе."""
    ledger = TruthLedger()
    ledger.on_match(_no_object(), job=_job(1, 10.0, 20.0, 1000, 100.0))

    counters = ledger.counters()
    assert counters["false_alarm"] == 1
    assert counters["false_alarm_frozen_xy"] == 0


# --------------------------------------------------------------------------- #
# reset() зануляет счётчик И забывает недавние задания                       #
# --------------------------------------------------------------------------- #


def test_reset_forgets_recent_jobs() -> None:
    ledger = TruthLedger()
    ledger.on_match(_matched(), job=_job(1, 10.0, 20.0, 1000, 100.0))
    ledger.on_match(_no_object(), job=_job(2, 10.0, 20.0, 1362, 101.0))
    assert ledger.counters()["false_alarm_frozen_xy"] == 1, "предусловие: frozen сработал до reset"

    ledger.reset()
    zeroed = ledger.counters()
    assert zeroed["false_alarm_frozen_xy"] == 0
    assert zeroed["false_alarm"] == 0

    # та же точка, что "забытое" задание #1 — но reset() стёр память, поэтому это
    # обычный false_alarm, не frozen (§2 контракта: reset "забывает недавние задания").
    ledger.on_match(_no_object(), job=_job(3, 10.0, 20.0, 1900, 200.0))
    after = ledger.counters()
    assert after["false_alarm"] == 1
    assert after["false_alarm_frozen_xy"] == 0, "reset() должен был забыть задание #1 -> не frozen"


# --------------------------------------------------------------------------- #
# on_match БЕЗ job — старое поведение 5.2 (может быть уже ЗЕЛЁНЫМ сегодня)   #
# --------------------------------------------------------------------------- #


def test_on_match_without_job_keeps_5_2_behavior() -> None:
    """§3 контракта: движок не собран -> job передаётся, но ветка "нет кандидатов"
    не требует job для caught/dup — здесь только гарантия обратной совместимости
    вызова без job (как делал старый код §2 контракта 5.2). Может остаться ЗЕЛЁНЫМ,
    если ``job`` уже сегодня опциональный по умолчанию — фиксируем явно как факт,
    не как ожидание провала."""
    ledger = TruthLedger()
    ledger.on_spawn(
        ObjectPassport(object_id="obj-1", class_name="square", angle_deg=0.0, defect=None, spawn_encoder=0.0)
    )
    ledger.on_match(_matched())  # без job=... — сигнатура 5.2, ДО этой задачи
    assert ledger.counters()["caught"] == 1
