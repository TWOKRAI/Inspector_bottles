"""Геометрия линейной калибровки px -> мм робота (билинейная интерполяция).

Чистые функции без side-effect — легко юнит-тестировать.

Формула:
    Дано 4 угла ROI в координатах робота (мм):
        TL = угол px(0, 0),  TR = угол px(W, 0),
        BL = угол px(0, H),  BR = угол px(W, H).

    Нормируем пиксельные координаты:
        u = px / src_w   (горизонталь, 0..1 внутри ROI, экстраполяция допустима)
        v = py / src_h   (вертикаль)

    Билинейная интерполяция:
        top = lerp(TL, TR, u)      — верхняя грань
        bot = lerp(BL, BR, u)      — нижняя грань
        out = lerp(top, bot, v)    — итоговая точка

    lerp(a, b, t) = a + t * (b - a) = a * (1 - t) + b * t
"""

from __future__ import annotations


def bilinear_px_to_mm(
    px: float,
    py: float,
    src_w: int,
    src_h: int,
    tl: tuple[float, float],
    tr: tuple[float, float],
    br: tuple[float, float],
    bl: tuple[float, float],
) -> tuple[float, float]:
    """Билинейная интерполяция пиксельной координаты в мм робота.

    Параметры
    ---------
    px, py : float
        Координаты точки в пикселях ROI (локальные, после roi_crop).
    src_w, src_h : int
        Размер ROI в пикселях (ширина, высота).  Guard: ``max(1, ...)``
        применяется здесь, чтобы избежать деления на 0.
    tl, tr, br, bl : tuple[float, float]
        Углы ROI в координатах робота (мм).
        TL = px(0,0), TR = px(W,0), BR = px(W,H), BL = px(0,H).

    Возвращает
    ----------
    (x_mm, y_mm) : tuple[float, float]
        Координаты в мм робота.

    Примечание
    ----------
    Экстраполяция допустима — u/v не клампятся.  Если точка за пределами ROI,
    результат — линейная экстраполяция (физически разумно для малых отклонений).
    """
    w = max(1, src_w)
    h = max(1, src_h)

    u = px / w  # нормировка по горизонтали
    v = py / h  # нормировка по вертикали

    # Верхняя грань: lerp(TL, TR, u)
    top_x = tl[0] + u * (tr[0] - tl[0])
    top_y = tl[1] + u * (tr[1] - tl[1])

    # Нижняя грань: lerp(BL, BR, u)
    bot_x = bl[0] + u * (br[0] - bl[0])
    bot_y = bl[1] + u * (br[1] - bl[1])

    # Итог: lerp(top, bot, v)
    x_mm = top_x + v * (bot_x - top_x)
    y_mm = top_y + v * (bot_y - top_y)

    return (x_mm, y_mm)
