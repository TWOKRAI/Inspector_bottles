"""Differential-тест чётности: новый RobotClient ↔ рабочий robot/universal3/pc_full.py.

Самая сильная гарантия совместимости с реальным роботом: прогоняем ОТЛАЖЕННЫЙ
класс ``Robot`` из ``robot/universal3/pc_full.py`` и новый ``RobotClient`` через
один и тот же фейк-робот и сравниваем БАЙТЫ НА ПРОВОДЕ (последовательность
записей в регистры) для каждой логической операции.

Если совпадают — новые сервисы говорят с роботом ровно тем же протоколом, что
проверенный на железе код. Различие в группировке (старый код пишет регистры
по одному, новый — серией ``transaction``) не важно: на проводе это те же
отдельные FC06/FC16 в том же порядке, поэтому сравниваем ПЛОСКИЙ список
операций ``(kind, addr, value)``.

Бонус: «sim fidelity» — рабочий ``Robot`` доводит полный CVT-цикл до конца
против нашего ``sim_core``, что подтверждает: симулятор — верная модель робота.

Пропускается, если ``robot/universal3/pc_full.py`` отсутствует (untracked
reference-код может быть не на всех машинах).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from Services.robot_comm.core.client import RobotClient
from Services.robot_comm.core.config import RobotConfig
from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.testing.fake_transport import FakeRobotTransport

from Services.vfd_comm.core.client import VfdClient

_PC_FULL = Path(__file__).resolve().parents[3] / "robot" / "universal3" / "pc_full.py"
pytestmark = pytest.mark.skipif(not _PC_FULL.exists(), reason="robot/universal3/pc_full.py отсутствует")


# --------------------------------------------------------------------------- #
# Загрузка рабочего эталона по пути (pc_full.py — не пакет)
# --------------------------------------------------------------------------- #


def _load_reference():
    spec = importlib.util.spec_from_file_location("pc_full_ref", _PC_FULL)
    module = importlib.util.module_from_spec(spec)
    sys.modules["pc_full_ref"] = module  # нужно для @dataclass в модуле
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ref():
    """Модуль рабочего эталона robot/universal3/pc_full.py."""
    return _load_reference()


# --------------------------------------------------------------------------- #
# pymodbus-образный записывающий клиент поверх sim_core (драйвит старый Robot)
# --------------------------------------------------------------------------- #


class _Resp:
    """Минимальный ответ pymodbus: .isError() + .registers."""

    def __init__(self, registers: list[int] | None = None) -> None:
        self.registers = registers or []

    def isError(self) -> bool:  # noqa: N802 — имя из pymodbus API
        return False


class RecordingModbusClient:
    """Клиент в форме ModbusTcpClient: пишет в sim_core и ПИШЕТ ЖУРНАЛ записей.

    Старый ``Robot`` зовёт read_holding_registers / write_register /
    write_registers с device_id=… — записываем (kind, addr, value) плоско.
    """

    def __init__(self, core: RobotSimCore) -> None:
        self.core = core
        self.writes: list[tuple] = []

    def read_holding_registers(self, address, count=1, **_kw):
        self.core.tick()
        return _Resp(self.core.read(address, count))

    def write_register(self, address, value, **_kw):
        self.writes.append(("w", address, int(value) & 0xFFFF))
        self.core.write(address, [int(value)])
        return _Resp()

    def write_registers(self, address, values, **_kw):
        vals = [int(v) & 0xFFFF for v in values]
        self.writes.append(("wm", address, vals))
        self.core.write(address, vals)
        return _Resp()

    def connect(self) -> bool:
        return True

    def close(self) -> None:
        pass


def _flat_new(transport: FakeRobotTransport) -> list[tuple]:
    """Плоский список записей нового клиента (из transaction-ops) к виду старого."""
    out: list[tuple] = []
    for ops in transport.transactions:
        for kind, addr, val in ops:
            if kind == "w":
                out.append(("w", addr, int(val) & 0xFFFF))
            else:
                out.append(("wm", addr, [int(v) & 0xFFFF for v in val]))
    return out


@pytest.fixture
def old_bot(ref):
    """Рабочий Robot поверх записывающего клиента (свой sim_core)."""
    client = RecordingModbusClient(RobotSimCore())
    return ref.Robot(client), client


@pytest.fixture
def new_bot():
    """Новый RobotClient поверх FakeRobotTransport (свой sim_core), быстрый clock."""
    transport = FakeRobotTransport(RobotSimCore(draw_ticks=1))
    client = RobotClient(RobotConfig(), transport=transport, sleep=lambda _s: None)
    client.connect()
    return client, transport


# --------------------------------------------------------------------------- #
# Чётность записей: новый клиент == рабочий код на проводе
# --------------------------------------------------------------------------- #


def test_parity_send_job(old_bot, new_bot) -> None:
    old, oc = old_bot
    new, nt = new_bot
    old.send_job(150.5, -200.3, 1234567)
    new.send_job(150.5, -200.3, 1234567)
    assert oc.writes == _flat_new(nt)


def test_parity_set_mode(old_bot, new_bot) -> None:
    old, oc = old_bot
    new, nt = new_bot
    if not hasattr(old, "set_mode"):
        pytest.skip("референс — CVT-only вариант без режимов (REG_MODE/set_mode)")
    old.set_mode(1)
    new.set_mode("draw")
    assert oc.writes == _flat_new(nt)


def test_parity_stop_and_servo(old_bot, new_bot) -> None:
    old, oc = old_bot
    new, nt = new_bot
    old.stop(2)
    old.servo(False)
    new.stop(2)
    new.set_servo(False)
    assert oc.writes == _flat_new(nt)


def test_parity_set_config(old_bot, new_bot) -> None:
    """Read-modify-write всего конфиг-блока + маркер: 11 слов идентичны."""
    old, oc = old_bot
    new, nt = new_bot
    old.set_config(speed=70, home_x=-12.5, pick_z=-3.5, zone_max=300.0)
    new.set_config(speed=70, home_x=-12.5, pick_z=-3.5, zone_max=300.0)
    # отфильтровать read-тики: сравниваем только записи
    assert oc.writes == _flat_new(nt)


def test_parity_set_pen_speed_overlap(old_bot, new_bot) -> None:
    old, oc = old_bot
    new, nt = new_bot
    if not hasattr(old, "set_pen"):
        pytest.skip("референс — CVT-only вариант без рисования")
    old.set_pen(-5.0, 5.0)
    old.set_draw_speed(150)  # клампится в 100 у обоих
    old.set_overlap(2.5)
    new.set_pen(-5.0, 5.0)
    new.set_draw_speed(150)
    new.set_overlap(2.5)
    assert oc.writes == _flat_new(nt)


def test_parity_draw_circle(old_bot, new_bot) -> None:
    old, oc = old_bot
    new, nt = new_bot
    if not hasattr(old, "draw_circle"):
        pytest.skip("референс — CVT-only вариант без рисования")
    old.draw_circle(10.0, 20.0, 5.0)
    new.draw_circle(10.0, 20.0, 5.0)
    assert oc.writes == _flat_new(nt)


def test_parity_draw_polyline_chunks(old_bot, new_bot) -> None:
    """Заливка точек чанками по 30 регистров + запуск прохода — байт в байт."""
    old, oc = old_bot
    new, nt = new_bot
    if not hasattr(old, "draw"):
        pytest.skip("референс — CVT-only вариант без рисования")
    pts = [(float(i), float(-i), 1) for i in range(15)]
    old.draw(pts)
    new.draw(pts)
    assert oc.writes == _flat_new(nt)


def test_parity_vfd_run_stop_setfreq_reset(old_bot, new_bot) -> None:
    """ПЧ: старый Robot.vfd_* vs новый VfdClient — один mailbox, один протокол."""
    old, oc = old_bot
    _new, nt = new_bot
    vfd = VfdClient(nt)  # новый ПЧ-клиент поверх того же транспорта-моста

    old.vfd_run(50.0, reverse=False)
    vfd.run(50.0, reverse=False)
    old.vfd_set_freq(30.0)
    vfd.set_freq(30.0)
    old.vfd_stop()
    vfd.stop()
    old.vfd_reset_fault()
    vfd.reset_fault()
    assert oc.writes == _flat_new(nt)


# --------------------------------------------------------------------------- #
# Sim fidelity: рабочий Robot удовлетворяется нашим симулятором
# --------------------------------------------------------------------------- #


def test_sim_fidelity_full_job_cycle(old_bot, ref) -> None:
    """Рабочий Robot доводит CVT-задание до конца против sim_core (echo сходится)."""
    old, _oc = old_bot
    assert old.is_free() is True
    assert old.send_job(120.0, -40.0, 99) is True
    # робот принимает задание: маркер REG_FLAG сбрасывается в 0 (читаем напрямую)
    accepted = any(old._read(ref.REG_FLAG, 1)[0] == 0 for _ in range(20))
    assert accepted, "робот не принял задание (REG_FLAG не сброшен)"
    assert any(old.is_free() for _ in range(20)), "робот не освободился после задания"
    echo = old.read_echo()
    assert echo["job_x"] == pytest.approx(120.0)
    assert echo["job_y"] == pytest.approx(-40.0)


def test_sim_fidelity_vfd_mirror(old_bot) -> None:
    """Рабочий Robot.read_status видит зеркало ПЧ после команды (через sim-мост)."""
    old, _oc = old_bot
    old.vfd_run(45.0, reverse=False)
    status = old.read_status()
    assert status is not None
    assert status.running is True
    assert status.out_freq_hz == pytest.approx(45.0)
