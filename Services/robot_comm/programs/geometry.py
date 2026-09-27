"""Геометрия рабочей зоны SCARA и системы координат (protocol-spec §7.3).

Проверяет точки (`check_point`) и XY-отрезки LINE/LINE_PASS (`check_segment`)
на попадание в рабочую зону робота: кольцо `[r_min, r_max]` вокруг оси J1,
сектор поворота J1, диапазоны Z и RZ, опциональный прямоугольный бокс. Единицы
измерения — мм и градусы. Модуль Qt-independent, состояние не хранит, зависит
только от stdlib `math` — единая геометрия для симулятора (T2.2), компиляции
программ (T3.3) и драйвера контроллера.

Эта проверка необходима, но не достаточна: точные пределы осей знает только
контроллер. Штатная рабочая зона DRAStudio (`OpenWorkSpace`/`WorkSpace`) на
объекте остаётся вторым, окончательным слоем защиты (protocol-spec §7.3).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from Services.robot_comm.core.protocol_v2 import REASON

Vector3 = tuple[float, float, float]


def _sub(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vector3, b: Vector3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vector3, b: Vector3) -> Vector3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _scale(a: Vector3, s: float) -> Vector3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _norm(a: Vector3) -> float:
    return math.sqrt(_dot(a, a))


@dataclass(frozen=True)
class Workspace:
    """Рабочая зона SCARA: кольцо + сектор J1 + Z/RZ + опциональный бокс."""

    r_min: float
    r_max: float
    z_min: float
    z_max: float
    rz_min: float
    rz_max: float
    ang_min: float
    ang_max: float
    box_en: bool
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    @classmethod
    def from_params(cls, values: Mapping[str, float]) -> "Workspace":
        """Строит Workspace из карты `P_WS_*` в мм и °; из сырых ×0.1 — через `params_v2.to_eng`."""
        return cls(
            r_min=float(values["P_WS_R_MIN"]),
            r_max=float(values["P_WS_R_MAX"]),
            z_min=float(values["P_WS_Z_MIN"]),
            z_max=float(values["P_WS_Z_MAX"]),
            rz_min=float(values["P_WS_RZ_MIN"]),
            rz_max=float(values["P_WS_RZ_MAX"]),
            ang_min=float(values["P_WS_ANG_MIN"]),
            ang_max=float(values["P_WS_ANG_MAX"]),
            box_en=bool(values["P_WS_BOX_EN"]),
            x_min=float(values["P_WS_X_MIN"]),
            x_max=float(values["P_WS_X_MAX"]),
            y_min=float(values["P_WS_Y_MIN"]),
            y_max=float(values["P_WS_Y_MAX"]),
        )


def check_point(ws: Workspace, x: float, y: float, z: float, rz: float) -> int:
    """Проверяет точку (x, y, z, rz) на попадание в рабочую зону `ws`.

    Возвращает 0 (допустимо) или `REASON["R_OUT_OF_ZONE"]`. Все границы
    включительны.
    """
    r = math.hypot(x, y)
    if not (ws.r_min <= r <= ws.r_max):
        return REASON["R_OUT_OF_ZONE"]
    if not (ws.z_min <= z <= ws.z_max):
        return REASON["R_OUT_OF_ZONE"]
    if not (ws.rz_min <= rz <= ws.rz_max):
        return REASON["R_OUT_OF_ZONE"]

    angle = math.degrees(math.atan2(y, x))
    if not (ws.ang_min <= angle <= ws.ang_max):
        return REASON["R_OUT_OF_ZONE"]

    if ws.box_en and (not (ws.x_min <= x <= ws.x_max) or not (ws.y_min <= y <= ws.y_max)):
        return REASON["R_OUT_OF_ZONE"]

    return 0


def check_segment(ws: Workspace, x0: float, y0: float, x1: float, y1: float) -> int:
    """Проверяет XY-отрезок LINE/LINE_PASS-хода на попадание в рабочую зону `ws`.

    Сначала аналитически проверяет минимальное расстояние от оси J1 (0, 0) до
    отрезка (проекция начала координат на отрезок, t зажат в [0, 1]): строго
    меньше `r_min` — мёртвая зона (`R_DEAD_ZONE`), ровно `r_min` допустимо.
    Затем выборкой через каждые ≤5 мм (сектор с дырой невыпуклый — прямая
    между двумя достижимыми точками может пройти через недостижимую зону)
    проверяет попадание в сектор `[ang_min, ang_max]`. Валидность самих
    концов отрезка здесь не проверяется — это забота вызывающего кода.
    """
    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
        return REASON["R_OUT_OF_ZONE"]  # NaN/inf не должны молча становиться «разрешено» или исключением
    dx = x1 - x0
    dy = y1 - y0
    len2 = dx * dx + dy * dy

    if len2 > 0.0:
        t = -(x0 * dx + y0 * dy) / len2
        t = max(0.0, min(1.0, t))
    else:
        t = 0.0
    closest_x = x0 + t * dx
    closest_y = y0 + t * dy
    if math.hypot(closest_x, closest_y) < ws.r_min:
        return REASON["R_DEAD_ZONE"]

    length = math.hypot(dx, dy)
    n = max(1, math.ceil(length / 5.0))
    for i in range(n + 1):
        ti = i / n
        px = x0 + ti * dx
        py = y0 + ti * dy
        angle = math.degrees(math.atan2(py, px))
        if not (ws.ang_min <= angle <= ws.ang_max):
            return REASON["R_OUT_OF_ZONE"]

    return 0


@dataclass(frozen=True)
class Frame:
    """Локальная система координат (origin + базис ex/ey/ez + yaw в base-фрейме)."""

    origin: Vector3
    ex: Vector3
    ey: Vector3
    ez: Vector3
    yaw: float

    @classmethod
    def from_points(cls, origin: Vector3, on_x: Vector3, in_plane: Vector3) -> "Frame":
        """Строит Frame по трём точкам base-фрейма: origin, точка на оси X, точка в плоскости XY.

        `ex` — нормированное направление origin -> on_x, `ez` — нормаль плоскости
        (origin, on_x, in_plane), `ey = ez × ex`. `yaw` — угол `ex` в base-фрейме
        (градусы). Ось Z всегда смотрит вверх (инструмент SCARA вертикален): третья точка задаёт
        только плоскость, сторона (+Y или −Y) не важна. Бросает `ValueError`, если on_x ближе 1 мм
        к origin, in_plane ближе 1 мм к прямой оси X (плоскость не определена) или координаты
        не конечны.
        """
        on_x_vec = _sub(on_x, origin)
        on_x_len = _norm(on_x_vec)
        if not on_x_len >= 1.0:  # «not >=» ловит и NaN
            raise ValueError("on_x слишком близко к origin (< 1 мм) — ось X не определена")
        ex = _scale(on_x_vec, 1.0 / on_x_len)

        in_plane_vec = _sub(in_plane, origin)
        ez_raw = _cross(ex, in_plane_vec)
        ez_len = _norm(ez_raw)
        if not ez_len >= 1.0:
            raise ValueError("in_plane слишком близко к оси X (< 1 мм) — плоскость не определена")
        ez = _scale(ez_raw, 1.0 / ez_len)
        if ez[2] < 0:  # третья точка со стороны −Y: разворачиваем нормаль, иначе «над листом» ушло бы под лист
            ez = _scale(ez, -1.0)

        ey = _cross(ez, ex)

        yaw = math.degrees(math.atan2(ex[1], ex[0]))
        return cls(origin=origin, ex=ex, ey=ey, ez=ez, yaw=yaw)

    def to_base(self, x: float, y: float, z: float, rz: float) -> tuple[float, float, float, float]:
        """Переводит точку локального фрейма (x, y, z, rz) в base-фрейм."""
        px = self.origin[0] + x * self.ex[0] + y * self.ey[0] + z * self.ez[0]
        py = self.origin[1] + x * self.ex[1] + y * self.ey[1] + z * self.ez[1]
        pz = self.origin[2] + x * self.ex[2] + y * self.ey[2] + z * self.ez[2]
        return (px, py, pz, rz + self.yaw)

    def from_base(self, x: float, y: float, z: float, rz: float) -> tuple[float, float, float, float]:
        """Переводит точку base-фрейма (x, y, z, rz) в локальный фрейм (обратно to_base)."""
        v = _sub((x, y, z), self.origin)
        lx = _dot(v, self.ex)
        ly = _dot(v, self.ey)
        lz = _dot(v, self.ez)
        return (lx, ly, lz, rz - self.yaw)
