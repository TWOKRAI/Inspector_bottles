"""Независимые приёмочные тесты окна-вида симулятора v2 (T2.V,
plans/robot-protocol-v2/tasks.md «Окно-вид симулятора»), написанные ДО
реализации — по брифу лида (T2.V), а не по коду.

Пакет ``Services/robot_comm/gui/`` ещё не существует в этом ворктри (дерево
на b3924f85 — T2.K сделан, T2.V нет), поэтому ожидаемый КРАСНЫЙ =
``ImportError`` на ``Services.robot_comm.gui.sim_view``.

ЗАПРЕЩЕНО трогать (не открывать, не grep'ать, не импортировать): любую
реализацию ``sim_view.py`` (её ещё нет), основное дерево репозитория и любой
другой ``.claude/worktrees/*`` — работа только в этом ворктри. Ничего из
перечисленного в ходе работы не открывалось.

Мейлбокс-хелперы (``cmd``/``read_res``/``u16``/``mm``/``s16``/``pose``) —
паттерн, скопированный из ``test_sim_v2_motion.py`` (та же директория, стиль
уже принят в T2.2), а не импорт — этот файл вне FILES того таска.

Один символ угадан вслепую и не выводится из брифа лида: сигнал клика окна
называется ``SimView.clicked`` (``Signal(float, float)``, координаты робота
в мм) — бриф говорит только «click on the view calls driver.goto» и не даёт
имя сигнала/механизма (конструктор ``SimView(core, parent=None)`` не берёт
``driver``, значит проводка клика — сигнал, который демо-``__main__``
соединяет с ``DemoDriver.goto`` снаружи). Тест этого угадывания
(``test_click_maps_to_robot_and_moves``) дополнительно подменяет
``widget_to_robot`` через ``monkeypatch``, чтобы не зависеть от неизвестного
масштаба пиксель->мм — см. докстринг теста.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="окно-вид требует PySide6")

from PySide6.QtCore import QPoint, Qt

from Services.robot_comm.core.params_v2 import PARAM_ID
from Services.robot_comm.core.protocol_v2 import ERR, ERR_TEXT, KIND, OP, REG, REG_COUNT

# модуль ещё не существует -> ImportError (ожидаемый КРАСНЫЙ для всего файла)
from Services.robot_comm.gui.sim_view import DemoDriver, SimView
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

pytestmark = pytest.mark.timeout(30)

ACK = 1
NAK = 2
FW_BUILD = 7

# --------------------------------------------------------------------------- #
# Мейлбокс-хелперы — паттерн из test_sim_v2_motion.py, скопирован (не импорт).
# --------------------------------------------------------------------------- #


def u16(value: int) -> int:
    return value & 0xFFFF


def mm(eng: float) -> int:
    """Инженерное значение (мм или °) -> сырой регистр ×0.1, округление до целого."""
    return round(eng * 10)


def s16(raw: int) -> int:
    """u16 регистра -> знаковое значение (two's complement)."""
    return raw - 65536 if raw >= 0x8000 else raw


def cmd(core: RobotSimCoreV2, seq: int, opcode: int, *args: int, argc: int | None = None) -> dict:
    core.write(REG["CMD_SEQ"], [u16(seq)])
    core.write(REG["CMD_OPCODE"], [opcode])
    n = len(args) if argc is None else argc
    core.write(REG["CMD_ARGC"], [n])
    if args:
        core.write(REG["CMD_ARGS"], [u16(a) for a in args])
    core.write(REG["CMD_FLAG"], [1])  # CMD_FLAG — последним (TRAPS)
    core.tick()
    return read_res(core)


def read_res(core: RobotSimCoreV2) -> dict:
    status = core.read(REG["RES_STATUS"], 1)[0]
    errno = core.read(REG["RES_ERRNO"], 1)[0]
    rvalc = core.read(REG["RES_RVALC"], 1)[0]
    rvals = core.read(REG["RES_RVALS"], REG_COUNT["RES_RVALS"])[:rvalc]
    return {"status": status, "errno": errno, "rvalc": rvalc, "rvals": rvals}


def pose(core: RobotSimCoreV2) -> tuple[int, int, int, int]:
    return (
        s16(core.read(REG["TLM_X"], 1)[0]),
        s16(core.read(REG["TLM_Y"], 1)[0]),
        s16(core.read(REG["TLM_Z"], 1)[0]),
        s16(core.read(REG["TLM_RZ"], 1)[0]),
    )


def fresh_core(**kw) -> RobotSimCoreV2:
    return RobotSimCoreV2(fw_build=FW_BUILD, **kw)


def run_until_idle(core: RobotSimCoreV2, max_ticks: int = 3000) -> None:
    """Тикает, пока активная команда не завершится (TLM_MOVING == 0). Ограничено
    потолком тиков — висящий тест хуже отсутствующего (project-rules)."""
    for _ in range(max_ticks):
        core.tick()
        if core.regs[REG["TLM_MOVING"]] == 0:
            return
    pytest.fail(f"ход не завершился за {max_ticks} тиков")


class DeltaStub:
    """Duck-typed фейковая модель (НЕ RobotModel-подкласс — типизация утиная,
    как требует контракт T2.K) с ТРЕМЯ параллельными цепями, как у дельта-
    робота Клавеля — окно-вид не должно знать про SCARA."""

    kind = "delta_stub"
    axes = ("X", "Y", "Z", "RZ")
    joint_names = ("A", "B", "C")

    def fk(self, joints):
        return (0.0, 0.0, 0.0, 0.0)

    def ik(self, pose, hand):
        return (0.0, 0.0, 0.0)

    def chain_points(self, joints):
        return [
            [(0.0, 0.0, 0.0), (10.0, 10.0, 0.0)],
            [(0.0, 0.0, 0.0), (-10.0, 10.0, 0.0)],
            [(0.0, 0.0, 0.0), (0.0, -10.0, 0.0)],
        ]

    def check_point(self, ws, pose):
        return 0

    def check_segment(self, ws, p0, p1):
        return 0


# --------------------------------------------------------------------------- #
# Тесты
# --------------------------------------------------------------------------- #


def test_view_builds_for_default_sim(qtbot):
    """Свежий core (дефолтная поза = дом SCARA) -> окно строит 1 цепь из 3 точек
    (база/локоть/инструмент) и текстовый статус с литеральными дефолтами дома."""
    core = fresh_core()
    view = SimView(core)
    qtbot.addWidget(view)
    view.refresh()

    chains = view.scene_chains()
    assert len(chains) == 1
    assert len(chains[0]) == 3
    tool_x, tool_y = chains[0][-1]
    assert tool_x == pytest.approx(300.0, abs=0.05)  # P_HOME_X default = 3000 raw / scale 10
    assert tool_y == pytest.approx(-210.0, abs=0.05)  # P_HOME_Y default = -2100 raw / scale 10

    status = view.status_text()
    assert "300" in status
    assert "-210" in status
    assert "-40" in status  # P_HOME_Z default = -400 raw / scale 10
    assert "-100" in status  # P_HOME_RZ default = -1000 raw / scale 10
    assert "серво" in status.lower()


def test_view_follows_pose_after_move(qtbot):
    """DemoDriver.goto ведёт до цели через mailbox; после завершения хода
    последняя точка цепи (TCP) совпадает с целью в пределах 0.1 мм."""
    core = fresh_core()
    driver = DemoDriver(core)
    view = SimView(core)
    qtbot.addWidget(view)

    driver.goto(200.0, 100.0)  # r=223.6 в кольце [100,600], угол 26.6° в [-165,165]
    run_until_idle(core)

    view.refresh()
    chains = view.scene_chains()
    assert len(chains) == 1
    tool_x, tool_y = chains[0][-1]
    assert tool_x == pytest.approx(200.0, abs=0.1)
    assert tool_y == pytest.approx(100.0, abs=0.1)


def test_view_never_writes_registers(qtbot):
    """Окно read-only: несколько refresh()/отрисовок посреди активного хода не
    меняют НИ ОДНОГО регистра core."""
    core = fresh_core()
    driver = DemoDriver(core)
    driver.goto(200.0, 50.0)
    for _ in range(5):
        core.tick()

    view = SimView(core)
    qtbot.addWidget(view)
    view.resize(300, 300)

    before = list(core.regs)
    for _ in range(3):
        view.refresh()
        view.grab()  # форсирует paintEvent синхронно, без show()/event loop
    after = list(core.regs)

    assert after == before


def test_three_chain_fake_model_drawn_without_code_change(qtbot):
    """Утиная модель с тремя цепями (дельта-робот) рисуется без правок кода
    окна — scene_chains() отдаёт ровно 3 записи."""
    core = fresh_core(model=DeltaStub())
    view = SimView(core)
    qtbot.addWidget(view)
    view.refresh()

    chains = view.scene_chains()
    assert len(chains) == 3


def test_unreachable_pose_no_chains_and_warning(qtbot):
    """Воспроизведение из докстринга RobotSimCoreV2.joints() (ревью T2.K,
    находка 1): P_WS_R_MAX раздвинут за пределы модели (700 > 600=l1+l2),
    ход на (650,0,0,0) -> ACK прошивки, но joints() = None (вне модели).
    Окно обязано пережить это без исключения: пустая сцена + слово
    «недостижима» в статусе."""
    core = fresh_core()

    r = cmd(core, 1, OP["PARAM_SET"], PARAM_ID["P_WS_R_MAX"], 7000)  # eng 700.0 мм (scale=10)
    assert r["status"] == ACK, r

    r = cmd(core, 2, OP["PTP_MOVE"], mm(650), mm(0), mm(0), mm(0), KIND["JOINT"], 0)
    assert r["status"] == ACK, r

    run_until_idle(core)
    assert core.joints() is None  # предпосылка теста, не сам SUT

    view = SimView(core)
    qtbot.addWidget(view)
    view.refresh()

    assert view.scene_chains() == []
    assert "недостижима" in view.status_text()


def test_status_text_shows_error_text_after_nak_or_fault(qtbot):
    """inject_motion_fault() -> TLM_ERRNO_LAST = E_MOTION_FAULT; статус окна
    содержит РОВНО текст ERR_TEXT[E_MOTION_FAULT] из protocol_v2 (не своё
    сочинённое сообщение — единый источник текста ошибок)."""
    core = fresh_core()
    core.inject_motion_fault()

    view = SimView(core)
    qtbot.addWidget(view)
    view.refresh()

    assert ERR_TEXT[ERR["E_MOTION_FAULT"]] in view.status_text()


def test_click_maps_to_robot_and_moves(qtbot, monkeypatch):
    """Клик по окну вызывает view.widget_to_robot(point), а результат уходит в
    driver.goto — поза реально доезжает до цели.

    Реальный масштаб пиксель->мм ``widget_to_robot`` бриф не называет
    (`SimView(core, parent=None)` не знает про размер зоны в мм на пиксель) —
    подмена через monkeypatch изолирует именно проводку «клик -> тот же метод
    -> driver.goto», не завязываясь на неизвестные числа масштаба. Угаданный
    сигнал: ``view.clicked`` (см. докстринг модуля).
    """
    core = fresh_core()
    driver = DemoDriver(core)
    view = SimView(core)
    qtbot.addWidget(view)
    view.resize(400, 400)
    view.show()
    qtbot.waitExposed(view)

    target = (300.0, 0.0)  # r=300 в кольце [100,600], угол 0° в [-165,165]
    monkeypatch.setattr(view, "widget_to_robot", lambda point: target)
    view.clicked.connect(driver.goto)

    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
    run_until_idle(core)

    x_raw, y_raw, _z, _rz = pose(core)
    assert x_raw / 10.0 == pytest.approx(target[0], abs=0.1)
    assert y_raw / 10.0 == pytest.approx(target[1], abs=0.1)


def test_driver_stop_aborts_move(qtbot):
    """driver.stop() пишет STOP_REQ HARD -> активный ход обрывается (E_ABORTED),
    поза замирает (не продолжает двигаться дальше того же тика)."""
    core = fresh_core()
    driver = DemoDriver(core)

    driver.goto(200.0, 100.0)
    for _ in range(5):
        core.tick()
    assert core.regs[REG["TLM_MOVING"]] == 1  # предпосылка: ход ещё активен

    pos_before = pose(core)
    driver.stop()
    core.tick()
    pos_after = pose(core)

    assert core.regs[REG["TLM_MOVING"]] == 0
    assert core.regs[REG["TLM_ERRNO_LAST"]] == ERR["E_ABORTED"]
    assert pos_after == pos_before


def test_battle_defaults_home_drawn(qtbot):
    """Дефолтные параметры (без единой ручной правки): домашняя поза рисуется
    (цепь непустая), статус показывает серво включённым (TLM_SERVO=1 при
    боевых дефолтах)."""
    core = fresh_core()
    view = SimView(core)
    qtbot.addWidget(view)
    view.refresh()

    assert core.regs[REG["TLM_SERVO"]] == 1  # предпосылка: боевой дефолт

    chains = view.scene_chains()
    assert len(chains) == 1
    assert len(chains[0]) >= 2

    status = view.status_text()
    assert "серво" in status.lower()
