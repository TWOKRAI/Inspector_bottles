"""Симметрия классов: авто-детектор и кодирование метки угла.

Зачем: для симметричных объектов разные углы дают одинаковую картинку —
без приведения метки обучение регрессии угла не сойдётся. Симметрия —
вычисляемое свойство класса (по эталону), не хардкод; конфиг допускает
ручное переопределение (SymmetryConfig.overrides).

Кодирование угла по типу симметрии:
  none — (sin θ, cos θ), полный диапазон 0–360°;
  180  — (sin 2θ, cos 2θ): θ и θ+180° дают одинаковую метку;
  full — угол не определён, флаг angle_valid=False (класс исключается
         из loss по углу обучающим кодом).
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from Services.dataset_gen.core.config import SymmetryType

_DEFAULT_FULL_ANGLES = (30.0, 45.0, 60.0, 90.0, 120.0, 135.0)


def _pad_rotation_safe(sprite_rgba: np.ndarray) -> tuple[np.ndarray, tuple[float, float]]:
    """Допейстить спрайт в квадрат со стороной ≥ диагонали — поворот не обрежет контент.

    Возвращает (холст, центр спрайта в пиксельных координатах). Центр считается
    в конвенции «центр пикселя i = координата i»: (x0 + (w-1)/2, y0 + (h-1)/2).
    Брать side/2 нельзя — для чётных размеров это даёт сдвиг на целый пиксель
    при повороте на 180° и ложные «несимметрии» у симметричных объектов.
    """
    h, w = sprite_rgba.shape[:2]
    side = int(math.ceil(math.hypot(h, w))) + 2
    out = np.zeros((side, side, 4), dtype=np.uint8)
    y0, x0 = (side - h) // 2, (side - w) // 2
    out[y0 : y0 + h, x0 : x0 + w] = sprite_rgba
    center = (x0 + (w - 1) / 2.0, y0 + (h - 1) / 2.0)
    return out, center


def rotation_difference(sprite_rgba: np.ndarray, angle_deg: float) -> float:
    """Нормированная [0..1] разность спрайта и его поворота на angle_deg.

    Сравнение — в пределах непрозрачной области (объединение альфа-масок):
    premultiplied-RGB разность + разность альфы, нормировано на площадь
    объединения. 0 — идеальное совпадение, ~1 — полное несовпадение.

    Pre:
      - sprite_rgba: HxWx4 uint8
    Post:
      - 0.0 <= результат <= 1.0
    """
    base, center = _pad_rotation_safe(sprite_rgba)
    side = base.shape[0]
    m = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    rotated = cv2.warpAffine(
        base,
        m,
        (side, side),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )

    a1 = base[:, :, 3].astype(np.float32) / 255.0
    a2 = rotated[:, :, 3].astype(np.float32) / 255.0
    union = np.maximum(a1, a2)
    area = float(union.sum())
    if area < 1.0:
        return 0.0

    p1 = base[:, :, :3].astype(np.float32) * a1[:, :, None]
    p2 = rotated[:, :, :3].astype(np.float32) * a2[:, :, None]
    color_diff = np.abs(p1 - p2).mean(axis=2)
    alpha_diff = np.abs(a1 - a2) * 255.0
    total = float((0.5 * color_diff + 0.5 * alpha_diff).sum())
    return min(1.0, total / (area * 255.0))


def detect_symmetry(
    sprite_rgba: np.ndarray,
    threshold: float = 0.05,
    full_angles: tuple[float, ...] = _DEFAULT_FULL_ANGLES,
    rel_threshold: float = 0.3,
) -> SymmetryType:
    """Определить тип вращательной симметрии эталона.

    Два критерия:
      full — разность мала (< threshold, абсолют) на 180° И на всей серии
             full_angles;
      180  — разность на 180° мала и абсолютно (< threshold), и ОТНОСИТЕЛЬНО
             типичной разности объекта на контрольных углах
             (< rel_threshold * median(diff по full_angles)).

    Относительный критерий нужен для объектов с большой ротационно-инвариантной
    областью (буква на диске, деталь на шайбе): инвариантный фон «разбавляет»
    абсолютную метрику, и слабо-несимметричный объект ложно проходит порог.

    Pre:
      - sprite_rgba: HxWx4 uint8; 0 < threshold < 1; rel_threshold > 0
    Post:
      - результат ∈ {"none", "180", "full"}
    """
    d180 = rotation_difference(sprite_rgba, 180.0)
    if d180 >= threshold:
        return "none"
    probes = [rotation_difference(sprite_rgba, a) for a in full_angles]
    if all(p < threshold for p in probes):
        return "full"
    scale = float(np.median(probes))
    if d180 < rel_threshold * scale:
        return "180"
    return "none"


def combine_symmetries(kinds: set[SymmetryType]) -> SymmetryType:
    """Свести симметрии нескольких эталонов класса к худшей (минимальной).

    Класс симметричен лишь настолько, насколько симметричен его наименее
    симметричный эталон: any none → none; иначе any 180 → 180; иначе full.
    """
    if "none" in kinds:
        return "none"
    if "180" in kinds:
        return "180"
    return "full"


def encode_angle(angle_deg: float, symmetry: SymmetryType) -> tuple[float, float, bool]:
    """Закодировать угол в (sin, cos, angle_valid) с учётом симметрии.

    Pre:
      - symmetry ∈ {"none", "180", "full"}
    Post:
      - none/180: sin²+cos² == 1 (±eps), angle_valid=True;
        для 180: encode(θ) == encode(θ+180°)
      - full: (0.0, 0.0, False) — метка угла игнорируется в loss
    """
    if symmetry == "full":
        return 0.0, 0.0, False
    factor = 2.0 if symmetry == "180" else 1.0
    rad = math.radians(angle_deg * factor)
    return math.sin(rad), math.cos(rad), True
