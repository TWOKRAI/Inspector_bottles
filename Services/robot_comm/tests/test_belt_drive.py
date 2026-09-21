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

import pytest

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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
