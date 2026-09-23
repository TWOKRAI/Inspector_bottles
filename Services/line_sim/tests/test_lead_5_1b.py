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


# Ревью 5.1b, п.1: окно по job.t при немонотонном t. Раньше чистилась только голова
# очереди, а `_is_frozen_xy` не сверял Δt.
_MATCHED_UNTRACKED_2 = MatchResult(outcome="matched", object_id="obj-y", residual_mm=0.1)


def test_late_old_job_does_not_revive_expired_entry():
    """R1: опоздавшее задание (t=0 после t=100) застревает за головой очереди; к t=105 оно
    за окном и повтором не считается. Держат его обе половины исправления сразу (чистка всей
    очереди и проверка |Δt|): по одной он зелёный, красный только без обеих."""
    ledger = TruthLedger()
    ledger.on_match(_MATCHED_UNTRACKED, job=JobDone(index=1, x_mm=100.0, y_mm=20.0, ecap=5000, t=100.0))
    ledger.on_match(_MATCHED_UNTRACKED_2, job=JobDone(index=2, x_mm=0.0, y_mm=20.0, ecap=1000, t=0.0))
    ledger.on_match(_NO_OBJECT, job=JobDone(index=3, x_mm=0.0, y_mm=20.0, ecap=6000, t=105.0))

    assert ledger.counters()["false_alarm_frozen_xy"] == 0


def test_future_entry_beyond_window_is_not_compared():
    """R3: запись на 500 с «из будущего» (перезапуск машины робота) дальше окна — не повтор."""
    ledger = TruthLedger()
    ledger.on_match(_MATCHED_UNTRACKED, job=JobDone(index=1, x_mm=0.0, y_mm=20.0, ecap=1000, t=500.0))
    ledger.on_match(_NO_OBJECT, job=JobDone(index=2, x_mm=0.0, y_mm=20.0, ecap=1362, t=0.0))

    assert ledger.counters()["false_alarm_frozen_xy"] == 0


def test_memory_bounded_after_out_of_order_head():
    """R2: запись с t=1e6 в голове не должна запирать очередь. Длина — через приватное поле:
    свойство здесь именно память, наблюдаемого снаружи эффекта у него нет."""
    ledger = TruthLedger()
    ledger.on_match(_MATCHED_UNTRACKED, job=JobDone(index=0, x_mm=0.0, y_mm=-500.0, ecap=1, t=1e6))
    for i in range(1, 2001):
        ledger.on_match(_MATCHED_UNTRACKED, job=JobDone(index=i, x_mm=0.0, y_mm=20.0, ecap=1000 + i, t=i * 1.6))

    # t=1e6 + задания за последние 10 с при шаге 1.6 с (7 шт.)
    assert len(ledger._recent_jobs) <= 8
