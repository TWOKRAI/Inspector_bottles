"""Тесты автора (hazard) для Task 2.1 (line-sim, Ф2): `BeltDrive` + интеграция в
`RobotSimCore`.

Дополняют независимую приёмку тестера (`test_belt_acceptance.py`) ловушками
механизма, которые она не покрывает (см. бриф Task 2.1 + ревью, итерация 1):

1. Единственный писатель скорости — `tick()`: `write()` сам по себе не должен
   трогать `belt.command()` — реакция только внутри `tick()` (`_handle_vfd`),
   синхронно, без фонового потока/sleep. Иначе гонка между потоком Modbus-
   сервера (пишет mailbox) и Motion-тикером (`sim_robot.py:_ticker`,
   отдельный поток) была бы реальной, а не только «применяется по пульсу».
2. Дробный остаток копится корректно и на НЕРАВНОМЕРНОМ `dt` — приёмка
   тестера бьёт `advance()` только фиксированным шагом 0.01 с.
3. Ненулевая команда ПЧ через полный путь `RobotSimCore` (не только
   `BeltDrive` напрямую) — приёмка тестера проверяет `_handle_vfd` только на
   freq=0 (что не отличает «команда применилась» от «лента просто встала»),
   это явно названная тестером дыра (см. `test_belt_acceptance.py` шапка).
4. `reverse` через полный путь `RobotSimCore` (ревью, п.1) — до этого файла
   ни один тест не писал `0x1201=1` (cmd_dir), инъекция `reverse=False` в
   `_handle_vfd` оставляла бы всё зелёным.
"""

from __future__ import annotations

import threading
import time

import pytest

from Services.robot_comm import ROBOT_AVAILABLE
from Services.robot_comm.core.registers import FACTOR_MM
from Services.robot_comm.server.belt import BeltDrive
from Services.robot_comm.server.sim_core import RobotSimCore

_N_TICKS = 1000


def test_write_alone_does_not_move_belt() -> None:
    """Pre/Post: единственный писатель скорости — tick(). `write()` сам по себе
    не должен применять команду ПЧ к belt — до вызова tick() энкодер и
    скорость ленты не меняются, даже если VFD_FLAG уже выставлен."""
    core = RobotSimCore(enc_rate=7)
    core.tick()
    baseline = core.encoder

    core.write(0x1200, [1])  # cmd_run = 1
    core.write(0x1201, [0])
    core.write(0x1202, [2500])  # 25.00 Гц (raw*100)
    core.write(0x1204, [1])  # flag — команда «в почтовом ящике», но НЕ применена

    # Прямой вызов write() не должен был сдвинуть энкодер и не должен был
    # тронуть belt — реакция строго внутри tick()/_handle_vfd.
    assert core.encoder == baseline
    # "Сырой" режим from_enc_rate ещё активен (ни одной command() не было),
    # но mm_s УЖЕ сообщает реальную скорость (ревью Task 2.1, п.2): 7*0.144473/0.01
    assert core._belt.mm_s == pytest.approx(101.1311, abs=1e-3)


def test_advance_accumulates_over_uneven_dt() -> None:
    """Pre/Post: остаток копится корректно и при РАЗНОМ dt между вызовами —
    приёмка тестера проверяет только фиксированный шаг 0.01 с."""
    belt = BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0)
    belt.command(run=True, freq_hz=25.0)  # mm_s = 50.0

    dts = [0.02, 0.005, 0.005, 0.03, 0.01] * 200  # сумма за цикл = 0.07с * 200 = 14с
    total_time = sum(dts)
    total = sum(belt.advance(dt) for dt in dts)

    expected = 50.0 * total_time / FACTOR_MM  # 50 мм/с * 14с / FACTOR_MM
    assert total == pytest.approx(expected, abs=1)


def test_nonzero_vfd_command_moves_belt_through_core() -> None:
    """Pre/Post: закрывает дыру тестера — команда ПЧ с НЕНУЛЕВОЙ частотой через
    полный путь RobotSimCore (mailbox -> _handle_vfd -> belt.command ->
    tick() -> encoder), не только прямой BeltDrive.

    25 Гц из 50 (freq_max_hz по умолчанию у BeltDrive) -> 3461±1 отсчёт за
    1000 тиков по 0.01с (тот же литерал, что в приёмке тестера для прямого
    BeltDrive — здесь тот же результат должен получаться и через регистры).
    """
    core = RobotSimCore(enc_rate=7, belt=BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0))
    core.tick()
    baseline = core.encoder

    core.write(0x1200, [1])  # cmd_run = 1
    core.write(0x1201, [0])  # вперёд
    core.write(0x1202, [2500])  # 25.00 Гц (raw*100, scale=100 из gd20_bridge.yaml)
    core.write(0x1204, [1])  # flag — маркер последним

    total = 0
    for _ in range(_N_TICKS):
        before = core.encoder
        core.tick()
        total += core.encoder - before
    assert total == pytest.approx(3461, abs=1)
    assert core.encoder - baseline == total


