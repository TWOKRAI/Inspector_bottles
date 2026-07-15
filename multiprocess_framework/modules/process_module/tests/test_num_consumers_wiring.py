# -*- coding: utf-8 -*-
"""Ф7 G.7 — проводка num_consumers loan-протокола из топологии (chain_targets).

``_count_loan_aware_consumers`` = число потребителей кадра, реально шлющих release
(loan-aware). copy-out терминалы (GUI/дисплеи — кадр копируют, release не шлют)
исключаются. Владелец с 0 loan-aware (fan-out только в GUI) → пул не создаётся
(round-robin В1), исчерпания free-list нет (резидуал G.5 закрыт).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.generic.generic_process import (
    _COPY_OUT_TARGETS,
    _count_loan_aware_consumers,
)


def test_gui_is_copy_out_terminal():
    assert "gui" in _COPY_OUT_TARGETS


def test_single_real_target():
    assert _count_loan_aware_consumers(["seg"]) == 1


def test_excludes_gui_from_fanout():
    # seg → [lines, gui]: только lines шлёт release.
    assert _count_loan_aware_consumers(["lines", "gui"]) == 1


def test_gui_only_target_is_zero():
    # points → [gui]: 0 loan-aware (GUI копирует, release не шлёт).
    assert _count_loan_aware_consumers(["gui"]) == 0


def test_empty_targets_is_zero():
    assert _count_loan_aware_consumers([]) == 0
    assert _count_loan_aware_consumers(None) == 0


def test_multiple_real_targets():
    assert _count_loan_aware_consumers(["a", "b", "gui"]) == 2
    assert _count_loan_aware_consumers(["a", "b", "c"]) == 3


def test_copy_out_override_from_config():
    """Ф7 ревью фазы G: рецепт/конфиг перекрывает дефолт {"gui"} — мульти-дисплей
    (display_0/display_1) объявляет своих copy-out читателей сам, иначе они считались
    бы loan-aware → release не пришёл бы → free-list исчерпание."""
    targets = ["seg", "display_0", "display_1"]
    # Без перекрытия display_* считаются loan-aware (дефолт знает только "gui").
    assert _count_loan_aware_consumers(targets) == 3
    # С перекрытием — только seg шлёт release.
    assert _count_loan_aware_consumers(targets, ["display_0", "display_1"]) == 1
    # Явный пустой список = все цели loan-aware (даже gui).
    assert _count_loan_aware_consumers(["gui"], []) == 1


def test_duplicate_targets_deduplicated():
    """Дубль-target не завышает refcount: release от него придёт ОДИН раз (dedup по
    reader в пуле), завышенный refcount застрял бы навсегда."""
    assert _count_loan_aware_consumers(["seg", "seg", "gui"]) == 1
