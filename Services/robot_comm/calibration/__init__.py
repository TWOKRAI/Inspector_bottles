"""Калибровки робота v2: лента по двум отметкам, СК по точкам, проверка точек инструментов (T5.4m).

Purpose:
    Чистая математика без ввода-вывода: числа на входе, результат или `CalibrationError` на выходе. Запись
    результатов в параметры и файлы, команды хаба — не здесь (T5.4c).

Public API:
    ``CalibrationError``, ``BeltResult``, ``belt_from_marks``, ``BELT_AXES``, ``FrameFit``, ``fit_frame``,
    ``ToolCheck``, ``check_tool_points``.

Stability: lite (контракт держат тесты ``test_calibration_math.py``).

Потоков и состояния нет. ``Services.robot_comm`` этот пакет не импортирует: ``numpy`` грузит только сам пакет.
"""

from __future__ import annotations

from Services.robot_comm.calibration.belt import (
    BELT_AXES,
    BeltResult,
    CalibrationError,
    belt_from_marks,
)
from Services.robot_comm.calibration.frame_fit import FrameFit, fit_frame
from Services.robot_comm.calibration.tools import ToolCheck, check_tool_points

__all__ = [
    "BELT_AXES",
    "BeltResult",
    "CalibrationError",
    "FrameFit",
    "ToolCheck",
    "belt_from_marks",
    "check_tool_points",
    "fit_frame",
]
