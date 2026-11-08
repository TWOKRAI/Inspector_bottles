"""Калибровка ленты по двум отметкам: коэффициент мм/импульс и направление (T5.4m).

Purpose:
    Чистая функция `belt_from_marks`: по двум положениям детали на ленте (мм в базе робота) и двум показаниям
    энкодера даёт сырое значение коэффициента ленты и индекс направления (`P_BELT_DIR`). Файлов и робота не
    касается. Здесь же — `CalibrationError` пакета и константы отказов (`TEXT_*`).

Public API: `CalibrationError`, `BeltResult`, `belt_from_marks`, `BELT_AXES`, `BELT_FACTOR_SCALE`,
    `MIN_TRAVEL_MM`, `MAX_AXIS_DEV_DEG`, `TEXT_*`.

Stability: lite (контракт держат тесты `test_calibration_math.py`).

Потоков и состояния нет.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "BELT_AXES",
    "BELT_FACTOR_SCALE",
    "MAX_AXIS_DEV_DEG",
    "MIN_TRAVEL_MM",
    "TEXT_BELT_BAD_MARKS",
    "TEXT_BELT_FACTOR_RANGE",
    "TEXT_BELT_NO_ENCODER",
    "TEXT_BELT_OFF_AXIS",
    "TEXT_BELT_SHORT",
    "TEXT_FRAME_BAD_POINTS",
    "TEXT_FRAME_DEGENERATE",
    "TEXT_FRAME_RESIDUAL",
    "TEXT_FRAME_UPSIDE_DOWN",
    "BeltResult",
    "CalibrationError",
    "belt_from_marks",
]

# Индекс = значение `P_BELT_DIR`: 0 +X, 1 +Y, 2 -X, 3 -Y (совпадает с `sim_core_v2.py`).
BELT_AXES: tuple[tuple[float, float], ...] = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))
# мм на импульс, соответствующие единице сырого значения параметра.
BELT_FACTOR_SCALE: float = 1e-5
# Минимальный ход ленты между отметками, мм.
MIN_TRAVEL_MM: float = 100.0
# Допустимое отклонение хода от ближайшей оси робота, градусы.
MAX_AXIS_DEV_DEG: float = 1.0

# Тексты отказов: постоянные, без входных значений (уходят в ответ команды как есть).
TEXT_BELT_BAD_MARKS = "неверные отметки ленты"
TEXT_BELT_NO_ENCODER = "энкодер не изменился между отметками"
TEXT_BELT_SHORT = "мало хода ленты между отметками"
TEXT_BELT_OFF_AXIS = "лента не вдоль оси робота"
TEXT_BELT_FACTOR_RANGE = "коэффициент ленты вне диапазона параметра"
TEXT_FRAME_BAD_POINTS = "неверные точки подгонки СК"
TEXT_FRAME_DEGENERATE = "точки СК вырождены"
TEXT_FRAME_RESIDUAL = "точки не совпадают с размерами СК"
TEXT_FRAME_UPSIDE_DOWN = "СК перевёрнута: ось Z вниз"


class CalibrationError(ValueError):
    """Отказ калибровки: `str(exc)` — одна из констант `TEXT_*`, без входных значений."""


@dataclass(frozen=True)
class BeltResult:
    """Результат калибровки ленты.

    Поля: `factor_mm_per_imp` — мм на импульс (положительный); `raw_factor` — целое сырое значение параметра
    (`round(factor / BELT_FACTOR_SCALE)`, не меньше 1); `direction` — индекс в `BELT_AXES` (0..3);
    `axis_dev_deg` — отклонение хода от выбранной оси, градусы (>= 0); `travel_mm` — длина хода между
    отметками, мм; `delta_enc` — разность энкодера со знаком между отметками, импульсы (не 0).
    """

    factor_mm_per_imp: float
    raw_factor: int
    direction: int
    axis_dev_deg: float
    travel_mm: float
    delta_enc: int


def belt_from_marks(
    p1: tuple[float, float],
    enc1: int,
    p2: tuple[float, float],
    enc2: int,
    *,
    min_travel_mm: float = MIN_TRAVEL_MM,
    max_axis_dev_deg: float = MAX_AXIS_DEV_DEG,
) -> BeltResult:
    """Коэффициент и направление ленты по двум отметкам.

    Pre: `p1`, `p2` — (x, y) в мм в базе робота; `enc1`, `enc2` — показания 32-битного энкодера со знаком
    (целые); отметки сняты на одной детали, лента двигалась между ними.
    Post: `BeltResult` (поля — в его докстроке); `factor_mm_per_imp` и `raw_factor` положительны;
    все числа — `float`/`int` Python.
    Raises: `CalibrationError` с текстом
        `TEXT_BELT_BAD_MARKS` — координата не конечна;
        `TEXT_BELT_NO_ENCODER` — энкодер не изменился между отметками;
        `TEXT_BELT_SHORT` — ход между отметками меньше `min_travel_mm`;
        `TEXT_BELT_OFF_AXIS` — отклонение от оси больше `max_axis_dev_deg`;
        `TEXT_BELT_FACTOR_RANGE` — `raw_factor` меньше 1.
    Верхнюю границу `raw_factor` по диапазону параметра проверяет вызывающий.

    Алгоритм (T5.4m, 2a). Порядок проверок закреплён:
    1. Координаты не конечны -> BAD_MARKS.
    2. Разность энкодера по модулю 2**32 приводится к диапазону 32-битного знакового; 0 -> NO_ENCODER.
       Так переход через границу даёт малую разность, а убывание энкодера - отрицательную.
    3. Ход `d = p2 - p1`, `travel = hypot(d)`; `travel < min_travel_mm` -> SHORT.
    4. Единичный вектор движения детали при РОСТЕ энкодера - `d / travel`, умноженный на знак разности
       (лента назад при росте энкодера даёт обратную ось). Ось - с наибольшим скалярным произведением по
       `BELT_AXES`; отклонение - арккосинус этого произведения (зажатого в [-1, 1]), градусы;
       больше `max_axis_dev_deg` -> OFF_AXIS.
    5. Коэффициент - проекция хода на выбранную ось, делённая на модуль разности: прошивка ведёт деталь только
       вдоль оси, поперечная ошибка `travel * sin(отклонение)` неустранима и ограничена п. 4.
       `raw_factor = round(factor / BELT_FACTOR_SCALE)`; меньше 1 -> FACTOR_RANGE.
    """
    try:
        coords = (float(p1[0]), float(p1[1]), float(p2[0]), float(p2[1]))
    except (TypeError, ValueError, IndexError) as exc:
        raise CalibrationError(TEXT_BELT_BAD_MARKS) from exc
    if not all(math.isfinite(v) for v in coords):
        raise CalibrationError(TEXT_BELT_BAD_MARKS)

    delta = ((int(enc2) - int(enc1) + 2**31) % 2**32) - 2**31
    if delta == 0:
        raise CalibrationError(TEXT_BELT_NO_ENCODER)

    dx, dy = coords[2] - coords[0], coords[3] - coords[1]
    travel = math.hypot(dx, dy)
    if travel < min_travel_mm:
        raise CalibrationError(TEXT_BELT_SHORT)

    sign = 1.0 if delta > 0 else -1.0
    ux, uy = sign * dx / travel, sign * dy / travel
    dots = [ux * ax + uy * ay for ax, ay in BELT_AXES]
    axis = max(range(len(BELT_AXES)), key=dots.__getitem__)
    axis_dev_deg = math.degrees(math.acos(max(-1.0, min(1.0, dots[axis]))))
    if axis_dev_deg > max_axis_dev_deg:
        raise CalibrationError(TEXT_BELT_OFF_AXIS)

    ax, ay = BELT_AXES[axis]
    factor = abs(dx * ax + dy * ay) / abs(delta)
    raw_factor = round(factor / BELT_FACTOR_SCALE)
    if raw_factor < 1:
        raise CalibrationError(TEXT_BELT_FACTOR_RANGE)
    return BeltResult(
        factor_mm_per_imp=float(factor),
        raw_factor=int(raw_factor),
        direction=int(axis),
        axis_dev_deg=float(axis_dev_deg),
        travel_mm=float(travel),
        delta_enc=int(delta),
    )
