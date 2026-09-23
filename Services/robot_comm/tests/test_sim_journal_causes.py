# -*- coding: utf-8 -*-
"""Task 5.1 — ПРИЧИНА повтора задания, не только факт дубля.

Обновлено задачей 5.1b (Контракт лида, ``plans/line-sim/phase-5-contract-5.1b.md``,
§1): категория ``repeats_frozen_xy`` («те же X/Y, но новый энкодер») УШЛА из
``SimJournal`` целиком — на линии с триггером она ложно срабатывала на разных,
честных деталях в одной точке кадра. ``dups`` по-прежнему расщепляется на
``dups_same_capture`` (та же съёмка отправлена дважды) и ``dups_tracked`` (та же
деталь снята на другом кадре) — R1/R2/R4 без изменений контракта. R3 переписан
(было: «те же X/Y → repeats_frozen_xy, НЕ dups»; стало: «те же X/Y → обычное
задание» — задача 5.1b явно требует не удалять тест молча, а переписать под новый
контракт, см. §1 плана «Кто что пишет»).

Литералы взяты из контракта дословно: ``r=5.0`` (дефолт ``dup_radius_mm``), лента
вдоль +Y (``BELT_UX=0.0, BELT_UY=1.0``), ``FACTOR_MM=0.144473`` мм/счёт — все три уже
дефолты/константы ``SimJournal``/``registers.py``, ничего не подобрано под код.

Приём задания — той же последовательностью записей, что реальный Modbus-клиент
(``RobotClient.send_job``): координаты, потом DW-энкодер, маркер ``job_flag``
последним — TRAPS ведущего: тень применяется ДО разбора флага внутри ОДНОГО
``on_write``, порядок записей внутри "транзакции" обязан быть таким же, как в
``Services/robot_comm/tests/test_sim_journal.py::_send_job`` (прочитан, не
изменялся).
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
    """Управляемые часы — тот же приём, что в ``test_sim_journal.py`` (объектная
    зависимость, не глобальный патч времени)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _send_job(journal: SimJournal, x_mm: float, y_mm: float, ecap: int) -> None:
    """Сымитировать транзакцию клиента: координаты, энкодер, маркер последним
    (порядок ``RobotClient.send_job`` — см. ``test_sim_journal.py::_send_job``)."""
    journal.on_write(FC_WRITE_SINGLE, REG_JOB_X, [int(x_mm * XY_SCALE) & 0xFFFF])
    journal.on_write(FC_WRITE_SINGLE, REG_JOB_Y, [int(y_mm * XY_SCALE) & 0xFFFF])
    journal.on_write(FC_WRITE_MULTI, REG_JOB_ECAP, [ecap & 0xFFFF, (ecap >> 16) & 0xFFFF])
    journal.on_write(FC_WRITE_SINGLE, REG_JOB_FLAG, [1])


# --------------------------------------------------------------------------- #
# R1 — та же съёмка отправлена дважды (ecap совпал) -> dups_same_capture       #
# --------------------------------------------------------------------------- #


def test_same_capture_repeat_is_dup_same_capture() -> None:
    """Литерал контракта: (10.0, 20.0, e=1000) дважды -> dups=1, dups_same_capture=1."""
    journal = SimJournal(clock=FakeClock())
    _send_job(journal, x_mm=10.0, y_mm=20.0, ecap=1000)
    _send_job(journal, x_mm=10.0, y_mm=20.0, ecap=1000)

    counters = journal.counters()
    assert counters["jobs"] == 2
    assert counters["dups"] == 1
    assert counters["dups_same_capture"] == 1
    assert counters["dups_tracked"] == 0
    assert "repeats_frozen_xy" not in counters, "5.1b §1: ключ должен был исчезнуть из counters()"
    assert counters["dups"] == counters["dups_same_capture"] + counters["dups_tracked"], (
        "инвариант контракта: dups == dups_same_capture + dups_tracked"
    )


# --------------------------------------------------------------------------- #
# R2 — та же деталь снята на другом кадре (ecap разный, невязка мала) ->      #
#      dups_tracked                                                          #
# --------------------------------------------------------------------------- #


def test_tracked_repeat_is_dup_tracked() -> None:
    """Литерал контракта: вместо второго (10.0, 164.473, e=2000) -> dups=1, dups_tracked=1."""
    journal = SimJournal(clock=FakeClock())
    _send_job(journal, x_mm=10.0, y_mm=20.0, ecap=1000)
    _send_job(journal, x_mm=10.0, y_mm=164.473, ecap=2000)

    counters = journal.counters()
    assert counters["jobs"] == 2
    assert counters["dups"] == 1
    assert counters["dups_same_capture"] == 0
    assert counters["dups_tracked"] == 1
    assert "repeats_frozen_xy" not in counters, "5.1b §1: ключ должен был исчезнуть из counters()"


