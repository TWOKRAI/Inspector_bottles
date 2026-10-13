"""Генераторы программ робота (T3.4, ADR-RC-011): рисование, возврат в слот, смена инструмента.

Purpose: чистые функции «штрихи или точки + параметры → `GeneratedProgram`» поверх моделей T3.3.
Генератор не вызывает `compile_program`: зону, руку и отрезки проверяет вызывающий одной компиляцией.
Провод (`wire_v2`, клиент, pymodbus) и геометрия здесь не импортируются.

Public API: `GeneratedProgram`, `GeneratorError`, `draw`, `circle_stroke`, `square_stroke`,
`return_slot`, `toolchange`, `TOOL_POINTS_V1`, `TRANSIT_V1`.

Stability: lite
"""

from Services.robot_comm.programs.generators._common import GeneratedProgram, GeneratorError
from Services.robot_comm.programs.generators.drawing import circle_stroke, draw, square_stroke
from Services.robot_comm.programs.generators.routes import TOOL_POINTS_V1, TRANSIT_V1, return_slot, toolchange

__all__ = [
    "TOOL_POINTS_V1",
    "TRANSIT_V1",
    "GeneratedProgram",
    "GeneratorError",
    "circle_stroke",
    "draw",
    "return_slot",
    "square_stroke",
    "toolchange",
]
