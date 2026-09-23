# -*- coding: utf-8 -*-
"""Тесты автора (hazard) — Task 5.1b, причина «те же X/Y с новым энкодером» в
`TruthLedger` (`Services/line_sim/core/truth.py::TruthLedger.on_match`, §2 контракта
`plans/line-sim/phase-5-contract-5.1b.md`).

Независимый тестер (`test_acceptance_5_1b.py` в этом же пакете) закрепил базовые
литералы (matched+no_object на той же точке -> frozen, за окном -> нет, разные точки
-> нет, reset забывает память). Здесь — то, что видно только автору механизма:
поведение при НЕМОНОТОННОМ `job.t` (задания могут прийти по сети не в порядке
постановки — Δt отрицательный между соседними вызовами) и ограниченность памяти
`_recent_jobs` при долгом потоке БЕЗ единой ложной тревоги (деке не должна расти
неограниченно, если исход всегда `matched`).

Плюс дословные литералы §2 контракта (лид просил держать их в этом файле как
независимую от тестера проверку числами из самого текста контракта, не выведенными
из кода): A matched + B matched (разные диски у триггера) -> frozen=0; A matched +
no_object рядом -> frozen=1; тот же no_object за окном (t=10.5) -> frozen=0;
no_object в пустом месте -> frozen=0.
"""

from __future__ import annotations

from Services.line_sim.core.matching import JobDone, MatchResult
from Services.line_sim.core.truth import TruthLedger
from Services.line_sim.interfaces import ObjectPassport


def _passport(object_id: str) -> ObjectPassport:
    return ObjectPassport(object_id=object_id, class_name="square", angle_deg=0.0, defect=None, spawn_encoder=0.0)


def _job(index: int, x_mm: float, y_mm: float, ecap: int, t: float) -> JobDone:
    return JobDone(index=index, x_mm=x_mm, y_mm=y_mm, ecap=ecap, t=t)


def _matched(residual_mm: float = 0.5, object_id: str = "obj-1") -> MatchResult:
    return MatchResult(outcome="matched", object_id=object_id, residual_mm=residual_mm)


def _no_object() -> MatchResult:
    return MatchResult(outcome="no_object", object_id=None, residual_mm=None)


# --------------------------------------------------------------------------- #
# Контракт §2, литералы дословно (независимая от тестера сверка числами)      #
# --------------------------------------------------------------------------- #


def test_contract_literal_distinct_disks_at_trigger_no_frozen():
    """matched A (0,20,e=1000,t=0) + matched B (0,20,e=2190,t=1.6) -> caught 2,
    false_alarm_frozen_xy 0 (разные диски у триггера — повтором не считаются, frozen
    проверяется только на no_object)."""
    ledger = TruthLedger()
    ledger.on_spawn(_passport("A"))
    ledger.on_spawn(_passport("B"))
    ledger.on_match(MatchResult(outcome="matched", object_id="A", residual_mm=0.1), job=_job(1, 0.0, 20.0, 1000, 0.0))
    ledger.on_match(MatchResult(outcome="matched", object_id="B", residual_mm=0.1), job=_job(2, 0.0, 20.0, 2190, 1.6))

    counters = ledger.counters()
    assert counters["caught"] == 2
    assert counters["false_alarm_frozen_xy"] == 0


def test_contract_literal_matched_then_no_object_same_xy_is_frozen():
    """matched A (0,20,e=1000,t=0) + no_object (0,20,e=1362,t=0.5) -> false_alarm 1,
    false_alarm_frozen_xy 1."""
    ledger = TruthLedger()
    ledger.on_match(_matched(), job=_job(1, 0.0, 20.0, 1000, 0.0))
    ledger.on_match(_no_object(), job=_job(2, 0.0, 20.0, 1362, 0.5))

    counters = ledger.counters()
    assert counters["false_alarm"] == 1
    assert counters["false_alarm_frozen_xy"] == 1


def test_contract_literal_same_no_object_outside_window_is_not_frozen():
    """Тот же сценарий, но второе задание в t=10.5 (окно 10.0 с) -> false_alarm 1,
    false_alarm_frozen_xy 0."""
    ledger = TruthLedger()
    ledger.on_match(_matched(), job=_job(1, 0.0, 20.0, 1000, 0.0))
    ledger.on_match(_no_object(), job=_job(2, 0.0, 20.0, 1362, 10.5))

    counters = ledger.counters()
    assert counters["false_alarm"] == 1
    assert counters["false_alarm_frozen_xy"] == 0