# --------------------------------------------------------------------------- #
# R3 — те же X/Y, но новый энкодер -> ОБЫЧНОЕ задание (переписано 5.1b, §1:    #
#      на триггере это разные честные детали в одной точке кадра, не повтор)  #
# --------------------------------------------------------------------------- #


def test_same_xy_new_encoder_is_plain_job() -> None:
    """Литерал контракта 5.1b: (10.0, 20.0, e=1000), затем (10.0, 20.0, e=2000) ->
    обычное второе задание — тег "job", не "repeat"; счётчики dups не растут.

    ДО 5.1b здесь стоял литерал «-> repeats_frozen_xy=1, тег "repeat"» — контракт
    отменён (см. докстринг модуля), тест переписан, не удалён."""
    journal = SimJournal(clock=FakeClock())
    _send_job(journal, x_mm=10.0, y_mm=20.0, ecap=1000)
    _send_job(journal, x_mm=10.0, y_mm=20.0, ecap=2000)

    counters = journal.counters()
    assert counters["jobs"] == 2
    assert counters["dups"] == 0
    assert counters["dups_same_capture"] == 0
    assert counters["dups_tracked"] == 0
    assert "repeats_frozen_xy" not in counters, "5.1b §1: ключ должен был исчезнуть из counters()"

    entries = journal.drain()
    tags = [e.tag for e in entries]
    assert "repeat" not in tags, f"тег 'repeat' не должен появляться после 5.1b: {entries!r}"
    job_entries = [e for e in entries if e.tag == "job"]
    assert len(job_entries) == 2, f"оба задания должны быть обычными 'job'-строками: {entries!r}"


# --------------------------------------------------------------------------- #
# R4 — разные детали дают нули; reset обнуляет И старые, И новые ключи        #
# --------------------------------------------------------------------------- #


def test_distinct_jobs_zero_and_reset_clears_new_keys() -> None:
    """Литерал контракта: (10.0, 20.0, e=1000) и (60.0, 20.0, e=1000) -> все нули.

    Плюс отдельная проверка: после накопления обоих новых счётчиков ``reset()``
    обнуляет их наравне со старыми (``jobs/dups/done/reads``) — те же ключи, что уже
    проверяет ``test_sim_journal.py::test_reset_clears_counters_and_duplicate_memory``,
    просто с расширенным набором.

    Переписано 5.1b: четвёртое задание журнала-2 (было — литерал «(10,20,e=3000) ->
    repeats_frozen_xy» под старый контракт) теперь ОБЫЧНОЕ задание — ``_find_origin``
    против A/B/C проездом ленты за Δenc даёт невязку ~289 мм на всех трёх (см. §1
    контракта 5.1b: без частной проверки «X/Y без поправки на проезд» такое задание
    падает в plain job, не в отдельную категорию)."""
    journal = SimJournal(clock=FakeClock())
    _send_job(journal, x_mm=10.0, y_mm=20.0, ecap=1000)
    _send_job(journal, x_mm=60.0, y_mm=20.0, ecap=1000)

    counters = journal.counters()
    assert counters["jobs"] == 2
    assert counters["dups"] == 0
    assert counters["dups_same_capture"] == 0
    assert counters["dups_tracked"] == 0
    assert "repeats_frozen_xy" not in counters, "5.1b §1: ключ должен был исчезнуть из counters()"
    assert counters["done"] == 0
    assert counters["reads"] == 0

    # Второй журнал: по одному разу каждый из старых новых счётчиков, четвёртое —
    # обычное задание (5.1b), затем reset.
    journal2 = SimJournal(clock=FakeClock())
    _send_job(journal2, x_mm=10.0, y_mm=20.0, ecap=1000)  # A
    _send_job(journal2, x_mm=10.0, y_mm=20.0, ecap=1000)  # dups_same_capture (vs A)
    _send_job(journal2, x_mm=10.0, y_mm=164.473, ecap=2000)  # dups_tracked (vs A/dup)
    _send_job(journal2, x_mm=10.0, y_mm=20.0, ecap=3000)  # 5.1b: обычное задание, не repeats_frozen_xy

    pre_reset = journal2.counters()
    assert pre_reset["dups_same_capture"] == 1, pre_reset
    assert pre_reset["dups_tracked"] == 1, pre_reset
    assert pre_reset["jobs"] == 4, pre_reset
    assert pre_reset["dups"] == 2, pre_reset

    journal2.reset()

    assert journal2.counters() == {
        "jobs": 0,
        "dups": 0,
        "done": 0,
        "reads": 0,
        "dups_same_capture": 0,
        "dups_tracked": 0,
    }
