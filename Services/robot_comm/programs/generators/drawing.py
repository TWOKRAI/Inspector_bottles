"""Генератор рисования: штрихи в СК листа → программа робота (T3.4; v1 `execute_path`, ADR-RC-008).

Purpose: превратить рисунок (штрихи — полилинии XY в СК листа) в программу T3.3: подвод JOINT над
началом, опускание, штрих (внутри LINE_PASS, конец и каждая `max_pass_run + 1`-я точка подряд — LINE),
подъём, переезд на высоте, финальный подъём. Круг и квадрат — готовые полилинии (О-4: на v2 круг —
полилиния с ПК, а не `MCircle` прошивки).

Public API: `draw`, `circle_stroke`, `square_stroke`.

Stability: lite
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

from Services.robot_comm.programs import Point
from Services.robot_comm.programs.generators._common import GeneratedProgram, GeneratorError, _Builder

__all__ = ["circle_stroke", "draw", "square_stroke"]

type XY = tuple[float, float]


def _dedup(stroke: Sequence[XY]) -> list[XY]:
    """Соседние точки с точно равными XY (`==` кортежей, без допуска) — вторая отбрасывается."""
    out: list[XY] = []
    for x, y in stroke:
        if not out or out[-1] != (x, y):
            out.append((x, y))
    return out


def draw(
    strokes: Sequence[Sequence[XY]],
    *,
    frame: str | None,
    hand: Literal[0, 1],
    rz: float,
    pen_down: float,
    pen_up: float,
    lift_mm: float = 10.0,
    draw_speed_pct: int = 30,
    travel_speed_pct: int = 100,
    accel: int | None = None,
    max_pass_run: int = 26,
    name: str = "draw",
    home: Point | None = None,
) -> GeneratedProgram:
    """Штрихи (XY в СК `frame`, `None` — база) → программа рисования.

    Z всех точек — в СК `frame`: `pen_down` (перо на листе), `pen_up` (переезд), `pen_up + lift_mm`
    (финальный подъём). RZ — `rz`, рука — `hand`. Умолчания — из v1: `DRAW_LIFT_MM` 10,
    `DRAW_SPD0` 30, `TRAVEL_SPD0` 100; `accel=None` — действие ACCEL не ставится (прошивка берёт
    `P_ACC_L`). `max_pass_run` 26 = `SC_CAP // 2 - 1`: длиннее ряд LINE_PASS не режется на куски
    пинг-понга (связь держит тест автора, провод здесь не импортируется).

    Pre: `strokes` не пуст, ни один штрих не пуст; `pen_up > pen_down`; `lift_mm >= 0`;
    `max_pass_run >= 1` — иначе `GeneratorError`. Неконечная координата, скорость или ускорение вне
    диапазона — `ValueError` валидации `Point`/`Action`.
    Post: первый шаг — `Move` JOINT, действий до него нет; действия — только после EXACT-ходов;
    соседние равные XY штриха схлопнуты (ходов нулевой длины внутри штриха нет); ряд LINE_PASS подряд
    не длиннее `max_pass_run`; между штрихами нет LINE_PASS; последний ход — финальный подъём LINE
    (или JOINT в `home`, если задан). Зону и руку проверяет вызывающий через `compile_program`.
    """
    if not strokes:
        raise GeneratorError("рисунок пуст: нет ни одного штриха")
    if any(len(stroke) == 0 for stroke in strokes):
        raise GeneratorError("пустой штрих в рисунке")
    if pen_up <= pen_down:
        raise GeneratorError("высота пера над листом должна быть больше высоты пера на листе")
    if lift_mm < 0:
        raise GeneratorError("финальный подъём не может быть отрицательным")
    if max_pass_run < 1:
        raise GeneratorError("длина ряда LINE_PASS должна быть не меньше 1")

    b = _Builder(name)

    def p(xy: XY, z: float, kind: str) -> None:
        b.move_new(xy[0], xy[1], z, rz, hand=hand, frame=frame, kind=kind)

    end: XY | None = None  # последняя точка предыдущего штриха
    for k, raw in enumerate(strokes):
        s = _dedup(raw)
        if end is None:
            p(s[0], pen_up, "JOINT")  # подвод — первый ход программы
        else:
            b.act("SPEED_PCT", travel_speed_pct)  # стоим на EXACT-конце прошлого штриха
            p(end, pen_up, "LINE")  # подъём вертикально в текущем XY
            if s[0] != end:
                p(s[0], pen_up, "LINE")  # переезд на высоте; совпало XY — пропуск
        b.act("SPEED_PCT", draw_speed_pct)
        if k == 0 and accel is not None:
            b.act("ACCEL", accel)
        p(s[0], pen_down, "LINE")  # опускание вертикально
        run = 0
        last = len(s) - 1
        for j in range(1, len(s)):
            if j == last or run == max_pass_run:
                kind, run = "LINE", 0  # конец штриха EXACT; EXACT каждые max_pass_run
            else:
                kind, run = "LINE_PASS", run + 1
            p(s[j], pen_down, kind)
        end = s[-1]
    assert end is not None  # strokes не пуст
    b.act("SPEED_PCT", travel_speed_pct)
    p(end, pen_up + lift_mm, "LINE")  # финальный подъём одним ходом
    if home is not None:
        b.move_ref(home, "JOINT")
    return b.build()


def circle_stroke(cx: float, cy: float, r: float, *, segments: int = 64) -> tuple[XY, ...]:
    """Замкнутая полилиния круга (О-4 вместо `MCircle` v1): старт `(cx + r, cy)`, обход против часовой.

    Pre: `r > 0`, `segments >= 3` — иначе `GeneratorError`.
    Post: `segments + 1` точек; точка j = `(cx + r·cos(2πj/segments), cy + r·sin(2πj/segments))`;
    последняя — тот же кортеж, что первая (без дрейфа float).
    """
    if not r > 0:
        raise GeneratorError("радиус круга должен быть больше 0")
    if segments < 3:
        raise GeneratorError("у круга должно быть не меньше 3 сегментов")
    pts = [
        (cx + r * math.cos(2 * math.pi * j / segments), cy + r * math.sin(2 * math.pi * j / segments))
        for j in range(segments)
    ]
    pts.append(pts[0])
    return tuple(pts)


def square_stroke(x1: float, y1: float, x2: float, y2: float) -> tuple[XY, ...]:
    """Замкнутый прямоугольник по двум углам, как v1 `_op_draw_square`.

    Pre: `x1 != x2` и `y1 != y2` — иначе `GeneratorError`.
    Post: `((x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1))`; углы внутри штриха `draw` проходит
    LINE_PASS (сглаживание, как в v1).
    """
    if x1 == x2 or y1 == y2:
        raise GeneratorError("вырожденный прямоугольник: стороны должны быть ненулевыми")
    return ((x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1))
