# -*- coding: utf-8 -*-
"""Task 5.1b — тесты лида после break-injection (стадия 3).

J4 («reset не забывает недавние задания») выжила: в тестерском `test_reset_forgets_recent_jobs`
задание после сброса приходит через 100 с, и окно 10 с выбросило бы старое и без сброса.
J2 («без проверки другого ecap») выжила: `no_object` с тем же ecap и теми же X/Y не слал никто.
"""

from __future__ import annotations

from Services.line_sim.core import JobDone, MatchResult, TruthLedger

_NO_OBJECT = MatchResult(outcome="no_object", object_id=None, residual_mm=None)
_MATCHED_UNTRACKED = MatchResult(outcome="matched", object_id="obj-x", residual_mm=0.1)


def test_reset_forgets_recent_jobs_inside_window():
    ledger = TruthLedger()
    ledger.on_match(_MATCHED_UNTRACKED, job=JobDone(index=1, x_mm=0.0, y_mm=20.0, ecap=1000, t=0.0))
    ledger.reset()
    ledger.on_match(_NO_OBJECT, job=JobDone(index=2, x_mm=0.0, y_mm=20.0, ecap=1362, t=0.5))  # в окне

    counters = ledger.counters()
    assert counters["false_alarm"] == 1
    assert counters["false_alarm_frozen_xy"] == 0


def test_same_ecap_same_xy_is_not_frozen():
    """Та же съёмка отправлена ещё раз — это дубль команды (журнал 5.1, `dups_same_capture`),
    а не «те же X/Y с новым энкодером»."""
    ledger = TruthLedger()
    ledger.on_match(_NO_OBJECT, job=JobDone(index=1, x_mm=0.0, y_mm=20.0, ecap=1000, t=0.0))
    ledger.on_match(_NO_OBJECT, job=JobDone(index=2, x_mm=0.0, y_mm=20.0, ecap=1000, t=0.5))

    counters = ledger.counters()
    assert counters["false_alarm"] == 2
    assert counters["false_alarm_frozen_xy"] == 0
