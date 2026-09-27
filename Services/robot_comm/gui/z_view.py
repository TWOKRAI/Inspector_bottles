"""Дополнительные read-only виды к окну-симулятору протокола v2 (T2.W,
plans/robot-protocol-v2/tasks.md «Окно-вид симулятора v2»).

``ZScale`` — вертикальная шкала Z с границами рабочей зоны и отметками
pick/place/home. ``TimeTape`` — лента Z(t)/RZ(t) за последнее окно времени
(часы зрителя, не ядра — вид должен работать поверх настоящего робота,
где времени ядра нет).

Оба класса — READ-ONLY, тот же паттерн, что и ``SimView`` (T2.V): свой
``QTimer`` перерисовки, останавливаемый в ``closeEvent``/``hideEvent`` и
возобновляемый в ``showEvent`` (F4, ревью T2.W — Qt доставляет ``closeEvent``
только окну верхнего уровня, встроенный виджет продолжал бы тикать после
``window.close()``). НИ ОДНОГО регистра не пишут — оба читают ТОЛЬКО регистры
телеметрии (``TLM_*``) и зеркало параметров (``PMIR``, F5, ревью T2.W): у
ядра нет публичного геттера параметра по имени и зоны, но зеркало — тот же
контракт read-only, что и телеметрия, и не требует приватного доступа к
``core._workspace()``/``core._values``. ``SimView`` (T2.V, вне зоны этого
таска) по-прежнему читает зону и суставы через ``core._workspace()``/
``core.joints()`` — эти два виджета в это решение не входят.

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

from Services.robot_comm.core.params_v2 import PARAM_ID, PARAMS, to_eng
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.gui._common import _REFRESH_MS, _decode_reg
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

#: отступ сверху/снизу от края виджета до крайних отметок шкалы/ленты, px
#: (contract T2.W: "≥ 8 px, чтобы 3px-линия в z_min/z_max была видна целиком").
_Y_MARGIN_PX = 8.0
#: запасной размах домена, если фактический размах меньше 1 мм/град (F1,
#: ревью T2.W: вырожденные/почти вырожденные параметры зоны из PARAM_SET).
_FALLBACK_SPAN = 1.0

_TEXT_COLOR = "#c8c8c8"


def _param_eng(core: RobotSimCoreV2, name: str) -> float:
    """Инженерное значение параметра ``name`` — ТОЛЬКО через зеркало ``PMIR``
    (F5, ревью T2.W): сырой u16 из ``core.read(REG["PMIR"] + PARAM_ID[name], 1)``,
    декодирован как two's complement, если параметр знаковый (``PARAMS[...]
    ["signed"]`` — тот же признак, что использует само ядро при разборе
    ``PMIR`` в ``_boot``/``_decode``), затем ``to_eng`` (ожидает уже
    декодированное значение, не сырой u16 — см. ``RobotSimCoreV2._boot``,
    где ``to_eng`` вызывается на результате ``_decode``, а не на регистре)."""
    meta = PARAMS[PARAM_ID[name]]
    raw = core.read(REG["PMIR"] + PARAM_ID[name], 1)[0]
    decoded = raw - 65536 if meta["signed"] and raw >= 0x8000 else raw
    return to_eng(name, decoded)


def _widen_domain(lo: float, hi: float) -> tuple[float, float]:
    """(lo, hi) как есть, либо расширение до ``_FALLBACK_SPAN`` вокруг центра,
    если фактический размах меньше него (F1, ревью T2.W: вырожденный/почти
    вырожденный домен — без запаса деление на ноль ниже уронило бы отрисовку,
    а слишком узкий домен слил бы разные значения в одну строку/пиксель).
    Вызывающий обязан передавать уже упорядоченную пару (``lo <= hi``) — оба
    места вызова строят её через ``min(...)``/``max(...)`` над одним и тем же
    набором значений, так что инверсия параметров зоны (``z_min > z_max``)
    сюда не протекает."""
    if hi - lo >= _FALLBACK_SPAN:
        return lo, hi
    centre = (lo + hi) / 2.0
    return centre - _FALLBACK_SPAN / 2.0, centre + _FALLBACK_SPAN / 2.0


def _value_to_y(value: float, lo: float, hi: float, height: float) -> float:
    """Линейная развёртка ``value`` из ``[lo, hi]`` в px по высоте виджета.

    ``hi`` — наверху (``y = margin``), ``lo`` — внизу (``y = margin + usable``).
    Значение за пределами ``[lo, hi]`` зажимается на край (не рисуется за
    границей виджета) — актуально для запроса ``z_to_widget_y`` со значением,
    не входившим в набор, из которого строился домен на последнем ``refresh()``."""
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


class ZScale(QWidget):
    """Read-only вертикальная шкала ``TLM_Z`` поверх ``core``.

    Границы зоны (``P_WS_Z_MIN``/``P_WS_Z_MAX``) и отметки pick/place/home
    перечитываются на каждый ``refresh()`` через зеркало ``PMIR`` (F5) —
    параметры меняются в рантайме (``PARAM_SET``).

    Развёртка шкалы (``z_to_widget_y``) — по СТАТЕЛЕСС-домену, пересчитанному
    заново на каждый ``refresh()`` (F1, ревью T2.W): не голые границы зоны, а
    ``min``/``max`` по границам зоны, текущему Z и всем трём отметкам сразу.
    Иначе Z или отметка вне зоны (плохой ``PARAM_SET``) зажались бы на строку
    границы и стали неотличимы от неё; без памяти между кадрами (домен НЕ
    накапливается — виджет, созданный после ``PARAM_SET``, должен выглядеть
    так же, как созданный до и переживший тот же ``PARAM_SET``)."""

    def __init__(self, core: RobotSimCoreV2, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.core = core
        self._z = 0.0
        self._limits: tuple[float, float] = (0.0, 1.0)
        self._marks: dict[str, float] = {}
        self._domain: tuple[float, float] = (0.0, 1.0)
        self.setMinimumSize(80, 100)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(_REFRESH_MS)
        self.refresh()

    def refresh(self) -> None:
        """Пересчитать текущий Z, границы зоны, отметки и домен развёртки
        из ``core`` (только чтение регистров телеметрии и ``PMIR``)."""
        core = self.core
        self._z = _decode_reg(core.read(REG["TLM_Z"], 1)[0])
        self._limits = (_param_eng(core, "P_WS_Z_MIN"), _param_eng(core, "P_WS_Z_MAX"))
        self._marks = {
            "pick": _param_eng(core, "P_PICK_Z"),
            "place": _param_eng(core, "P_PLACE_Z"),
            "home": _param_eng(core, "P_HOME_Z"),
        }
        z_min, z_max = self._limits
        values = (z_min, z_max, self._z, *self._marks.values())
        self._domain = _widen_domain(min(values), max(values))
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
        """Z (мм) -> y (px): строго убывает по z (больше Z -> меньше y).

        Развёртка — по домену последнего ``refresh()`` (``_widen_domain`` над
        границами зоны, текущим Z и отметками), не по голым границам зоны —
        см. докстринг класса."""
        lo, hi = self._domain
        return _value_to_y(z, lo, hi, max(self.height(), 1))

    def closeEvent(self, event) -> None:  # noqa: N802 (переопределение Qt)
        """Остановить таймер перерисовки при закрытии (как у SimView)."""
        self._timer.stop()
        super().closeEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 (переопределение Qt)
        """Остановить таймер при скрытии (F4): ``closeEvent`` приходит только
        окну верхнего уровня, встроенный виджет иначе тикал бы после закрытия."""
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 (переопределение Qt)
        """Возобновить таймер при повторном показе (пара к ``hideEvent``)."""
        self._timer.start(_REFRESH_MS)
        super().showEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (переопределение Qt)
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor("#1b1b1b"))
            # Порядок: границы -> отметки -> текущий Z (текущий рисуется поверх).
            for z in self._limits:
                self._paint_row(painter, z, "#ff5c57")
            for name, z in self._marks.items():
                self._paint_row(painter, z, "#8be9fd", label=name)
            # Подпись текущего Z — ПОД линией (отметки подписаны над своей): при Z,
            # равном отметке (на старте Z = home), подписи иначе легли бы одна на
            # другую (живой снимок T2.W).
            self._paint_row(painter, self._z, "#5af78e", label="Z", below=True)
        finally:
            painter.end()

    def _paint_row(
        self, painter: QPainter, z: float, color: str, label: str | None = None, below: bool = False
    ) -> None:
        y = self.z_to_widget_y(z)
        pen = QPen(QColor(color))
        pen.setWidth(3)
        painter.setPen(pen)
        painter.drawLine(QPointF(0, y), QPointF(self.width(), y))
        if label:
            painter.setPen(QPen(QColor(_TEXT_COLOR)))
            # Сторона подписи — предпочтительная, но у края домена она перекидывается
            # на другую, иначе обрезалась бы краем виджета (ревью T2.W, итерации 1–2:
            # Z на z_min — снизу, отметка на z_max — сверху).
            if below and y + 14 > self.height() - 2:
                below = False
            elif not below and y - 16 < 0:
                below = True
            painter.drawText(QPointF(12, y + 14 if below else y - 4), f"{label} {z:.1f}")


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
        """Добавить одну выборку (clock(), Z, RZ), отбросить старше окна,
        перечитать границы зоны через ``PMIR`` (F5), перерисовать."""
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
        self._z_limits = (_param_eng(core, "P_WS_Z_MIN"), _param_eng(core, "P_WS_Z_MAX"))
        self._rz_limits = (_param_eng(core, "P_WS_RZ_MIN"), _param_eng(core, "P_WS_RZ_MAX"))
        self.update()

    def samples(self) -> list[tuple[float, float, float]]:
        """Выборки (t, Z, RZ) по возрастанию времени добавления — копия внутреннего буфера."""
        return list(self._samples)

    def closeEvent(self, event) -> None:  # noqa: N802 (переопределение Qt)
        """Остановить таймер перерисовки при закрытии (как у SimView)."""
        self._timer.stop()
        super().closeEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 (переопределение Qt)
        """Остановить таймер при скрытии (F4): ``closeEvent`` приходит только
        окну верхнего уровня, встроенный виджет иначе тикал бы после закрытия."""
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 (переопределение Qt)
        """Возобновить таймер при повторном показе (пара к ``hideEvent``)."""
        self._timer.start(_REFRESH_MS)
        super().showEvent(event)

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
        lo_base, hi_base = limits
        values = [s[key] for s in samples]
        # Домен по кадру (F1, ревью T2.W): границы зоны И все выборки — не
        # только границы. Значение вне зоны (или зона схлопнута) иначе
        # зажалось бы на край и стало неотличимо от границы. Пересчитывается
        # на каждый paintEvent (не хранится) — окно ленты меняет набор
        # выборок каждый кадр, кэш домена быстро бы устарел.
        lo, hi = _widen_domain(min(lo_base, hi_base, *values), max(lo_base, hi_base, *values))
        points = [QPointF(_value_to_x(s[0], now, self.window_s, w), _value_to_y(s[key], lo, hi, h)) for s in samples]
        pen = QPen(QColor(color))
        pen.setWidth(2)
        painter.setPen(pen)
        for a, b in zip(points, points[1:]):
            painter.drawLine(a, b)
