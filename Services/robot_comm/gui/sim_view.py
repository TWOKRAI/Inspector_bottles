"""Окно-вид симулятора протокола v2 (T2.V, plans/robot-protocol-v2/tasks.md).

Два класса, строго разделённые по правам на запись:

- ``SimView`` — READ-ONLY виджет: рисует зону, цепи звеньев модели (``core.model``,
  через ``core.joints()``), шлейф TCP и текстовый статус. НИ ОДНОГО регистра не
  пишет — сам не решает, что должно двигаться, только показывает текущее
  состояние ``core`` и эмитит ``clicked`` по клику мышью.
- ``DemoDriver`` — единственный писатель. Водит ``core`` через mailbox точно тем
  же паттерном, что и тестовые хелперы (``CMD_SEQ``/``CMD_OPCODE``/``CMD_ARGC``/
  ``CMD_ARGS``, ``CMD_FLAG=1`` последним), и плоскость ``STOP_REQ`` — напрямую
  (это не mailbox-команда, а отдельный регистр прошивки).

Окно НЕ знает про SCARA — цепи приходят из ``core.model.chain_points()``,
любая duck-typed модель (см. ``RobotModel`` в ``kinematics.py``) рисуется без
правок этого файла.

Запуск::

    python -m Services.robot_comm.gui.sim_view
"""

from __future__ import annotations

import math
import sys
import time
from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from Services.robot_comm.core.protocol_v2 import ERR_TEXT, KIND, OP, REG, STOP_LEVEL
from Services.robot_comm.server.sim_core_v2 import (
    RobotSimCoreV2,
    TLM_ACTIVITY_FAULT,
    TLM_ACTIVITY_IDLE,
    TLM_ACTIVITY_JOG,
    TLM_ACTIVITY_PTP,
)

#: период таймера перерисовки, мс (contract T2.V: "~33 мс").
_REFRESH_MS = 33
#: длина шлейфа TCP, точек.
_TRAIL_LEN = 200
#: отступ от края виджета до кольца зоны, px.
_MARGIN_PX = 20.0
#: запас масштаба вокруг r_max, чтобы кольцо не касалось края виджета.
_ZONE_MARGIN = 1.1

_ACTIVITY_NAMES = {
    TLM_ACTIVITY_IDLE: "IDLE",
    TLM_ACTIVITY_PTP: "PTP",
    TLM_ACTIVITY_JOG: "JOG",
    TLM_ACTIVITY_FAULT: "FAULT",
}


def _decode_reg(raw: int) -> float:
    """u16-регистр позы (×10, two's complement) -> инженерное значение (мм/°)."""
    signed = raw - 65536 if raw >= 0x8000 else raw
    return signed / 10.0


def _encode_mm(eng: float) -> int:
    """Инженерное значение (мм/°) -> сырой аргумент команды ×10, округление до целого."""
    return round(eng * 10)


