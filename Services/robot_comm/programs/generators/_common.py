"""Общий контракт генераторов программ робота (T3.4).

Purpose: выход генератора (`GeneratedProgram`), ошибка аргументов (`GeneratorError`) и внутренний
сборщик `_Builder`, который держит правила T3.3 для всех генераторов: первый ход JOINT, последний ход
не LINE_PASS, действия только после EXACT-точек.

Public API: `GeneratedProgram`, `GeneratorError` (сборщик `_Builder` — внутренний).

Stability: lite
"""

from __future__ import annotations

from typing import Literal, NamedTuple

from Services.robot_comm.programs import Action, Move, Point, Program

__all__ = ["GeneratedProgram", "GeneratorError"]


class GeneratedProgram(NamedTuple):
    """Программа и все точки, на которые ссылаются её шаги `Move` (и только они).

    `compile_program(gp.program, gp.points, frames, params)` работает без склейки словарей:
    вызывающему нужны только свои `frames`.
    """

    program: Program
    points: dict[str, Point]


class GeneratorError(ValueError):
    """Ошибка аргументов генератора. Текст по-русски, без координат; имена точек — можно."""


class _Builder:
    """Сборщик программы: создаёт точки `"<name>/<i>"`, шаги `Move`/`Action` и проверяет инварианты в `build()`."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._steps: list[Move | Action] = []
        self._points: dict[str, Point] = {}
        self._created = 0

    def move_new(
        self,
        x: float,
        y: float,
        z: float,
        rz: float,
        *,
        hand: Literal[0, 1],
        frame: str | None,
        kind: str,
    ) -> None:
        """Новая точка с именем `"<name>/<i>"` (i — счётчик созданных точек с 0) и шаг `Move` в неё."""
        point = Point(name=f"{self._name}/{self._created}", x=x, y=y, z=z, rz=rz, hand=hand, frame=frame)
        self._created += 1
        self.move_ref(point, kind)

    def move_ref(self, point: Point, kind: str) -> None:
        """Шаг `Move` на готовую точку (обученную или `home`); другая точка с тем же именем → `GeneratorError`."""
        known = self._points.get(point.name)
        if known is not None and known != point:
            raise GeneratorError(f"конфликт имён точек: {point.name}")
        self._points[point.name] = point
        self._steps.append(Move(point=point.name, kind=kind))

    def act(self, act: str, value: int) -> None:
        """Шаг `Action`."""
        self._steps.append(Action(act=act, value=value))

    def last_move_name(self) -> str | None:
        """Имя точки шага-`Move`, если последний шаг — `Move`; иначе `None` (между ними было действие)."""
        if self._steps and isinstance(self._steps[-1], Move):
            return self._steps[-1].point
        return None

    def build(self) -> GeneratedProgram:
        """Проверка инвариантов (защита от ошибки в генераторе) и выход `GeneratedProgram`."""
        steps = self._steps
        if not steps or not isinstance(steps[0], Move) or steps[0].kind != "JOINT":
            raise GeneratorError("ошибка генератора: первый шаг программы — не ход JOINT")
        moves = [s for s in steps if isinstance(s, Move)]
        if moves[-1].kind == "LINE_PASS":
            raise GeneratorError("ошибка генератора: последний ход — LINE_PASS")
        last_move: Move | None = None
        for step in steps:
            if isinstance(step, Move):
                last_move = step
            elif last_move is not None and last_move.kind == "LINE_PASS":
                raise GeneratorError("ошибка генератора: действие после хода LINE_PASS")
        return GeneratedProgram(Program(name=self._name, steps=tuple(steps)), dict(self._points))
