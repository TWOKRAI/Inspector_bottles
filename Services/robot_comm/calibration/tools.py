"""Проверка обученных точек инструментов: наличие и допустимость (T5.4m).

Purpose:
    Чистая функция `check_tool_points`: по карте обученных точек и таблицам маршрутов `TOOL_POINTS_V1` /
    `TRANSIT_V1` сообщает по каждому инструменту, каких точек не хватает и какие правила нарушены.
    Файлов и робота не касается.

Public API: `ToolCheck`, `check_tool_points`, `TOOL_PROBLEMS`.

Stability: lite (контракт держат тесты `test_calibration_math.py`).

Потоков и состояния нет.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from Services.robot_comm.programs import Point
from Services.robot_comm.programs.generators.routes import TOOL_POINTS_V1, TRANSIT_V1

__all__ = ["TOOL_PROBLEMS", "ToolCheck", "check_tool_points"]

# Коды проблем точек инструмента; порядок кортежа задаёт порядок в `ToolCheck.problems`.
TOOL_PROBLEMS: tuple[str, ...] = ("not_in_base", "over_not_above_pick")


@dataclass(frozen=True)
class ToolCheck:
    """Итог проверки одного инструмента.

    Поля: `tool` — номер инструмента; `ok` — нет ни пропавших точек, ни проблем; `missing` — имена
    отсутствующих точек, по алфавиту; `problems` — коды из `TOOL_PROBLEMS`, в порядке `TOOL_PROBLEMS`.
    """

    tool: int
    ok: bool
    missing: tuple[str, ...]
    problems: tuple[str, ...]


def check_tool_points(
    points: Mapping[str, Point],
    *,
    tools: Mapping[int, tuple[str, str, str]] = TOOL_POINTS_V1,
    transit: Mapping[int, str] = TRANSIT_V1,
    min_clear_mm: float = 1.0,
) -> list[ToolCheck]:
    """Проверить точки каждого инструмента из `tools`.

    Pre: `points` — карта «имя -> Point»; `tools[n]` — тройка имён (над инструментом, гнездо, выход);
    `transit[n]` — имя транзитной точки инструмента n (если задана).
    Post: список `ToolCheck`, по одному на номер из `tools`, по возрастанию номера. `missing` — из имён тройки
    и транзитной точки (`transit.get(n)`) те, которых нет в `points`. Проблемы (только по имеющимся точкам):
    `not_in_base` — у какой-либо из точек инструмента `frame` не `None`; `over_not_above_pick` — при наличии
    «над» и гнезда `over.z - pick.z < min_clear_mm`. Других правил нет.
    Raises: ничего не поднимает.

    Проверяются имена тройки и транзитной точки; `not_in_base` - по любой имеющейся из них.
    """
    results: list[ToolCheck] = []
    for number in sorted(tools):
        over_name, pick_name, _exit_name = tools[number]
        names = set(tools[number])
        transit_name = transit.get(number)
        if transit_name is not None:
            names.add(transit_name)
        missing = tuple(sorted(name for name in names if name not in points))
        problems: list[str] = []
        if any(points[name].frame is not None for name in names if name in points):
            problems.append("not_in_base")
        if over_name in points and pick_name in points and points[over_name].z - points[pick_name].z < min_clear_mm:
            problems.append("over_not_above_pick")
        results.append(
            ToolCheck(tool=number, ok=not missing and not problems, missing=missing, problems=tuple(problems))
        )
    return results
