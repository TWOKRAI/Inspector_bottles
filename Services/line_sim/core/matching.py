"""Сопоставление «задание робота выполнено» <-> «объект на ленте» (Task 3.5).

Чистая функция без побочных эффектов и без знания о плагинах/IPC — родственник
`SimJournal._residual_mm` (`Services/robot_comm/server/sim_journal.py`), но там
сравниваются два ЗАДАНИЯ (job vs job, детект дублей эха), а здесь — ЗАДАНИЕ и
АКТИВНЫЙ/СНЯТЫЙ ОБЪЕКТ сцены (`ObjectPassport`). Реализация не переиспользует
`SimJournal` и не импортирует его — только общая идея «невязка по XY».

Pre:
  - `match_radius_mm > 0` (`match_job` иначе поднимает `ValueError`).
  - `job.ecap` — то же 32-битное значение E_capture, которое ядро робота
    (`RobotSimCore.on_job_done`) декодирует из пары регистров `REG_JOB_ECAP`.
Post:
  - `match_job` — победитель среди `active` ∪ `removed`: минимальная невязка XY
    до `(job.x_mm, job.y_mm)`, строго `< match_radius_mm`. Победитель из `active`
    -> `outcome="matched"`; из `removed` -> `outcome="dup"`; ни один кандидат не
    прошёл порог (или кандидатов нет вовсе) -> `outcome="no_object"`,
    `object_id=None`. Ничья по невязке между `active` и `removed` разрешается в
    пользу `active` (кандидаты `active` проверяются первыми, кандидат из
    `removed` заменяет текущего победителя только при СТРОГО меньшей невязке).
  - `residual_mm` — минимальная найденная невязка среди всех кандидатов;
    `None` только когда кандидатов нет вовсе (`active` и `removed` оба пусты).
  - `BeltGeometry`/`JobDone` — round-trip: `from_dict(x.to_dict()) == x`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from Services.line_sim.core.belt import BELT_UX, BELT_UY, encoder_to_offset_mm
from Services.line_sim.interfaces import ObjectPassport


@dataclass(frozen=True)
class BeltGeometry:
    """Координаты робота, отвечающие точке сцены «путь 0 вдоль ленты, центр полосы».

    Направление хода ленты не поле — общий `BELT_UX`/`BELT_UY` (см. `belt.py`).
    """

    origin_x_mm: float = 0.0
    origin_y_mm: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {"origin_x_mm": self.origin_x_mm, "origin_y_mm": self.origin_y_mm}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BeltGeometry:
        return cls(origin_x_mm=float(data["origin_x_mm"]), origin_y_mm=float(data["origin_y_mm"]))


@dataclass(frozen=True)
class JobDone:
    """Событие `RobotSimCore.on_job_done` на границе процесса — см. Services/robot_comm/
    server/sim_core.py, §1 контракта лида 3.5."""

    index: int
    x_mm: float
    y_mm: float
    ecap: int
    t: float

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "x_mm": self.x_mm, "y_mm": self.y_mm, "ecap": self.ecap, "t": self.t}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobDone:
        return cls(
            index=int(data["index"]),
            x_mm=float(data["x_mm"]),
            y_mm=float(data["y_mm"]),
            ecap=int(data["ecap"]),
            t=float(data["t"]),
        )


@dataclass(frozen=True)
class MatchResult:
    """Исход сопоставления — см. Post докстринга модуля."""

    outcome: Literal["matched", "dup", "no_object"]
    object_id: str | None
    residual_mm: float | None


def object_robot_xy(spawn_encoder: float, ecap: float, geometry: BeltGeometry) -> tuple[float, float]:
    """Координаты объекта в системе робота на момент энкодера `ecap` — тот же путь
    вдоль ленты, что и трекинг робота (`FACTOR_MM`, `BELT_UX`/`BELT_UY`)."""
    off = encoder_to_offset_mm(ecap, spawn_encoder)
    return geometry.origin_x_mm + BELT_UX * off, geometry.origin_y_mm + BELT_UY * off


def match_job(
    active: Iterable[ObjectPassport],
    job: JobDone,
    geometry: BeltGeometry,
    *,
    removed: Iterable[ObjectPassport] = (),
    match_radius_mm: float = 5.0,
) -> MatchResult:
    """Сопоставить `job` с ближайшим объектом среди `active` ∪ `removed` — см. Post
    докстринга модуля."""
    if match_radius_mm <= 0:
        raise ValueError(f"match_radius_mm должен быть положительным, получено {match_radius_mm!r}")

    best_residual: float | None = None
    best_object_id: str | None = None
    best_is_active = False

    for passport in active:
        x, y = object_robot_xy(passport.spawn_encoder, job.ecap, geometry)
        residual = math.hypot(x - job.x_mm, y - job.y_mm)
        if best_residual is None or residual < best_residual:
            best_residual, best_object_id, best_is_active = residual, passport.object_id, True

    for passport in removed:
        x, y = object_robot_xy(passport.spawn_encoder, job.ecap, geometry)
        residual = math.hypot(x - job.x_mm, y - job.y_mm)
        if best_residual is None or residual < best_residual:
            best_residual, best_object_id, best_is_active = residual, passport.object_id, False

    if best_residual is None:
        return MatchResult(outcome="no_object", object_id=None, residual_mm=None)
    if best_residual < match_radius_mm:
        outcome: Literal["matched", "dup"] = "matched" if best_is_active else "dup"
        return MatchResult(outcome=outcome, object_id=best_object_id, residual_mm=best_residual)
    return MatchResult(outcome="no_object", object_id=None, residual_mm=best_residual)