class SimView(QWidget):
    """Read-only вид сверху над ``core``. Ничего не пишет в регистры.

    ``clicked(x, y)`` — клик левой кнопкой мыши, координаты уже переведены в
    мм робота (``widget_to_robot``). Кого соединять с сигналом — решает
    вызывающий (обычно ``DemoDriver.goto``), сам виджет драйвер не знает.
    """

    clicked = Signal(float, float)

    def __init__(self, core: RobotSimCoreV2, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.core = core
        self._chains: list[list[tuple[float, float]]] = []
        self._status = ""
        self._trail: deque[tuple[float, float]] = deque(maxlen=_TRAIL_LEN)
        self.setMinimumSize(200, 200)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(_REFRESH_MS)
        self.refresh()

    # ------------------------------------------------------------------ #
    # Пересчёт состояния (только чтение core)
    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        """Пересчитать цепи/статус/шлейф из ``core`` и запросить перерисовку."""
        self._chains = self._compute_chains()
        self._status = self._compute_status()
        self._trail.append(self._tool_xy())
        self.update()

    def scene_chains(self) -> list[list[tuple[float, float]]]:
        """XY-точки цепей модели на момент последнего ``refresh()`` (кэш)."""
        return self._chains

    def status_text(self) -> str:
        """Текстовый статус на момент последнего ``refresh()`` (кэш)."""
        return self._status

    def _tool_xy(self) -> tuple[float, float]:
        x = _decode_reg(self.core.read(REG["TLM_X"], 1)[0])
        y = _decode_reg(self.core.read(REG["TLM_Y"], 1)[0])
        return (x, y)

    def _compute_chains(self) -> list[list[tuple[float, float]]]:
        joints = self.core.joints()
        if joints is None:
            return []
        return [[(p[0], p[1]) for p in chain] for chain in self.core.model.chain_points(joints)]

    def _compute_status(self) -> str:
        core = self.core
        x, y = self._tool_xy()
        z = _decode_reg(core.read(REG["TLM_Z"], 1)[0])
        rz = _decode_reg(core.read(REG["TLM_RZ"], 1)[0])
        hand = "правая" if core.read(REG["TLM_HAND"], 1)[0] == 0 else "левая"
        activity = _ACTIVITY_NAMES.get(core.read(REG["TLM_ACTIVITY"], 1)[0], "?")
        servo = "вкл" if core.read(REG["TLM_SERVO"], 1)[0] else "выкл"
        errno = core.read(REG["TLM_ERRNO_LAST"], 1)[0]

        lines = [
            f"X={x:.1f}  Y={y:.1f}  Z={z:.1f}  RZ={rz:.1f}",
            f"рука: {hand}   активность: {activity}   серво: {servo}",
        ]
        if errno:
            lines.append(f"ошибка: {ERR_TEXT.get(errno, '?')}")
        if core.joints() is None:
            lines.append("поза недостижима для модели")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Пиксели <-> мм робота (+X вправо, +Y вверх)
    # ------------------------------------------------------------------ #

    def _paint_transform(self) -> tuple[float, float, float]:
        """Центр виджета (px) + масштаб (px/мм), подогнанный под текущий r_max.

        Зона читается заново на каждый вызов (TRAPS: ``PARAM_SET P_WS_R_MAX``
        меняет зону в рантайме — кэш на ``__init__`` показывал бы старую).
        """
        # ponytail: core._workspace() — приватный метод ядра; публичного геттера
        # зоны нет, а копировать сборку Workspace сюда завела бы вторую правду о
        # параметрах зоны. Тот же пакет-семья (Services/robot_comm), приемлемо.
        ws = self.core._workspace()
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        half = max(min(w, h) / 2.0 - _MARGIN_PX, 1.0)
        r_max = max(ws.r_max, 1.0)
        scale = half / (r_max * _ZONE_MARGIN)
        return w / 2.0, h / 2.0, scale

    def widget_to_robot(self, point: QPointF) -> tuple[float, float]:
        """Точка виджета (px) -> координаты робота (мм). Точная обратная ``_to_widget``."""
        cx, cy, scale = self._paint_transform()
        return ((point.x() - cx) / scale, (cy - point.y()) / scale)

    def _to_widget(self, x: float, y: float) -> QPointF:
        cx, cy, scale = self._paint_transform()
        return QPointF(cx + x * scale, cy - y * scale)

    # ------------------------------------------------------------------ #
    # Ввод
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event) -> None:  # noqa: N802 (переопределение Qt)
        if event.button() == Qt.MouseButton.LeftButton:
            x, y = self.widget_to_robot(event.position())
            self.clicked.emit(x, y)
        super().mousePressEvent(event)

    # ------------------------------------------------------------------ #
    # Отрисовка
    # ------------------------------------------------------------------ #

    def paintEvent(self, event) -> None:  # noqa: N802 (переопределение Qt)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillRect(self.rect(), QColor("#1b1b1b"))
            self._paint_zone(painter)
            self._paint_trail(painter)
            self._paint_chains(painter)
            self._paint_target(painter)
            self._paint_status(painter)
        finally:
            painter.end()

    def _paint_zone(self, painter: QPainter) -> None:
        ws = self.core._workspace()  # ponytail: см. _paint_transform
        pen = QPen(QColor("#3a3a3a"))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for r in (ws.r_min, ws.r_max):
            if r <= 0:
                continue
            top_left = self._to_widget(-r, r)
            bottom_right = self._to_widget(r, -r)
            painter.drawEllipse(QRectF(top_left, bottom_right))
        for angle in (ws.ang_min, ws.ang_max):
            rad = math.radians(angle)
            end = self._to_widget(ws.r_max * math.cos(rad), ws.r_max * math.sin(rad))
            painter.drawLine(self._to_widget(0.0, 0.0), end)
        if ws.box_en:
            pen.setColor(QColor("#5a5a2a"))
            painter.setPen(pen)
            top_left = self._to_widget(ws.x_min, ws.y_max)
            bottom_right = self._to_widget(ws.x_max, ws.y_min)
            painter.drawRect(QRectF(top_left, bottom_right))

    def _paint_trail(self, painter: QPainter) -> None:
        n = len(self._trail)
        if n < 2:
            return
        for i in range(1, n):
            alpha = int(200 * i / n)
            pen = QPen(QColor(90, 200, 255, alpha))
            pen.setWidth(2)
            painter.setPen(pen)
            p0 = self._to_widget(*self._trail[i - 1])
            p1 = self._to_widget(*self._trail[i])
            painter.drawLine(p0, p1)

    def _paint_chains(self, painter: QPainter) -> None:
        pen = QPen(QColor("#5af78e"))
        pen.setWidth(3)
        painter.setPen(pen)
        painter.setBrush(QColor("#5af78e"))
        for chain in self._chains:
            points = [self._to_widget(x, y) for x, y in chain]
            for a, b in zip(points, points[1:]):
                painter.drawLine(a, b)
            for p in points:
                painter.drawEllipse(p, 4, 4)

    def _paint_target(self, painter: QPainter) -> None:
        active = self.core._active  # ponytail: см. _paint_transform
        if not active or "target" not in active:
            return
        x, y, _z, _rz = active["target"]
        p = self._to_widget(x, y)
        pen = QPen(QColor("#ff5c57"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawLine(QPointF(p.x() - 6, p.y()), QPointF(p.x() + 6, p.y()))
        painter.drawLine(QPointF(p.x(), p.y() - 6), QPointF(p.x(), p.y() + 6))

    def _paint_status(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#c8c8c8")))
        painter.drawText(QRectF(8, 8, self.width() - 16, 80), Qt.TextFlag.TextWordWrap, self._status)


class DemoDriver:
    """Единственный писатель в регистры ``core`` — демо-водитель для интерактивного окна.

    Пишет mailbox точно как хелперы тестов (``CMD_SEQ``/``CMD_OPCODE``/
    ``CMD_ARGC``/``CMD_ARGS``, ``CMD_FLAG=1`` последним) и плоскость
    ``STOP_REQ`` — напрямую (не mailbox-команда). Сам ``core`` не тикает —
    тиканье ведёт таймер ``main()``.
    """

    def __init__(self, core: RobotSimCoreV2) -> None:
        self.core = core
        # seq стартует от ТЕКУЩЕГО RES_SEQ, не с нуля — иначе первая же команда
        # со seq==RES_SEQ была бы принята ядром за повтор и не исполнилась
        # (TRAPS: core может быть создан с уже непустым RES_SEQ в regs).
        self._seq = core.read(REG["RES_SEQ"], 1)[0]
        self._stop_seq = 0

    def goto(self, x: float, y: float) -> None:
        """PTP_MOVE KIND JOINT в (x, y); Z/RZ — текущие, скорость по умолчанию (spd=0)."""
        core = self.core
        z = _decode_reg(core.read(REG["TLM_Z"], 1)[0])
        rz = _decode_reg(core.read(REG["TLM_RZ"], 1)[0])
        self._send(OP["PTP_MOVE"], _encode_mm(x), _encode_mm(y), _encode_mm(z), _encode_mm(rz), KIND["JOINT"], 0)

    def home(self) -> None:
        """HOME со скоростью по умолчанию (spd_pct=0)."""
        self._send(OP["HOME"], 0)

    def servo(self, on: bool) -> None:
        """SERVO вкл/выкл."""
        self._send(OP["SERVO"], 1 if on else 0)

    def stop(self) -> None:
        """STOP_REQ уровня HARD — значение каждый раз новое.

        Плоскость стопа (contract §"Stop plane") реагирует только на ИЗМЕНЕНИЕ
        регистра: повтор того же значения не оборвал бы ход. Счётчик
        монотонно растёт (шаг 4, чтобы не задеть младшие 2 бита — уровень) и
        сверяется с уже лежащим в регистре значением на случай коллизии.
        """
        core = self.core
        current = core.read(REG["STOP_REQ"], 1)[0]
        self._stop_seq += 1
        value = (self._stop_seq * 4 + STOP_LEVEL["HARD"]) & 0xFFFF
        while value == current:
            self._stop_seq += 1
            value = (self._stop_seq * 4 + STOP_LEVEL["HARD"]) & 0xFFFF
        core.write(REG["STOP_REQ"], [value])

    def _send(self, opcode: int, *args: int) -> None:
        core = self.core
        self._seq = (self._seq + 1) & 0xFFFF
        core.write(REG["CMD_SEQ"], [self._seq])
        core.write(REG["CMD_OPCODE"], [opcode])
        core.write(REG["CMD_ARGC"], [len(args)])
        if args:
            core.write(REG["CMD_ARGS"], list(args))
        core.write(REG["CMD_FLAG"], [1])  # последним (TRAPS, тот же порядок что и у mailbox-хелперов тестов)


def main() -> None:
    """Запуск демо-окна: ``python -m Services.robot_comm.gui.sim_view``."""
    app = QApplication(sys.argv)
    core = RobotSimCoreV2()
    driver = DemoDriver(core)
    view = SimView(core)
    view.clicked.connect(driver.goto)

    window = QWidget()
    window.setWindowTitle("Симулятор робота v2 — вид сверху")

    btn_home = QPushButton("Домой")
    btn_home.clicked.connect(driver.home)

    servo_state = {"on": True}

    def _toggle_servo() -> None:
        servo_state["on"] = not servo_state["on"]
        driver.servo(servo_state["on"])

    btn_servo = QPushButton("Серво")
    btn_servo.clicked.connect(_toggle_servo)

    btn_stop = QPushButton("Стоп")
    btn_stop.clicked.connect(driver.stop)

    toolbar = QHBoxLayout()
    toolbar.addWidget(btn_home)
    toolbar.addWidget(btn_servo)
    toolbar.addWidget(btn_stop)
    toolbar.addStretch(1)

    layout = QVBoxLayout(window)
    layout.addLayout(toolbar)
    layout.addWidget(view)
    window.resize(700, 700)

    last = time.monotonic()

    def _tick() -> None:
        nonlocal last
        now = time.monotonic()
        dt = min(now - last, 0.1)
        last = now
        core.tick(dt)

    sim_timer = QTimer()
    sim_timer.timeout.connect(_tick)
    sim_timer.start(10)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
