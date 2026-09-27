"""Дополнительные read-only виды к окну-симулятору протокола v2 (T2.W,
plans/robot-protocol-v2/tasks.md «Окно-вид симулятора v2»).

``ZScale`` — вертикальная шкала Z с границами рабочей зоны и отметками
pick/place/home. ``TimeTape`` — лента Z(t)/RZ(t) за последнее окно времени
(часы зрителя, не ядра — вид должен работать поверх настоящего робота,
где времени ядра нет).

Оба класса — READ-ONLY, тот же паттерн, что и ``SimView`` (T2.V): свой
``QTimer`` перерисовки, останавливаемый в ``closeEvent``. НИ ОДНОГО регистра
не пишут.

Это ОТЛАДОЧНЫЙ вид (владелец, 2026-09-27) — не продуктовый GUI. Продуктовые
виджеты робота строятся в Ф6 на GUI-конструкторе (tasks-2.md T6.x); этот
модуль на тот момент заменяется виджетами конструктора, а не расширяется.
"""

from __future__ import annotations

import time
from collections import deque

from PySide6.QtCore import QPointF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from Services.robot_comm.core.params_v2 import PARAM_ID, to_eng
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.gui.sim_view import _REFRESH_MS, _decode_reg
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

#: отступ сверху/снизу от края виджета до крайних отметок шкалы/ленты, px
#: (contract T2.W: "≥ 8 px, чтобы 3px-линия в z_min/z_max была видна целиком").
_Y_MARGIN_PX = 8.0
#: запасной размах для вырожденного диапазона (lo >= hi из-за плохих параметров).
_FALLBACK_SPAN = 1.0

_TEXT_COLOR = "#c8c8c8"


def _span_or_fallback(lo: float, hi: float) -> tuple[float, float]:
    """(lo, hi) как есть, либо (lo, lo + запас) при вырожденном/перевёрнутом диапазоне.

    ``P_WS_Z_MIN``/``P_WS_Z_MAX`` (и RZ-пара) приходят из параметров ядра и
    ничем не гарантированы от `lo >= hi` (плохой PARAM_SET) — без запасного
    размаха деление на ноль ниже уронило бы отрисовку.
    """
    if hi > lo:
        return lo, hi
    return lo, lo + _FALLBACK_SPAN


def _value_to_y(value: float, lo: float, hi: float, height: float) -> float:
    """Линейная развёртка ``value`` из ``[lo, hi]`` в px по высоте виджета.

    ``hi`` — наверху (``y = margin``), ``lo`` — внизу (``y = margin + usable``).
    Значение за пределами диапазона зажимается на край (не рисуется за
    границей виджета).
    """
    lo, hi = _span_or_fallback(lo, hi)
    usable = max(height - 2 * _Y_MARGIN_PX, 1.0)
    frac = (min(max(value, lo), hi) - lo) / (hi - lo)
    return _Y_MARGIN_PX + (1.0 - frac) * usable


def _value_to_x(t: float, now: float, window_s: float, width: float) -> float:
    """Развёртка времени ``t`` в px по ширине ленты: ``now`` — правый край,
    ``now - window_s`` — левый. За пределами окна — зажим на край."""
    if window_s <= 0:
        return width
    frac = (t - (now - window_s)) / window_s
    return max(0.0, min(1.0, frac)) * width


def _expand_domain(current: tuple[float, float] | None, lo: float, hi: float) -> tuple[float, float]:
    """Домен пиксельной развёртки — РАСШИРЯЕТСЯ по всем виденным (lo, hi), но
    никогда не сужается.

    Если развёртку держать РАВНОЙ текущим (z_min, z_max) (самоссылочно), то
    сама граница z_min всегда попадает в frac=0 (нижний край) по построению —
    ``z_to_widget_y(z_min)`` не может сдвинуться при изменении z_min, это
    тавтология. Контракт T2.W (A4) требует обратного: после ``PARAM_SET
    P_WS_Z_MIN`` пиксель границы должен сместиться. Расширяющийся домен даёт
    и то, и другое: пока зона не выходит за уже виденные пределы — граница
    рисуется как обычная отметка на неподвижном фоне (двигается вместе со
    значением), а расширение зоны раздвигает и сам фон.
    """
    if current is None:
        return (lo, hi)
    return (min(current[0], lo), max(current[1], hi))


