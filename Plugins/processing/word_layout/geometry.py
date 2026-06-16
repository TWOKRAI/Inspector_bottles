"""Чистая геометрия раскладки слова (без I/O, без фреймворка — легко тестируется).

Слово раскладывается в ОДНУ линию между центрами первого и последнего диска.
Пробел между словами занимает ``gap_slots`` пустых ячеек той же линии, чтобы
буквы соседних слов не слипались. Угол доворота считается из угла, который дала
нейросеть, с калибровкой нуля и знака (ось робота ↔ ось модели).
"""

from __future__ import annotations

import math

# Тип точки на столе робота (мм).
Point = tuple[float, float]


def wrap180(deg: float) -> float:
    """Привести угол к диапазону (−180, 180] — кратчайший доворот.

    Пример: 270° → −90°, −180° → 180°, 540° → 180°.
    """
    d = (float(deg) + 180.0) % 360.0 - 180.0
    # %360 даёт [−180, 180): −180 включён, +180 исключён. Нормируем к (−180, 180].
    return 180.0 if d == -180.0 else d


def parse_word(text: str, gap_slots: int = 1) -> list[str | None]:
    """Разобрать слово/слова в ячейки линии: буква (UPPER) или ``None`` (пробел-зазор).

    Несколько слов разделяются ``gap_slots`` пустыми ячейками. Лишние пробелы
    схлопываются, регистр приводится к верхнему (лейблы модели — заглавные кириллицы).

    ``"кот пёс"`` при gap_slots=1 → ``['К','О','Т', None, 'П','Ё','С']``.
    """
    words = str(text).upper().split()
    cells: list[str | None] = []
    for wi, w in enumerate(words):
        if wi > 0:
            cells.extend([None] * max(0, int(gap_slots)))
        cells.extend(list(w))
    return cells


def slot_positions(first: Point, last: Point, cells: list[str | None]) -> list[Point]:
    """Позиции (x_mm, y_mm) для БУКВ-ячеек — равномерно между first и last.

    Интерполяция идёт по ВСЕМ ячейкам (буквы + зазоры), позиции возвращаются только
    для непустых (буквенных) ячеек в порядке слова. Один диск (n=1) → ``first``.
    """
    n = len(cells)
    if n == 0:
        return []
    fx, fy = float(first[0]), float(first[1])
    lx, ly = float(last[0]), float(last[1])
    out: list[Point] = []
    for i, c in enumerate(cells):
        if c is None:
            continue
        t = 0.0 if n == 1 else i / (n - 1)
        out.append((fx + t * (lx - fx), fy + t * (ly - fy)))
    return out


def pitch_positions(
    first: Point,
    line_angle_deg: float,
    pitch: float,
    cells: list[str | None],
) -> list[Point]:
    """Позиции букв от ПЕРВОГО диска по направлению + фиксированному шагу.

    В отличие от slot_positions (между first и last), здесь линия задаётся первым
    диском, углом направления и шагом между центрами — слово любой длины ложится с
    ОДНИМ шагом (диски не сжимаются). ``line_angle_deg``: 0 = вдоль +X, 90 = вдоль +Y
    (X постоянный, Y растёт). Зазор-ячейки (``None``) тоже занимают шаг (пустота = диск).
    """
    th = math.radians(float(line_angle_deg))
    dx, dy = float(pitch) * math.cos(th), float(pitch) * math.sin(th)
    fx, fy = float(first[0]), float(first[1])
    out: list[Point] = []
    for i, c in enumerate(cells):
        if c is None:
            continue
        out.append((fx + i * dx, fy + i * dy))
    return out


def correction_angle(
    detected_deg: float,
    angle_valid: bool,
    zero_deg: float = 0.0,
    sign: float = 1.0,
) -> float:
    """Угол доворота диска до «прямой» буквы (кратчайший, (−180, 180]).

    ``detected_deg`` — угол глифа от нейросети. ``angle_valid=False`` (полная симметрия
    буквы, напр. «О») → доворот не нужен, возвращаем 0. ``zero_deg``/``sign`` — калибровка
    нуля и направления вращения модель↔робот (подбирается на железе).
    """
    if not angle_valid:
        return 0.0
    return wrap180(float(zero_deg) - float(sign) * float(detected_deg))


def min_spacing(positions: list[Point]) -> float:
    """Минимальный зазор между соседними слотами (для проверки наложения дисков).

    Меньше 2 точек → ``inf`` (накладываться нечему).
    """
    if len(positions) < 2:
        return math.inf
    return min(math.dist(positions[i], positions[i + 1]) for i in range(len(positions) - 1))
