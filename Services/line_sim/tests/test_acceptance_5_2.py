# -*- coding: utf-8 -*-
"""Task 5.2 — независимый RED (тестер, worktree на коммите контракта 99022975, ДО реализации).

Контракт — ТОЛЬКО ``plans/line-sim/phase-5-contract-5.2.md`` §1 (``TruthLedger``), не код:
``Services/line_sim/core/truth.py`` СЕГОДНЯ НЕ СУЩЕСТВУЕТ — импорт нового модуля даёт
``ModuleNotFoundError`` на collection для ВСЕГО файла (тот же приём, что уже использует
``Plugins/sim/scene_source/tests/test_scene_source_acceptance.py`` для нового модуля целиком).

Класс чистый (без IPC, без лока, без часов) — входы строятся из РЕАЛЬНЫХ типов
``Services.line_sim.interfaces.ObjectPassport`` и ``Services.line_sim.core.matching.MatchResult``
(уже существуют, читаются, не угадываются).

Литералы сценария A/B/C — дословно §1 контракта (паспорты A и C без брака, B с
``defect="damaged"``; невязки 0.5/1.5 мм -> ``pick_error_mean_mm=1.0``,
``pick_error_max_mm=1.5``).
"""

from __future__ import annotations

import pytest

from Services.line_sim.core.matching import MatchResult
from Services.line_sim.core.truth import TruthLedger
from Services.line_sim.interfaces import ObjectPassport

pytestmark = pytest.mark.timeout(30)

#: Полный набор ключей counters() -- §1 контракта, дословно.
_EXPECTED_COUNTER_KEYS = {
    "caught",
    "caught_defect",
    "caught_ok",
    "missed",
    "missed_defect",
    "missed_ok",
    "dup_jobs",
    "false_alarm",
    "untracked_jobs",
    "on_belt",
    "pick_error_mean_mm",
    "pick_error_max_mm",
}


def _passport(object_id: str, *, defect: str | None = None, spawn_encoder: float = 0.0) -> ObjectPassport:
    """Минимальный валидный паспорт -- поля, не участвующие в контракте TruthLedger
    (class_name/angle_deg/layer_params), значения-заглушки."""
    return ObjectPassport(
        object_id=object_id,
        class_name="square",
        angle_deg=0.0,
        defect=defect,
        spawn_encoder=spawn_encoder,
    )


# --------------------------------------------------------------------------- #
# Литеральный сценарий A/B/C -- §1 контракта, точный текст                    #
# --------------------------------------------------------------------------- #


def test_literal_abc_scenario():
    """on_spawn(A,B,C); matched A 0.5мм; matched B 1.5мм; dup B; no_object;
    despawn(A) [уже поймана -- no-op]; despawn(C) [не решена -- missed] ->
    caught 2 (ok 1, defect 1), dup_jobs 1, missed 1 (ok 1, defect 0), false_alarm 1,
    untracked_jobs 0, on_belt 0, pick_error_mean_mm 1.0, pick_error_max_mm 1.5."""
    ledger = TruthLedger()
    a = _passport("A")
    b = _passport("B", defect="damaged")
    c = _passport("C")
    ledger.on_spawn(a)
    ledger.on_spawn(b)
    ledger.on_spawn(c)

    ledger.on_match(MatchResult(outcome="matched", object_id="A", residual_mm=0.5))
    ledger.on_match(MatchResult(outcome="matched", object_id="B", residual_mm=1.5))
    ledger.on_match(MatchResult(outcome="dup", object_id="B", residual_mm=0.2))
    ledger.on_match(MatchResult(outcome="no_object", object_id=None, residual_mm=None))
    ledger.on_despawn("A")  # A уже поймана -- контракт §1: no-op
    ledger.on_despawn("C")  # C не решена -- missed

    counters = ledger.counters()
    assert counters["caught"] == 2
    assert counters["caught_ok"] == 1
    assert counters["caught_defect"] == 1
    assert counters["dup_jobs"] == 1
    assert counters["missed"] == 1
    assert counters["missed_ok"] == 1
    assert counters["missed_defect"] == 0
    assert counters["false_alarm"] == 1
    assert counters["untracked_jobs"] == 0
    assert counters["on_belt"] == 0
    assert counters["pick_error_mean_mm"] == pytest.approx(1.0)
    assert counters["pick_error_max_mm"] == pytest.approx(1.5)


# --------------------------------------------------------------------------- #
# matched на объект, появившийся раньше ledger -- untracked_jobs, не caught   #
# --------------------------------------------------------------------------- #


