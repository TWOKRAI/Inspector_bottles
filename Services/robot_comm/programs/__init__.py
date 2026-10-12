"""Пакет программ и геометрии SCARA (protocol-spec §7.3).

Программы робота (T3.3) — модели и `compile_program` из `program.py`; геометрия зоны —
модуль `geometry` (импортируется модулем, не реэкспортируется).
"""

from Services.robot_comm.programs.program import (
    Action,
    CompileError,
    FrameDef,
    Move,
    Point,
    Program,
    Record,
    Scenario,
    compile_program,
)

__all__ = [
    "Action",
    "CompileError",
    "FrameDef",
    "Move",
    "Point",
    "Program",
    "Record",
    "Scenario",
    "compile_program",
]