class ZScale(QWidget):
    """Read-only вертикальная шкала ``TLM_Z`` поверх ``core``.

    Границы зоны (``P_WS_Z_MIN``/``P_WS_Z_MAX``) и отметки pick/place/home
    перечитываются на каждый ``refresh()`` — параметры меняются в рантайме
    (``PARAM_SET``).
    """

    def __init__(self, core: RobotSimCoreV2, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.core = core
        self._z = 0.0
        self._limits: tuple[float, float] = (0.0, 1.0)
        self._z_domain: tuple[float, float] | None = None
        self._marks: dict[str, float] = {}
        self.setMinimumSize(80, 100)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(_REFRESH_MS)
        self.refresh()

    def refresh(self) -> None:
        """Пересчитать текущий Z, границы зоны и отметки из ``core`` (только чтение)."""
        core = self.core
        self._z = _decode_reg(core.read(REG["TLM_Z"], 1)[0])
        # ponytail: core._workspace() — приватный метод ядра, см. sim_view._paint_transform.
        ws = core._workspace()
        self._limits = (ws.z_min, ws.z_max)
        self._z_domain = _expand_domain(self._z_domain, ws.z_min, ws.z_max)
        # ponytail: core._values — публичного геттера параметра по имени нет,
        # а добавлять его в core вне зоны этого таска (core v2 out of scope).
        self._marks = {
            "pick": to_eng("P_PICK_Z", core._values[PARAM_ID["P_PICK_Z"]]),
            "place": to_eng("P_PLACE_Z", core._values[PARAM_ID["P_PLACE_Z"]]),
            "home": to_eng("P_HOME_Z", core._values[PARAM_ID["P_HOME_Z"]]),
        }
        self.update()

    def z_value(self) -> float:
        """Текущий TLM_Z (мм) на момент последнего ``refresh()``."""
        return self._z

    def z_limits(self) -> tuple[float, float]:
        """(P_WS_Z_MIN, P_WS_Z_MAX) в мм на момент последнего ``refresh()``."""
        return self._limits

    def marks(self) -> dict[str, float]:
        """{"pick", "place", "home"} -> мм на момент последнего ``refresh()`` (копия)."""
        return dict(self._marks)

    def z_to_widget_y(self, z: float) -> float:
        """Z (мм) -> y (px): z_max сверху, z_min снизу, строго убывает по z.

        Развёртка — по ``_z_domain`` (расширяющийся, см. ``_expand_domain``),
        не по мгновенным ``_limits`` — иначе сама граница z_min не могла бы
        сдвинуться при её изменении (contract A4)."""
        lo, hi = self._z_domain if self._z_domain is not None else (0.0, 1.0)
        return _value_to_y(z, lo, hi, max(self.height(), 1))

    def closeEvent(self, event) -> None:  # noqa: N802 (переопределение Qt)
        """Остановить таймер перерисовки при закрытии (как у SimView)."""
        self._timer.stop()
        super().closeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (переопределение Qt)
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor("#1b1b1b"))
            # Порядок: границы -> отметки -> текущий Z (текущий рисуется поверх).
            for z in self._limits:
                self._paint_row(painter, z, "#ff5c57")
            for name, z in self._marks.items():
                self._paint_row(painter, z, "#8be9fd", label=name)
            self._paint_row(painter, self._z, "#5af78e", label="Z")
        finally:
            painter.end()

    def _paint_row(self, painter: QPainter, z: float, color: str, label: str | None = None) -> None:
        y = self.z_to_widget_y(z)
        pen = QPen(QColor(color))
        pen.setWidth(3)
        painter.setPen(pen)
        painter.drawLine(QPointF(0, y), QPointF(self.width(), y))
        if label:
            painter.setPen(QPen(QColor(_TEXT_COLOR)))
            painter.drawText(QPointF(12, y - 4), f"{label} {z:.1f}")


class TimeTape(QWidget):
    """Read-only лента Z(t)/RZ(t) за последние ``window_s`` секунд поверх ``core``.

    Часы — параметр ``clock`` (по умолчанию ``time.monotonic``), не время
    ядра: вид читает только регистры и должен работать поверх настоящего
    робота (T3/T5), где времени ядра нет. В тестах ``clock`` подменяется.
    """

    def __init__(
        self,
        core: RobotSimCoreV2,
        clock=time.monotonic,
        window_s: float = 10.0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.core = core
        self.clock = clock
        self.window_s = window_s
        self._samples: deque[tuple[float, float, float]] = deque()
        self._z_limits: tuple[float, float] = (0.0, 1.0)
        self._rz_limits: tuple[float, float] = (0.0, 1.0)
        self.setMinimumSize(200, 80)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(_REFRESH_MS)
        self.refresh()

    def refresh(self) -> None:
        """Добавить одну выборку (clock(), Z, RZ), отбросить старше окна, перерисовать."""
        core = self.core
        t = self.clock()
        z = _decode_reg(core.read(REG["TLM_Z"], 1)[0])
        rz = _decode_reg(core.read(REG["TLM_RZ"], 1)[0])
        self._samples.append((t, z, rz))
        cutoff = t - self.window_s
        # Часы, идущие назад (TRAPS, hazard-тест), просто не подрезают ленту
        # в этом тике — не исключение, накопление лишнего хвоста не опаснее.
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        # ponytail: core._workspace() — см. ZScale.refresh().
        ws = core._workspace()
        self._z_limits = (ws.z_min, ws.z_max)
        self._rz_limits = (ws.rz_min, ws.rz_max)
        self.update()

    def samples(self) -> list[tuple[float, float, float]]:
        """Выборки (t, Z, RZ) по возрастанию времени добавления — копия внутреннего буфера."""
        return list(self._samples)

    def closeEvent(self, event) -> None:  # noqa: N802 (переопределение Qt)
        """Остановить таймер перерисовки при закрытии (как у SimView)."""
        self._timer.stop()
        super().closeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (переопределение Qt)
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor("#1b1b1b"))
            self._paint_curve(painter, key=1, color="#5af78e", limits=self._z_limits)
            self._paint_curve(painter, key=2, color="#ffb86c", limits=self._rz_limits)
        finally:
            painter.end()

    def _paint_curve(self, painter: QPainter, key: int, color: str, limits: tuple[float, float]) -> None:
        samples = list(self._samples)
        if len(samples) < 2:
            return
        now = self.clock()
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        lo, hi = limits
        points = [QPointF(_value_to_x(s[0], now, self.window_s, w), _value_to_y(s[key], lo, hi, h)) for s in samples]
        pen = QPen(QColor(color))
        pen.setWidth(2)
        painter.setPen(pen)
        for a, b in zip(points, points[1:]):
            painter.drawLine(a, b)
