# -*- coding: utf-8 -*-
"""RED-приёмка Task 5.1b — причина «те же X/Y, новый энкодер» ПОКИДАЕТ SimJournal.

Независимый tester, worktree на коммите контракта лида (602be8ec, до реализации).
Контракт — ТОЛЬКО ``plans/line-sim/phase-5-contract-5.1b.md`` §1: категория
``repeats_frozen_xy`` уходит из ``SimJournal`` целиком — ``counters()`` больше не
содержит этот ключ, а задание с той же X/Y, но другим ``ecap`` (сегодня ловится
``_find_frozen_xy`` и тегируется ``"repeat"``) становится ОБЫЧНЫМ заданием
(тег ``"job"``, счётчики ``dups``/``dups_same_capture``/``dups_tracked`` не растут).

Сегодня ``repeats_frozen_xy`` — реальный ключ ``counters()`` (см.
``Services/robot_comm/server/sim_journal.py::counters``) и реальная строка-тег
``"repeat"`` (см. ``_register_job``/``_find_frozen_xy``) — ожидаемый провал
``AssertionError`` (ключ присутствует / тег "repeat" найден), не ``KeyError``.

Харнесс — своя копия ``FakeClock``/``_send_job``, тот же приём, что
``Services/robot_comm/tests/test_sim_journal_causes.py`` (прочитан read-only,
только ради порядка полей транзакции — координаты, DW-энкодер, флаг последним;
его СТАРЫЕ асерты на ``repeats_frozen_xy`` не скопированы, они сейчас пинают
контракт, который лид отменяет этой задачей).
"""

from __future__ import annotations

import pytest

from Services.robot_comm.core.registers import (
    REG_JOB_ECAP,
    REG_JOB_FLAG,
    REG_JOB_X,
    REG_JOB_Y,
    XY_SCALE,
)
from Services.robot_comm.server.sim_journal import SimJournal

pytestmark = pytest.mark.timeout(30)

FC_WRITE_SINGLE = 6
FC_WRITE_MULTI = 16


class FakeClock:
    """Управляемые часы — объектная зависимость (не глобальный патч времени)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _send_job(journal: SimJournal, x_mm: float, y_mm: float, ecap: int) -> None:
    """Транзакция клиента: координаты, DW-энкодер, маркер job_flag последним."""
    journal.on_write(FC_WRITE_SINGLE, REG_JOB_X, [int(x_mm * XY_SCALE) & 0xFFFF])
    journal.on_write(FC_WRITE_SINGLE, REG_JOB_Y, [int(y_mm * XY_SCALE) & 0xFFFF])
    journal.on_write(FC_WRITE_MULTI, REG_JOB_ECAP, [ecap & 0xFFFF, (ecap >> 16) & 0xFFFF])
    journal.on_write(FC_WRITE_SINGLE, REG_JOB_FLAG, [1])


def test_same_xy_new_encoder_is_plain_job() -> None:
    """Литерал: (10.0, 20.0, e=1000), затем (10.0, 20.0, e=2000) — §1 контракта 5.1b:
    больше НЕ ``repeats_frozen_xy``/тег "repeat", а обычное второе задание."""
    journal = SimJournal(clock=FakeClock())
    _send_job(journal, x_mm=10.0, y_mm=20.0, ecap=1000)
    _send_job(journal, x_mm=10.0, y_mm=20.0, ecap=2000)

    counters = journal.counters()
    assert "repeats_frozen_xy" not in counters, (
        f"§1 контракта 5.1b: ключ repeats_frozen_xy должен исчезнуть из counters(), нашли: {counters!r}"
    )
    assert counters["jobs"] == 2
    assert counters["dups"] == 0
    assert counters["dups_same_capture"] == 0
    assert counters["dups_tracked"] == 0

    entries = journal.drain()
    tags = [e.tag for e in entries]
    assert "repeat" not in tags, f"тег 'repeat' не должен появляться после 5.1b: {entries!r}"
    job_tags = [e for e in entries if e.tag == "job"]
    assert len(job_tags) == 2, f"оба задания должны быть обычными 'job'-строками: {entries!r}"
