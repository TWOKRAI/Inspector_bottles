"""Независимая приёмка Task 2.1 (line-sim, фаза 2 «правда ленты»): BeltDrive + контракт
карты mailbox ПЧ.

Пишется ДО реализации (`Services/robot_comm/server/belt.py` пока не существует), из
DESIGN тикета, без чтения будущей реализации — RED по конструкции (worktree на
коммите a0edf74a).

Прочитанные для контекста (только API/единицы, без реализации):
- Services/robot_comm/server/sim_core.py — текущий `tick()`, `_handle_vfd`,
  приватные адреса mailbox ПЧ (0x1200..0x1204, 0x1210).
- Services/robot_comm/core/registers.py — FACTOR_MM = 0.144473 (мм/счёт энкодера).
- Services/vfd_comm/protocols/gd20_bridge.yaml — клиентская карта ПЧ (адреса + scale).
- Services/robot_comm/tests/test_sim_e2e.py — подтверждает, что регистр частоты
  пишется как RAW*100 (0.01 Гц/LSB): `("w", 0x1202, 5000)  # 50.00 Гц`.

ПРЕДПОЛОЖЕНИЯ (не заданы DESIGN явно — если реализация выберет иначе, это повод для
разговора с teamlead, а не молчаливой правки теста):
1. `_handle_vfd` при пульсе VFD_FLAG переводит RAW-регистр частоты (scale=100,
   как в gd20_bridge.yaml) в Гц перед вызовом `belt.command(run, freq_hz, reverse)`
   — т.е. raw=0 всегда означает freq_hz=0.0, независимо от scale.
2. `tick()` продолжает работать без параметра dt; `belt.advance(dt)` вызывается с
   фиксированным шагом, равным `TICK_INTERVAL_S` (0.01 с) из sim_robot.py — сигнатура
   `tick()` не меняется.
3. `BeltDrive.from_enc_rate(enc_rate, tick_s)` восстанавливает СТАРОЕ поведение
   энкодера побитово (без клэмпа/масштаба ПЧ) — проверено литералом 7000 за 1000 тиков.
4. У belt по умолчанию (from_enc_rate) freq_max_hz > 0 — тест на «ПЧ меняет скорость»
   обходит незнание точного значения, командуя freq_hz=0.0 (0 Гц -> 0 мм/с при ЛЮБОМ
   freq_max_hz > 0), а не сравнивая с конкретным числом.
5. Предупреждение при freq_max_hz<=0 идёт через стандартный `logging` (WARNING),
   имя логгера не фиксируется — только уровень.

ЗАПРЕЩЕНО (по брифу): не читать реализацию/тесты разработчика — их ещё нет физически
в этом дереве (worktree на коммите до Task 2.1).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from Services.robot_comm.core.registers import FACTOR_MM
from Services.robot_comm.server.sim_core import RobotSimCore

# ПЧ работает с зафиксированным шагом Motion-цикла — импортируем константу проекта,
# а не дублируем магическое число 0.01 (sim_robot.py импортируется без pymodbus).
from Services.robot_comm.server.sim_robot import TICK_INTERVAL_S

_N_TICKS = 1000  # 1000 * 0.01с = 10с — из REDS брифа


# --------------------------------------------------------------------------------- #
# BeltDrive — прямые тесты объекта (без RobotSimCore)
# --------------------------------------------------------------------------------- #


def test_half_freq_sum_is_3461() -> None:
    """Pre/Post: mm_s = freq_hz/freq_max_hz * mm_s_at_max_freq; счёт = мм / FACTOR_MM."""
    assert FACTOR_MM == 0.144473  # отдельный литерал, как просит бриф

    from Services.robot_comm.server.belt import BeltDrive

    belt = BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0)
    belt.command(run=True, freq_hz=25.0)
    total = sum(belt.advance(0.01) for _ in range(_N_TICKS))
    assert total == pytest.approx(3461, abs=1)


def test_stopped_belt_advances_zero() -> None:
    """Pre/Post: run=False -> скорость 0 независимо от freq_hz."""
    from Services.robot_comm.server.belt import BeltDrive

    belt = BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0)
    belt.command(run=False, freq_hz=25.0)
    total = sum(belt.advance(0.01) for _ in range(_N_TICKS))
    assert total == 0


def test_low_speed_not_floored() -> None:
    """Pre/Post: остаток между вызовами накапливается — низкая скорость НЕ округляется в 0.

    0.5 Гц из 50 Гц -> 1 мм/с; за 10с должно накопиться ~69 счётов, а не 1000
    (что было бы при полной скорости) и не 0 (что было бы при floor() без остатка).
    """
    from Services.robot_comm.server.belt import BeltDrive

    belt = BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0)
    belt.command(run=True, freq_hz=0.5)
    total = sum(belt.advance(0.01) for _ in range(_N_TICKS))
    assert total == pytest.approx(69, abs=1)
    assert total != _N_TICKS  # не эквивалент полной скорости


def test_reverse_is_negative() -> None:
    """Pre/Post: reverse=True -> знак приращения меняется на минус, модуль тот же."""
    from Services.robot_comm.server.belt import BeltDrive

    belt = BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0)
    belt.command(run=True, freq_hz=25.0, reverse=True)
    total = sum(belt.advance(0.01) for _ in range(_N_TICKS))
    assert total == pytest.approx(-3461, abs=1)
    assert total < 0


def test_freq_clamped_to_range() -> None:
    """Pre/Post: freq_hz клэмпится в [0, freq_max_hz] — выше максимума и ниже нуля."""
    from Services.robot_comm.server.belt import BeltDrive

    above = BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0)
    above.command(run=True, freq_hz=999.0)
    total_above = sum(above.advance(0.01) for _ in range(_N_TICKS))
    assert total_above == pytest.approx(6922, abs=1)  # = freq_max_hz: 100 мм/с × 10 с / 0.144473

    below = BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=50.0)
    below.command(run=True, freq_hz=-10.0)
    total_below = sum(below.advance(0.01) for _ in range(_N_TICKS))
    assert total_below == 0  # эквивалент freq_hz=0


def test_zero_freq_max_no_exception(caplog: pytest.LogCaptureFixture) -> None:
    """Edge case: freq_max_hz<=0 -> скорость 0 + warning, БЕЗ исключения (деление на 0)."""
    from Services.robot_comm.server.belt import BeltDrive

    with caplog.at_level(logging.WARNING):
        belt = BeltDrive(mm_s_at_max_freq=100.0, freq_max_hz=0.0)
        belt.command(run=True, freq_hz=25.0)
        total = sum(belt.advance(0.01) for _ in range(10))

    assert total == 0
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


# --------------------------------------------------------------------------------- #
# RobotSimCore — интеграция belt в Motion-цикл
# --------------------------------------------------------------------------------- #


def test_core_default_belt_matches_enc_rate() -> None:
    """Pre/Post: belt=None -> BeltDrive.from_enc_rate(enc_rate, TICK_INTERVAL_S) —
    старое поведение энкодера воспроизводится побитово (регрессия, не новая красная
    ветка: не требует belt.py и уже сегодня зелёный — см. отчёт tester'а).
    """
    core = RobotSimCore(enc_rate=7)
    for _ in range(_N_TICKS):
        core.tick()
    assert core.encoder == 7 * _N_TICKS


def test_vfd_pulse_changes_speed() -> None:
    """Pre/Post: пульс VFD_FLAG применяет команду к belt — скорость по enc_rate
    прекращается, дальше её определяет belt.command() (0 Гц -> 0 счётов/тик,
    вместо enc_rate=7)."""
    core = RobotSimCore(enc_rate=7)
    core.tick()
    baseline = core.encoder
    assert baseline == 7  # sanity: до команды ПЧ энкодер идёт по enc_rate

    # Mailbox ПЧ (см. sim_core.py _REG_VFD_*): RUN, DIR, FREQ(raw*100), затем FLAG-маркер.
    core.write(0x1200, [1])  # cmd_run = 1
    core.write(0x1201, [0])  # cmd_dir = вперёд
    core.write(0x1202, [0])  # cmd_freq raw = 0 -> 0.00 Гц
    core.write(0x1204, [1])  # flag — маркер последним (атомарность mailbox)

    core.tick()
    delta = core.encoder - baseline
    assert delta == 0  # 0 Гц -> 0 мм/с, а НЕ enc_rate=7


def test_core_accepts_injected_belt() -> None:
    """Pre/Post: явно переданный belt используется вместо enc_rate."""
    from Services.robot_comm.server.belt import BeltDrive

    # mm_s_at_max_freq подобран так, чтобы при freq=freq_max_hz счёт/тик был круглым:
    # 144.473 мм/с * 0.01с / FACTOR_MM = 10.0 счётов/тик ровно.
    belt = BeltDrive(mm_s_at_max_freq=144.473, freq_max_hz=50.0)
    belt.command(run=True, freq_hz=50.0)

    core = RobotSimCore(enc_rate=999, belt=belt)
    core.tick()
    assert core.encoder == 10  # из инжектированного belt, а НЕ из enc_rate=999


# --------------------------------------------------------------------------------- #
# Контракт: карта mailbox ПЧ в sim_core не разошлась с gd20_bridge.yaml
# --------------------------------------------------------------------------------- #


def test_vfd_mailbox_addresses_match_bridge_yaml() -> None:
    """Контракт: адреса mailbox ПЧ у sim_core (сторона робота) и у vfd_comm
    (клиентская карта, gd20_bridge.yaml) обязаны побайтово совпадать — они дублируются
    осознанно (см. комментарий sim_core.py:69-70), но раздельно.

    Тест НЕ импортирует BeltDrive и потому не зависит от статуса Task 2.1: сегодня
    он GREEN, потому что адреса уже совпадают (это честно указано в отчёте tester'а,
    а не натянуто под "всё RED"). Красным его делает только реальный дрейф адреса —
    проверено вручную сдвигом на +1 при подготовке теста (см. отчёт).
    """
    yaml_path = Path(__file__).resolve().parents[2] / "vfd_comm" / "protocols" / "gd20_bridge.yaml"
    spec = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    regs = spec["registers"]

    from Services.robot_comm.server import sim_core as sim_core_mod

    assert sim_core_mod._REG_VFD_CMD_RUN == regs["cmd_run"]["address"] == 0x1200
    assert sim_core_mod._REG_VFD_CMD_DIR == regs["cmd_dir"]["address"] == 0x1201
    assert sim_core_mod._REG_VFD_CMD_FREQ == regs["cmd_freq"]["address"] == 0x1202
    assert sim_core_mod._REG_VFD_CMD_RESET == regs["cmd_reset"]["address"] == 0x1203
    assert sim_core_mod._REG_VFD_FLAG == regs["flag"]["address"] == 0x1204
    assert sim_core_mod._REG_VFD_ST_BASE == regs["status"]["address"] == 0x1210
