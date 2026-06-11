"""Типы данных robot_comm (Dict at Boundary: наружу процессов — to_dict)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class RobotPosition:
    """Текущая поза инструмента (главное для калибровки)."""

    x_mm: float
    y_mm: float
    z_mm: float
    rz_deg: float

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return asdict(self)


@dataclass(slots=True, frozen=True)
class Telemetry:
    """Телеметрия робота — блок 0x1130 (11 слов, universal3).

    ВНИМАНИЕ: heartbeat пишется Lua только в idle CVT-ветке — во время job/draw
    телеметрия «стоит», это норма, не обрыв связи. Индикатор «связь жива» —
    по успешности Modbus-чтений, не по этому полю.
    """

    x_mm: float
    y_mm: float
    z_mm: float
    rz_deg: float
    moving: bool
    spd_pct: int
    belt_mm_s: int
    heartbeat: int
    servo: bool
    hand: int
    miss_count: int

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return asdict(self)

    @property
    def position(self) -> RobotPosition:
        """Срез позы из телеметрии."""
        return RobotPosition(self.x_mm, self.y_mm, self.z_mm, self.rz_deg)


@dataclass(slots=True, frozen=True)
class JobEcho:
    """Эхо последнего принятого CVT-задания (блок 0x1120)."""

    job_x: float
    job_y: float
    px: float
    py: float
    trav: float

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return asdict(self)


@dataclass(slots=True, frozen=True)
class DrawPoint:
    """Точка пути рисования: координаты + состояние пера (1 = опущено)."""

    x_mm: float
    y_mm: float
    pen: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать в dict."""
        return asdict(self)
