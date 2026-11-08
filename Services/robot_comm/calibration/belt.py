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
    """
    raise NotImplementedError
