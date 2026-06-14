"""Вырез диска из РЕАЛЬНОГО фото в RGBA-эталон (формат каталога классов).

Назначение: превратить реальные снимки буквы на белом диске (как кадр
инспекции) в эталоны того же вида, что даёт tools/make_ru_letter_sprites
(белый диск + тёмная буква, вне диска прозрачно). Дальше — штатный движок
dataset_gen: поворот на GT-угол, композиция на фон, аугментации, экспорт.

Зачем именно так: реальные снимки дают настоящую фактуру буквы и диска
(блики, износ, неравномерность), а движок добавляет геометрию и фотометрию.
Несколько снимков одного класса (например под 0/90/180/270°), приведённых
к вертикали, становятся равноправными эталонами-вариантами — движок берёт
случайный и крутит на нужный угол.

Чистые функции (тестируемость): детекция круга, вырез в RGBA, приведение
к вертикали. I/O — на стороне инструмента (tools/cut_real_disks.py).
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Каноничные углы съёмки, приводимые к вертикали без интерполяции (кратны 90°).
# Угол в имени файла = поворот буквы CCW (как метка); привести к 0° = повернуть
# на -base, поэтому 90° CCW отменяется поворотом CW и наоборот.
_LOSSLESS_ROTATIONS = {
    90: cv2.ROTATE_90_CLOCKWISE,  # отменить +90° CCW → повернуть на -90° (CW)
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,  # отменить +270° CCW (= -90°) → повернуть на +90° (CCW)
}


def _detect_white_disk(gray: np.ndarray, min_side: int) -> tuple[int, int, int] | None:
    """Фолбэк-детекция: яркий диск через Otsu + minEnclosingCircle крупнейшего контура.

    Работает там, где Hough не сходится (белый диск vs тёмно-синий фон даёт
    чистую бинаризацию). None, если правдоподобного круга нет.
    """
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    (x, y), r = cv2.minEnclosingCircle(max(contours, key=cv2.contourArea))
    if not (0.1 * min_side <= r <= 0.95 * min_side):
        return None
    return int(round(x)), int(round(y)), int(round(r))


def detect_disk(bgr: np.ndarray) -> tuple[int, int, int]:
    """Найти диск (cx, cy, r): HoughCircles → бинаризация → вписанный круг.

    param2 ослабляется в цикле (устойчивость к контрастности); диапазон радиусов
    умеренный (0.18–0.66 min_side, точность). Диски вне диапазона / при провале
    Hough ловит бинаризация-фолбэк (_detect_white_disk). Из найденных берётся
    самый крупный круг (диск крупнее буквы и бликов). Если ни Hough, ни
    бинаризация не сошлись — ВИДИМЫЙ warning (фолбэк по центру кадра легко
    принять за настоящую детекцию и молча испортить эталон).

    Pre:
      - bgr: HxWx3 uint8 (как из cv2.imdecode)
    Post:
      - 0 < r ≤ min(H, W) / 2; центр (cx, cy) внутри кадра
    """
    h, w = bgr.shape[:2]
    min_side = min(h, w)
    gray = cv2.medianBlur(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), 5)
    for param2 in (60, 45, 35, 25, 18):
        circles = cv2.HoughCircles(
            gray,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=float(min_side),
            param1=120,
            param2=param2,
            minRadius=int(0.18 * min_side),
            maxRadius=int(0.66 * min_side),
        )
        if circles is not None:
            best = max(np.round(circles[0]).astype(int), key=lambda c: c[2])
            return int(best[0]), int(best[1]), int(best[2])
    fallback = _detect_white_disk(gray, min_side)
    if fallback is not None:
        return fallback
    logger.warning(
        "detect_disk: круг НЕ найден (Hough+бинаризация) — фолбэк на вписанный круг по центру "
        "(%dx%d). Эталон может быть испорчен: проверьте контраст диск/фон.",
        w,
        h,
    )
    return w // 2, h // 2, int(0.48 * min_side)


def cut_disk_rgba(rgb: np.ndarray, circle: tuple[int, int, int], feather: float = 2.0) -> np.ndarray:
    """Вырезать диск в квадратный RGBA-эталон (вне круга — прозрачно).

    Диск центрируется в квадрате 2r×2r. Если круг подрезан краем кадра,
    недостающая зона остаётся ПРОЗРАЧНОЙ (а не чёрной) — туда «просветит»
    подставляемый движком фон.

    Pre:
      - rgb: HxWx3 uint8 (RGB-порядок); circle = (cx, cy, r), r > 0
    Post:
      - RGBA 2r×2r uint8 (RGB-порядок каналов, как у PIL); углы прозрачны
    """
    cx, cy, r = circle
    side = 2 * r
    h, w = rgb.shape[:2]

    sprite = np.zeros((side, side, 3), dtype=np.uint8)
    coverage = np.zeros((side, side), dtype=np.uint8)

    dx0, dy0 = max(0, r - cx), max(0, r - cy)  # старт в спрайте
    sx0, sy0 = max(0, cx - r), max(0, cy - r)  # старт в источнике
    cw = min(side - dx0, w - sx0)
    ch = min(side - dy0, h - sy0)
    if cw > 0 and ch > 0:
        sprite[dy0 : dy0 + ch, dx0 : dx0 + cw] = rgb[sy0 : sy0 + ch, sx0 : sx0 + cw]
        coverage[dy0 : dy0 + ch, dx0 : dx0 + cw] = 255

    mask = np.zeros((side, side), dtype=np.uint8)
    cv2.circle(mask, (r, r), r, 255, thickness=-1)
    if feather > 0:
        mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=float(feather))
    alpha = cv2.bitwise_and(mask, coverage)

    return np.dstack([sprite, alpha])


def rotate_upright(rgba: np.ndarray, base_deg: int) -> np.ndarray:
    """Привести эталон к вертикали (поворот на -base_deg).

    base_deg — ориентация буквы на снимке (CCW, градусы). Для каноничных
    0/90/180/270° поворот без интерполяции (cv2.ROTATE_*); иначе — аффинный
    поворот с сохранением размера квадрата.

    Pre:
      - rgba: квадрат S×S×4 uint8; 0 ≤ base_deg < 360
    Post:
      - RGBA того же размера, буква приведена к 0°
    """
    base = base_deg % 360
    if base == 0:
        return rgba
    code = _LOSSLESS_ROTATIONS.get(base)
    if code is not None:
        return cv2.rotate(rgba, code)
    # неканоничный угол — аффинный поворот вокруг центра (редкий случай)
    s = rgba.shape[0]
    matrix = cv2.getRotationMatrix2D((s / 2.0, s / 2.0), -base, 1.0)
    return cv2.warpAffine(rgba, matrix, (s, s), flags=cv2.INTER_CUBIC, borderValue=(0, 0, 0, 0))
