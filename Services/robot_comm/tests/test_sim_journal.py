"""Тесты журнала обмена симулятора — без сети, без pymodbus, без Qt.

Проверяемые свойства (по одному тесту на свойство — так их можно ломать
поштучно инъекцией):
  1. запись с провода подписывается именем и шкалой из карты регистров;
  2. взвод job_flag=1 считается заданием, координаты берутся из ЭТОЙ транзакции;
  3. повтор той же детали (смещение объяснимо проездом ленты) помечается дублем;
  4. другая деталь дублем НЕ помечается;
  5. окно дедупа истекает по часам-зависимости (не по глобальному времени);
  6. чередование A,B,A' — дубль виден при сравнении не только с соседом;
  7. чтения (values=None) строк не создают, но считаются.
"""

from __future__ import annotations

import pytest

from Services.robot_comm.core.registers import (
    FACTOR_MM,
    REG_FREE,
    REG_JOB_ECAP,
    REG_JOB_FLAG,
    REG_JOB_X,
    REG_JOB_Y,
    XY_SCALE,
)
from Services.robot_comm.server.sim_journal import SimJournal

FC_WRITE_SINGLE = 6
FC_WRITE_MULTI = 16
FC_READ = 3


class FakeClock:
    """Управляемые часы: зависимость объекта, а не глобальный патч времени."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _send_job(journal: SimJournal, x_mm: float, y_mm: float, ecap: int) -> None:
    """Сымитировать транзакцию клиента: координаты, энкодер, маркер последним.

    Порядок повторяет ``RobotClient.send_job`` (маркер job_flag пишется в конце).
    """
    journal.on_write(FC_WRITE_SINGLE, REG_JOB_X, [int(x_mm * XY_SCALE) & 0xFFFF])
    journal.on_write(FC_WRITE_SINGLE, REG_JOB_Y, [int(y_mm * XY_SCALE) & 0xFFFF])
    journal.on_write(FC_WRITE_MULTI, REG_JOB_ECAP, [ecap & 0xFFFF, (ecap >> 16) & 0xFFFF])
    journal.on_write(FC_WRITE_SINGLE, REG_JOB_FLAG, [1])


def _texts(journal: SimJournal, tag: str) -> list[str]:
    return [e.text for e in journal.drain() if e.tag == tag]


def test_write_is_labelled_with_name_and_scale() -> None:
    """Свойство 1: сырое слово подписано именем регистра и переведено по шкале."""
    journal = SimJournal(clock=FakeClock())
    journal.on_write(FC_WRITE_SINGLE, REG_JOB_X, [1234])

    lines = [e.text for e in journal.drain() if e.side == "in"]
    assert any("job_x" in line and "123.4" in line for line in lines), lines


def test_negative_coordinate_decoded_as_signed() -> None:
    """Свойство 1 (знак): s16-регистр не должен читаться как 65326."""
    journal = SimJournal(clock=FakeClock())
    journal.on_write(FC_WRITE_SINGLE, REG_JOB_Y, [(-2100) & 0xFFFF])

    lines = [e.text for e in journal.drain() if e.side == "in"]
    assert any("job_y = -210.0" in line for line in lines), lines


def test_job_flag_counts_a_job_with_coordinates_of_this_transaction() -> None:
    """Свойство 2: задание учтено, координаты — из записей ЭТОЙ же транзакции.

    Хук зовётся ДО применения записи, поэтому живые регистры сервера в этот
    момент ещё старые; журнал обязан брать значения из своей тени.
    """
    journal = SimJournal(clock=FakeClock())
    _send_job(journal, x_mm=300.0, y_mm=-210.0, ecap=100_000)

    jobs = _texts(journal, "job")
    assert journal.jobs_seen == 1
    assert len(jobs) == 1
    assert "pick(300.0, -210.0)" in jobs[0]
    assert "e=100000" in jobs[0]


def test_same_part_on_next_frame_is_marked_duplicate() -> None:
    """Свойство 3: смещение, объяснимое проездом ленты, — та же деталь.

    Кадр через 33 мс: лента прошла 1000 счётов ≈ 144.5 мм, деталь снята на
    столько же дальше по +Y. Координаты РАЗНЫЕ — наивная проверка «те же X/Y»
    такой дубль пропустила бы.
    """
    clock = FakeClock()
    journal = SimJournal(clock=clock)
    _send_job(journal, x_mm=300.0, y_mm=-210.0, ecap=100_000)
    clock.advance(0.033)
    travel = 1000 * FACTOR_MM
    _send_job(journal, x_mm=300.0, y_mm=-210.0 + travel, ecap=101_000)

    dups = _texts(journal, "dup")
    assert journal.jobs_seen == 2
    assert journal.dups_seen == 1
    assert len(dups) == 1
    assert "та же деталь, что #1" in dups[0]
    assert "Δenc=+1000" in dups[0]


def test_different_part_is_not_a_duplicate() -> None:
    """Свойство 4: деталь в другом месте ленты дублем не считается."""
    clock = FakeClock()
    journal = SimJournal(clock=clock)
    _send_job(journal, x_mm=300.0, y_mm=-210.0, ecap=100_000)
    clock.advance(0.033)
    # Тот же энкодер-сдвиг, но деталь ушла ещё на 40 мм в сторону — невязка велика.
    _send_job(journal, x_mm=340.0, y_mm=-210.0 + 1000 * FACTOR_MM, ecap=101_000)

    assert journal.jobs_seen == 2
    assert journal.dups_seen == 0
    assert len(_texts(journal, "dup")) == 0


def test_duplicate_window_expires_by_clock() -> None:
    """Свойство 5: за пределами окна те же координаты — уже другая деталь."""
    clock = FakeClock()
    journal = SimJournal(dup_window_s=5.0, clock=clock)
    _send_job(journal, x_mm=300.0, y_mm=-210.0, ecap=100_000)
    clock.advance(5.5)
    _send_job(journal, x_mm=300.0, y_mm=-210.0, ecap=100_000)

    assert journal.jobs_seen == 2
    assert journal.dups_seen == 0


def test_duplicate_found_across_an_interleaved_other_part() -> None:
    """Свойство 6: A, B, A' — дубль виден, хотя сосед A' — это B.

    Сравнение только с предыдущим заданием этот случай пропускает; журнал
    сверяется со всеми заданиями в окне.
    """
    clock = FakeClock()
    journal = SimJournal(clock=clock)
    _send_job(journal, x_mm=300.0, y_mm=-210.0, ecap=100_000)  # A
    clock.advance(0.01)
    _send_job(journal, x_mm=380.0, y_mm=-150.0, ecap=100_000)  # B — другая деталь
    clock.advance(0.02)
    _send_job(journal, x_mm=300.0, y_mm=-210.0 + 1000 * FACTOR_MM, ecap=101_000)  # A'

    dups = _texts(journal, "dup")
    assert journal.dups_seen == 1
    assert "что #1" in dups[0], dups


def test_reads_are_counted_but_not_logged() -> None:
    """Свойство 7: опрос is_free (сотни в секунду) не засоряет колонку."""
    journal = SimJournal(clock=FakeClock())
    for _ in range(50):
        journal.on_write(FC_READ, REG_FREE, None)

    assert journal.counters()["reads"] == 50
    assert journal.drain() == []


def test_events_land_on_the_robot_side_and_count_completions() -> None:
    """События ядра идут в правую колонку; «выполнено» считается отдельно."""
    journal = SimJournal(clock=FakeClock())
    journal.on_event("[CVT]  задание принято: pick(300.0,-210.0) e=100000 -> GL_PLACE")
    journal.on_event("[CVT]  выполнено -> робот свободен")

    entries = journal.drain()
    assert [e.side for e in entries] == ["out", "out"]
    assert journal.counters()["done"] == 1


def test_reset_clears_counters_and_duplicate_memory() -> None:
    """После «Очистить» прежнее задание не должно делать следующее дублем."""
    clock = FakeClock()
    journal = SimJournal(clock=clock)
    _send_job(journal, x_mm=300.0, y_mm=-210.0, ecap=100_000)
    journal.reset()
    _send_job(journal, x_mm=300.0, y_mm=-210.0, ecap=100_000)

    assert journal.counters() == {"jobs": 1, "dups": 0, "done": 0, "reads": 0}


@pytest.mark.parametrize("word_order", ["little", "big"])
def test_encoder_is_decoded_with_the_configured_word_order(word_order: str) -> None:
    """DW-энкодер собирается в том же порядке слов, что у клиента и симулятора."""
    journal = SimJournal(word_order=word_order, clock=FakeClock())
    ecap = 0x0001_86A0  # 100 000
    words = [ecap & 0xFFFF, ecap >> 16] if word_order == "little" else [ecap >> 16, ecap & 0xFFFF]
    journal.on_write(FC_WRITE_MULTI, REG_JOB_ECAP, words)
    journal.on_write(FC_WRITE_SINGLE, REG_JOB_FLAG, [1])

    assert "e=100000" in _texts(journal, "job")[0]