def test_contract_literal_no_object_empty_space_is_not_frozen():
    """no_object (0,-500,e=3000,t=2) без похожих недавних -> false_alarm 1,
    false_alarm_frozen_xy 0."""
    ledger = TruthLedger()
    ledger.on_match(_no_object(), job=_job(1, 0.0, -500.0, 3000, 2.0))

    counters = ledger.counters()
    assert counters["false_alarm"] == 1
    assert counters["false_alarm_frozen_xy"] == 0


# --------------------------------------------------------------------------- #
# Hazard 1 — немонотонный job.t (задание пришло по сети не по порядку)        #
# --------------------------------------------------------------------------- #


def test_non_monotonic_t_does_not_crash_or_evict_wrongly():
    """Механизм чистит недавние ТОЛЬКО левым дропом по формуле
    ``job.t - entry.t > frozen_window_s`` (§2 контракта) — часов у ledger нет, время
    берётся из самого ``job.t``. Если задание с более старым ``t`` придёт ПОСЛЕ
    задания с более новым (сеть не гарантирует порядок доставки), разница
    ``job.t - entry.t`` для более свежих записей в деке получится ОТРИЦАТЕЛЬНОЙ —
    формула её не вычистит (не больше окна), и вызов не должен падать.

    Фиксируем закреплённое поведение: пришедшее не по порядку задание НЕ считается
    протухшим относительно более новых записей уже в деке (отрицательная разница —
    не « > window»), поэтому свежая запись остаётся доступной для проверки frozen-xy
    следующим вызовом."""
    ledger = TruthLedger()
    # t=0 -> t=5 (по порядку, копится память).
    ledger.on_match(_matched(), job=_job(1, 0.0, 20.0, 1000, 0.0))
    ledger.on_match(_matched(residual_mm=0.1, object_id="obj-2"), job=_job(2, 100.0, 20.0, 5000, 5.0))
    # t=2 пришло ПОСЛЕ t=5 — немонотонно. Не должно падать.
    ledger.on_match(_no_object(), job=_job(3, 0.0, 20.0, 1500, 2.0))

    counters = ledger.counters()  # не бросило исключение — сам факт уже проверка
    assert counters["false_alarm"] == 1
    # job#3 (t=2) сравнивается с job#1 (t=0, x=0,y=20,ecap=1000): 2-0=2, не > 10 ->
    # НЕ вычищено, x/y совпадают, ecap разный -> frozen. job#2 (t=5, x=100) — далеко
    # по X, не совпадает. Итог: сработал первый.
    assert counters["false_alarm_frozen_xy"] == 1, (
        f"задание не по порядку (t=2 после t=5) должно было сравниться с job#1 "
        f"(t=0), а не быть отброшено как протухшее: {counters!r}"
    )


# --------------------------------------------------------------------------- #
# Hazard 2 — память недавних заданий ограничена под длинным потоком без       #
#            единой ложной тревоги (окно по job.t, не число заданий)         #
# --------------------------------------------------------------------------- #


def test_recent_jobs_memory_is_bounded_under_long_matched_stream():
    """10 000 подряд ``matched`` заданий с шагом ``t += 1.6`` (частота, близкая к
    replay реального стенда) НЕ должны копить недавние без ограничения — окно
    ``frozen_window_s`` (дефолт 10.0) чистит слева на каждом вызове с job, поэтому
    в деке остаётся не больше ``window/step + 1`` записей, а не 10 000."""
    ledger = TruthLedger()
    step_s = 1.6
    window_s = 10.0
    for i in range(10_000):
        t = i * step_s
        ledger.on_spawn(_passport(f"obj-{i}"))
        result = MatchResult(outcome="matched", object_id=f"obj-{i}", residual_mm=0.1)
        ledger.on_match(result, job=_job(i, float(i), 20.0, 1000 + i, t))

    max_expected = int(window_s / step_s) + 2  # запас на округление
    assert len(ledger._recent_jobs) <= max_expected, (
        f"деке недавних заданий выросла без ограничения: {len(ledger._recent_jobs)} "
        f"записей при потоке 10000 matched-заданий, ожидалось <= {max_expected}"
    )
    assert ledger.counters()["caught"] == 10_000
    assert ledger.counters()["false_alarm_frozen_xy"] == 0
