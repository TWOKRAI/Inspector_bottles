# -*- coding: utf-8 -*-
"""Task 5.2 — тесты лида после break-injection (стадия 3).

Инъекция I4 («максимум невязки = последняя невязка») выжила против обоих наборов: в литерале
контракта максимум 1.5 стоит последним, и «последняя» с ним совпадает. Здесь максимум идёт
первым.
"""

from __future__ import annotations

import pytest

from Services.line_sim.core import MatchResult, TruthLedger
from Services.line_sim.tests.test_acceptance_5_2 import _passport


def test_pick_error_max_is_max_not_last():
    ledger = TruthLedger()
    ledger.on_spawn(_passport("A"))
    ledger.on_spawn(_passport("B"))
    ledger.on_match(MatchResult(outcome="matched", object_id="A", residual_mm=1.5))
    ledger.on_match(MatchResult(outcome="matched", object_id="B", residual_mm=0.5))

    counters = ledger.counters()
    assert counters["pick_error_max_mm"] == pytest.approx(1.5)
    assert counters["pick_error_mean_mm"] == pytest.approx(1.0)
