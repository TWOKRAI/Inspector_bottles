# -*- coding: utf-8 -*-
"""Тесты автора (hazard) — Task 5.2, `TruthLedger` (`Services/line_sim/core/truth.py`).

Независимый тестер (`test_acceptance_5_2.py`) закрепил литеральный сценарий A/B/C и базовые
свойства (идемпотентность `on_spawn`, no-op `on_despawn`, `None` до первого matched,
свежий словарь `counters()`). Здесь — то, что видно только автору механизма: обратный
порядок событий «задание и уход со сцены в одном кадре» (тестер закрепил только один
объект, поймавший задание и в этом же кадре уехавший со сцены — `caught`, не `missed`;
здесь — ДВА РАЗНЫХ объекта в одном логическом кадре, один ловит задание, другой уезжает
без единого задания, независимость их счётчиков друг от друга) и общий инвариант
`caught == caught_ok + caught_defect` / `missed == missed_ok + missed_defect` под
произвольным чередованием событий по нескольким объектам (контракт §1 обещает его "всегда",
тестер проверил только на одном финальном срезе).
"""

from __future__ import annotations

from Services.line_sim.core.matching import MatchResult
from Services.line_sim.core.truth import TruthLedger
from Services.line_sim.interfaces import ObjectPassport


def _passport(object_id: str, *, defect: str | None = None, spawn_encoder: float = 0.0) -> ObjectPassport:
    return ObjectPassport(
        object_id=object_id,
        class_name="square",
        angle_deg=0.0,
        defect=defect,
        spawn_encoder=spawn_encoder,
    )


# --------------------------------------------------------------------------- #
# Обратный сценарий к тестерскому "задание + уход со сцены в одном кадре":    #
# ДВА объекта, один ловит задание, другой уезжает БЕЗ задания -- одновременно #
# --------------------------------------------------------------------------- #


def test_leave_scene_without_job_while_sibling_matched_same_batch():
    """Один объект (A) ловит задание, ДРУГОЙ (B) в ТОМ ЖЕ логическом кадре уезжает со
    сцены без единого задания -- независимость учёта: A -> caught, B -> missed, ни один
    не путает счётчик и невязку другого."""
    ledger = TruthLedger()
    a = _passport("A")
    b = _passport("B")
    ledger.on_spawn(a)
    ledger.on_spawn(b)

    # produce() разбирает задания (_drain_jobs) ДО diff spawn/despawn -- порядок здесь
    # воспроизводит это: on_match(A) раньше on_despawn(B), оба в одном "кадре" вызова.
    ledger.on_match(MatchResult(outcome="matched", object_id="A", residual_mm=1.0))
    ledger.on_despawn("B")

    counters = ledger.counters()
    assert counters["caught"] == 1
    assert counters["missed"] == 1
    assert counters["on_belt"] == 0
    assert counters["pick_error_mean_mm"] == 1.0, "невязка B (которой не было) не должна попасть в pick_error A"


# --------------------------------------------------------------------------- #
# Инвариант caught==caught_ok+caught_defect / missed==missed_ok+missed_defect #
# на ЛЮБОМ префиксе чередующихся событий по нескольким объектам               #
# --------------------------------------------------------------------------- #


def test_invariant_caught_missed_split_holds_under_interleaving():
    """`caught == caught_ok + caught_defect` и `missed == missed_ok + missed_defect` --
    контракт §1 обещает это "всегда"; тестер проверил только итоговый срез одного
    сценария (A/B/C). Здесь -- проверка НА КАЖДОМ шаге чередующихся исходов по
    нескольким объектам (брак и не брак вперемешку)."""
    ledger = TruthLedger()
    passports = [
        _passport("ok-1"),
        _passport("def-1", defect="damaged"),
        _passport("ok-2"),
        _passport("def-2", defect="damaged"),
    ]
    for p in passports:
        ledger.on_spawn(p)

    steps = [
        lambda: ledger.on_match(MatchResult(outcome="matched", object_id="ok-1", residual_mm=0.1)),
        lambda: ledger.on_despawn("def-1"),
        lambda: ledger.on_match(MatchResult(outcome="matched", object_id="def-2", residual_mm=0.2)),
        lambda: ledger.on_despawn("ok-2"),
    ]
    for step in steps:
        step()
        counters = ledger.counters()
        assert counters["caught"] == counters["caught_ok"] + counters["caught_defect"], counters
        assert counters["missed"] == counters["missed_ok"] + counters["missed_defect"], counters

    final = ledger.counters()
    assert final["caught"] == 2
    assert final["caught_ok"] == 1
    assert final["caught_defect"] == 1
    assert final["missed"] == 2
    assert final["missed_ok"] == 1
    assert final["missed_defect"] == 1