def test_untracked_match():
    """on_match(matched, object_id="obj-99") без предшествующего on_spawn -> untracked_jobs
    1, caught 0 -- §1 контракта."""
    ledger = TruthLedger()
    ledger.on_match(MatchResult(outcome="matched", object_id="obj-99", residual_mm=0.3))

    counters = ledger.counters()
    assert counters["untracked_jobs"] == 1
    assert counters["caught"] == 0


# --------------------------------------------------------------------------- #
# reset() зануляет счётчики, но НЕ трогает объекты под учётом (on_belt)       #
# --------------------------------------------------------------------------- #


def test_reset_keeps_on_belt():
    """reset() при on_belt=1, затем on_despawn того же объекта -> missed 1 -- §1
    контракта: объекты под учётом остаются, их исход после сброса засчитывается
    как обычно."""
    ledger = TruthLedger()
    x = _passport("X")
    ledger.on_spawn(x)
    assert ledger.counters()["on_belt"] == 1

    ledger.reset()
    after_reset = ledger.counters()
    assert after_reset["caught"] == 0
    assert after_reset["missed"] == 0
    assert after_reset["dup_jobs"] == 0
    assert after_reset["false_alarm"] == 0
    assert after_reset["on_belt"] == 1, "reset() не трогает объекты под учётом -- только счётчики"

    ledger.on_despawn("X")
    assert ledger.counters()["missed"] == 1


# --------------------------------------------------------------------------- #
# counters() -- точный набор ключей + свежий словарь на каждый вызов          #
# --------------------------------------------------------------------------- #


def test_counters_keys_and_fresh_dict():
    """Ключи counters() -- ровно набор §1 контракта, ни больше ни меньше; мутация
    возвращённого словаря не должна отражаться на следующем вызове (новый словарь
    каждый раз)."""
    ledger = TruthLedger()
    d1 = ledger.counters()
    assert set(d1.keys()) == _EXPECTED_COUNTER_KEYS

    d1["caught"] = 999
    d2 = ledger.counters()
    assert d2["caught"] != 999, "counters() должен возвращать НОВЫЙ словарь, не одну и ту же ссылку"


# --------------------------------------------------------------------------- #
# on_spawn идемпотентен для одного object_id                                  #
# --------------------------------------------------------------------------- #


def test_idempotent_on_spawn():
    """Повторный on_spawn того же object_id ничего не делает -- §1 контракта: on_belt
    остаётся 1, не 2."""
    ledger = TruthLedger()
    a = _passport("A")
    ledger.on_spawn(a)
    ledger.on_spawn(a)

    assert ledger.counters()["on_belt"] == 1


# --------------------------------------------------------------------------- #
# on_despawn неизвестного/уже пойманного id -- no-op                          #
# --------------------------------------------------------------------------- #


def test_despawn_unknown_or_already_caught_is_noop():
    """on_despawn неизвестного id не бросает и не меняет счётчики; on_despawn уже
    пойманного id (исход решён) -- тоже no-op -- §1 контракта."""
    ledger = TruthLedger()
    ledger.on_despawn("ghost")  # неизвестный id
    assert ledger.counters()["missed"] == 0
    assert ledger.counters()["on_belt"] == 0

    a = _passport("A")
    ledger.on_spawn(a)
    ledger.on_match(MatchResult(outcome="matched", object_id="A", residual_mm=1.0))
    assert ledger.counters()["caught"] == 1

    ledger.on_despawn("A")  # исход уже решён (поймана) -- no-op
    assert ledger.counters()["missed"] == 0
    assert ledger.counters()["caught"] == 1


# --------------------------------------------------------------------------- #
# pick_error_* -- None, пока не было ни одного matched под учётом             #
# --------------------------------------------------------------------------- #


def test_pick_error_none_before_any_match():
    """pick_error_mean_mm/pick_error_max_mm -- None на свежем ledger и после
    событий, среди которых нет ни одного matched -- §1 контракта."""
    ledger = TruthLedger()
    fresh = ledger.counters()
    assert fresh["pick_error_mean_mm"] is None
    assert fresh["pick_error_max_mm"] is None

    ledger.on_match(MatchResult(outcome="dup", object_id="whatever", residual_mm=0.1))
    ledger.on_match(MatchResult(outcome="no_object", object_id=None, residual_mm=None))
    after = ledger.counters()
    assert after["pick_error_mean_mm"] is None
    assert after["pick_error_max_mm"] is None