def test_reverse_vfd_command_moves_belt_negative_through_core() -> None:
    """Pre/Post: закрывает дыру ревью Task 2.1, п.1 — `reverse` через полный путь
    RobotSimCore (не только прямой BeltDrive). Инъекция `reverse=False` в
    `sim_core.py:_handle_vfd` (игнорировать `cmd_dir`) оставляла бы все прежние
    тесты зелёными — ни один из них не писал `0x1201` в 1.

    Та же команда, что в `test_nonzero_vfd_command_moves_belt_through_core`
    (25 Гц), но `cmd_dir=1` (назад) -> тот же по модулю итог, с минусом.
    """
    core = RobotSimCore(enc_rate=7, belt=BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0))
    core.tick()
    baseline = core.encoder

    core.write(0x1200, [1])  # cmd_run = 1
    core.write(0x1201, [1])  # cmd_dir = 1 -> reverse
    core.write(0x1202, [2500])  # 25.00 Гц (raw*100)
    core.write(0x1204, [1])  # flag — маркер последним

    total = 0
    for _ in range(_N_TICKS):
        before = core.encoder
        core.tick()
        total += core.encoder - before
    assert total == pytest.approx(-3461, abs=1)
    assert total < 0
    assert core.encoder - baseline == total


def test_tick_dt_equivalence() -> None:
    """Pre/Post: Task 2.1b — `tick(dt_s)` принимает измеренный dt явным
    параметром; путь по времени не зависит от того, каким шагом его
    накопили. 500 тиков по 0.02с и 1000 тиков по 0.01с (та же команда ПЧ
    25 Гц, что и в `test_nonzero_vfd_command_moves_belt_through_core`) дают
    один и тот же итог — 3461±1, тот же литерал, что при неявном
    `TICK_INTERVAL_S`."""

    def _run(n_ticks: int, dt: float) -> int:
        core = RobotSimCore(enc_rate=7, belt=BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0))
        core.tick()
        baseline = core.encoder

        core.write(0x1200, [1])  # cmd_run = 1
        core.write(0x1201, [0])  # вперёд
        core.write(0x1202, [2500])  # 25.00 Гц (raw*100)
        core.write(0x1204, [1])  # flag — маркер последним

        for _ in range(n_ticks):
            core.tick(dt)
        return core.encoder - baseline

    total_02 = _run(500, 0.02)
    total_01 = _run(1000, 0.01)
    assert total_02 == pytest.approx(3461, abs=1)
    assert total_01 == pytest.approx(3461, abs=1)
    assert total_02 == pytest.approx(total_01, abs=1)


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")
def test_live_ticker_speed_is_wall_clock() -> None:
    """Pre/Post: Task 2.1b — живой `SimRobotServer._ticker` меряет реальный dt
    (`time.perf_counter()`, ревью: точнее `monotonic()` на Windows/Python
    3.12), а не считает такт всегда за `TICK_INTERVAL_S`. Лента 100 мм/с
    (freq_max=50 Гц) с командой ПЧ на полную частоту (50 Гц) за ≥2.0с ПО
    ЧАСАМ должна дать 100 мм/с / FACTOR_MM = 692.2 отсчёта/с (±3% — реальная
    ОС-планировка тикера, не считаем себя точнее). До этой задачи было
    заметно медленнее (реальный период тикера дороже TICK_INTERVAL_S)."""
    from Services.robot_comm.server.sim_robot import SimRobotServer

    core = RobotSimCore(enc_rate=7, belt=BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0))
    core.write(0x1200, [1])  # cmd_run = 1
    core.write(0x1201, [0])  # вперёд
    core.write(0x1202, [5000])  # 50.00 Гц — полная скорость (freq_max=50)
    core.write(0x1204, [1])  # flag — маркер последним

    server = SimRobotServer(core=core)
    ticker = threading.Thread(target=server._ticker, name="test-ticker", daemon=True)
    ticker.start()
    try:
        start_encoder = core.encoder
        t0 = time.monotonic()
        time.sleep(2.0)
        elapsed = time.monotonic() - t0
        counts = core.encoder - start_encoder
    finally:
        server._stop.set()
        ticker.join(timeout=2.0)
        assert not ticker.is_alive(), "тикер не остановился — join завис бы дальше"

    rate = counts / elapsed
    assert rate == pytest.approx(692.2, rel=0.03)


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")
def test_dt_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pre/Post: Task 2.1b — потолок `_MAX_TICK_DT_S=0.1` не даёт паузе
    процесса превратиться в прыжок ленты: `time.perf_counter()` внутри
    ТИКЕРНОГО потока один раз «скачет» на +5с (симуляция паузы планировщика),
    применённый к ядру `dt` должен быть зажат до 0.1с — приращение энкодера
    в ЭТОМ тике <=69.2±1 отсчёта (0.1с * 692.2 отсч/с при 100 мм/с), а не
    ~3461 (5с * 692.2).

    Ревью, итерация 1: подмена ГЛОБАЛЬНОГО `time.perf_counter()` по
    присваиванию ловила и другие потоки (второй `SimRobotServer` в том же
    процессе увидел бы тот же скачок — 5/5 репродукций у ревьюера). Инъекция
    гейтится по `threading.current_thread() is ticker` — триггерит только
    ЭТОТ тикер; после срабатывания смещение НЕИЗМЕННО (часы не идут назад —
    `real_now() + 5.0` монотонно растёт вместе с `real_now()`), а не
    возвращается к «сырому» времени на следующем вызове (что было бы
    скачком часов НАЗАД относительно уже выданного +5с значения)."""
    from Services.robot_comm.server import sim_robot

    core = RobotSimCore(enc_rate=7, belt=BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0))
    core.write(0x1200, [1])  # cmd_run = 1
    core.write(0x1201, [0])  # вперёд
    core.write(0x1202, [5000])  # 50.00 Гц — полная скорость (100 мм/с)
    core.write(0x1204, [1])  # flag — маркер последним

    server = sim_robot.SimRobotServer(core=core)
    ticker = threading.Thread(target=server._ticker, name="test-ticker-ceiling", daemon=True)

    real_perf_counter = sim_robot.time.perf_counter
    real_tick = core.tick
    calls_from_ticker = {"n": 0}
    offset_applied = threading.Event()
    captured: dict[str, float] = {}
    jumped = threading.Event()

    def fake_perf_counter() -> float:
        now = real_perf_counter()
        if not offset_applied.is_set() and threading.current_thread() is ticker:
            calls_from_ticker["n"] += 1
            if calls_from_ticker["n"] >= 2:  # 1-й вызов — baseline `last` до цикла
                offset_applied.set()
        return now + 5.0 if offset_applied.is_set() else now

    def spying_tick(dt: float | None = None) -> None:
        if offset_applied.is_set() and "dt" not in captured:
            before = core.encoder
            real_tick(dt)
            captured["dt"] = dt if dt is not None else -1.0
            captured["moved"] = core.encoder - before
            jumped.set()
        else:
            real_tick(dt)

    monkeypatch.setattr(sim_robot.time, "perf_counter", fake_perf_counter)
    monkeypatch.setattr(core, "tick", spying_tick)

    ticker.start()
    try:
        assert jumped.wait(timeout=2.0), "тикер не применил скачок часов за 2с"
    finally:
        server._stop.set()
        ticker.join(timeout=2.0)
        assert not ticker.is_alive(), "тикер не остановился — join завис бы дальше"

    assert captured["dt"] == pytest.approx(0.1, abs=1e-6)
    assert captured["moved"] == pytest.approx(69.2, abs=1)


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")
def test_live_ticker_default_belt_follows_wall_clock() -> None:
    """Pre/Post: ревью Task 2.1b, п.1 — «сырой» режим (`BeltDrive.from_enc_rate`,
    дефолт `RobotSimCore` без явной команды ПЧ) тоже обязан идти по РЕАЛЬНОМУ
    dt, не только "обычный" режим после `command()`. Ревьюер замерил живой
    тикер с дефолтным belt: 590.8 отсч/с вместо заявленных 7/0.01с=700 —
    `advance()` в сыром режиме был глух к `dt_s` (`return self._raw_rate`
    безусловно), несмотря на то, что `mm_s` уже сообщал верную скорость
    (101.1 мм/с). После фикса (`advance` считает `raw_rate*dt_s/raw_tick_s`
    через тот же remainder) — 700 отсч/с ±3% по часам."""
    from Services.robot_comm.server.sim_robot import SimRobotServer

    core = RobotSimCore(enc_rate=7)  # belt=None -> from_enc_rate(7, TICK_INTERVAL_S), БЕЗ команды ПЧ
    server = SimRobotServer(core=core)
    ticker = threading.Thread(target=server._ticker, name="test-ticker-raw", daemon=True)
    ticker.start()
    try:
        start_encoder = core.encoder
        t0 = time.monotonic()
        time.sleep(2.0)
        elapsed = time.monotonic() - t0
        counts = core.encoder - start_encoder
    finally:
        server._stop.set()
        ticker.join(timeout=2.0)
        assert not ticker.is_alive(), "тикер не остановился — join завис бы дальше"

    rate = counts / elapsed
    assert rate == pytest.approx(700.0, rel=0.03)


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")
def test_live_ticker_no_jump_on_first_vfd_command() -> None:
    """Pre/Post: ревью Task 2.1b, п.1 — докстринг `from_enc_rate` обещает, что
    наблюдатель видит РЕАЛЬНУЮ скорость ленты и до первой команды ПЧ; это
    должно быть верно не только для свойства `mm_s`, но и для фактического
    пройденного пути по часам. Первая живая команда ПЧ (50 Гц — freq_max по
    умолчанию у `from_enc_rate`) с ТОЙ ЖЕ `mm_s_at_max_freq=101.1311`, что
    уже стояла в сыром режиме, не должна дать скачок скорости — разница
    между «до» и «после» < 3% (до фикса раздела #1 разница была ~18.4%:
    сырой режим ехал медленнее реальной скорости, обычный — точно по ней)."""
    from Services.robot_comm.server.belt import BeltDrive as _BeltDrive
    from Services.robot_comm.server.sim_robot import SimRobotServer

    belt = _BeltDrive.from_enc_rate(7, 0.01)
    assert belt.mm_s == pytest.approx(101.1311, abs=1e-3)  # тот же литерал, что в test_write_alone_does_not_move_belt

    core = RobotSimCore(enc_rate=7, belt=belt)
    server = SimRobotServer(core=core)
    ticker = threading.Thread(target=server._ticker, name="test-ticker-nojump", daemon=True)
    ticker.start()
    try:
        before_start = core.encoder
        t0 = time.monotonic()
        time.sleep(1.0)
        before_elapsed = time.monotonic() - t0
        before_counts = core.encoder - before_start

        # Первая живая команда ПЧ (mailbox — см. test_nonzero_vfd_command_moves_belt_through_core):
        # 50 Гц = freq_max по умолчанию у from_enc_rate -> та же mm_s_at_max_freq=101.1311.
        core.write(0x1200, [1])  # cmd_run = 1
        core.write(0x1201, [0])  # вперёд
        core.write(0x1202, [5000])  # 50.00 Гц (raw*100)
        core.write(0x1204, [1])  # flag — маркер последним

        after_start = core.encoder
        t1 = time.monotonic()
        time.sleep(1.0)
        after_elapsed = time.monotonic() - t1
        after_counts = core.encoder - after_start
    finally:
        server._stop.set()
        ticker.join(timeout=2.0)
        assert not ticker.is_alive(), "тикер не остановился — join завис бы дальше"

    rate_before = before_counts / before_elapsed
    rate_after = after_counts / after_elapsed
    assert rate_after == pytest.approx(rate_before, rel=0.03)


def test_belt_mm_s_property_reads_exact_commanded_speed() -> None:
    """Pre/Post: ревью Task 2.2 line-sim — ``RobotSimCore.belt_mm_s`` читает
    ТОЧНУЮ команду ПЧ (``BeltDrive.mm_s``), а не производную энкодера между
    внешними тиками публикации (та даёт смешанное среднее на пульсе смены
    команды — находка ревью №1). 20 Гц из ``freq_max_hz=50`` при
    ``mm_s_at_max_freq=100`` -> (20/50)*100 = 40.0 мм/с; после «стоп»
    (``cmd_run=0``) -> 0.0."""
    core = RobotSimCore(enc_rate=7, belt=BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0))
    core.tick()

    core.write(0x1200, [1])  # cmd_run = 1
    core.write(0x1201, [0])  # вперёд
    core.write(0x1202, [2000])  # 20.00 Гц (raw*100)
    core.write(0x1204, [1])  # flag — маркер последним
    core.tick()
    assert core.belt_mm_s == pytest.approx(40.0)

    core.write(0x1200, [0])  # cmd_run = 0 -> stop
    core.write(0x1204, [1])
    core.tick()
    assert core.belt_mm_s == 0.0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
