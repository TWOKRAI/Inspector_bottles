"""Декодирование и нормализация изображений, принятых от телефона.

- decode_image: bytes (JPEG/PNG) -> BGR ndarray с учётом EXIF-ориентации.
- letterbox:    вписать кадр в целевой размер с сохранением пропорций (поля),
                чтобы круглые объекты не превращались в эллипсы.

EXIF-ориентация парсится без сторонних зависимостей (телефоны почти всегда
пишут JPEG с тегом Orientation 0x0112; без поворота портретные фото лягут боком).
"""

from __future__ import annotations

import struct

import cv2
import numpy as np

# Лимит на размер тела загрузки (защита от случайного OOM).
MAX_UPLOAD_BYTES = 64 * 1024 * 1024  # 64 МБ


def _orientation_from_tiff(tiff: bytes) -> int:
    """Найти тег Orientation (0x0112) в TIFF-блоке EXIF. 1 (норма) если нет."""
    try:
        if tiff[:2] == b"II":
            bo = "<"  # little-endian
        elif tiff[:2] == b"MM":
            bo = ">"  # big-endian
        else:
            return 1
        (ifd_off,) = struct.unpack(bo + "I", tiff[4:8])
        (count,) = struct.unpack(bo + "H", tiff[ifd_off : ifd_off + 2])
        pos = ifd_off + 2
        for _ in range(count):
            entry = tiff[pos : pos + 12]
            if len(entry) < 12:
                break
            tag = struct.unpack(bo + "H", entry[:2])[0]
            if tag == 0x0112:
                value = struct.unpack(bo + "H", entry[8:10])[0]
                return value or 1
            pos += 12
        return 1
    except Exception:
        return 1


def exif_orientation(data: bytes) -> int:
    """Вытащить EXIF-ориентацию из JPEG-байтов. 1 если нет/не JPEG."""
    try:
        if len(data) < 4 or data[0] != 0xFF or data[1] != 0xD8:
            return 1  # не JPEG
        idx, n = 2, len(data)
        while idx + 4 <= n:
            if data[idx] != 0xFF:
                break
            marker = data[idx + 1]
            seg_len = (data[idx + 2] << 8) | data[idx + 3]
            if marker == 0xE1:  # APP1 — здесь живёт EXIF
                seg = data[idx + 4 : idx + 2 + seg_len]
                if seg[:6] == b"Exif\x00\x00":
                    return _orientation_from_tiff(seg[6:])
                return 1
            if marker == 0xDA:  # SOS — дальше пошли данные изображения
                break
            idx += 2 + seg_len
        return 1
    except Exception:
        return 1


# EXIF Orientation -> поворот cv2. Отражения (2,4,5,7) на телефонах редки —
# обрабатываем только повороты (best-effort).
_ROTATIONS = {
    3: cv2.ROTATE_180,
    6: cv2.ROTATE_90_CLOCKWISE,
    8: cv2.ROTATE_90_COUNTERCLOCKWISE,
}


def apply_exif_orientation(img: np.ndarray, orientation: int) -> np.ndarray:
    """Повернуть изображение согласно EXIF-ориентации."""
    rot = _ROTATIONS.get(orientation)
    return cv2.rotate(img, rot) if rot is not None else img


def decode_image(data: bytes) -> np.ndarray | None:
    """bytes -> BGR ndarray с EXIF-поворотом. None если декод не удался.

    ВАЖНО: cv2.imdecode (OpenCV 4.x) сам применяет EXIF-ориентацию по умолчанию.
    Чтобы не повернуть дважды (наш ручной поворот + авто-поворот cv2 = +90° мимо),
    декодируем с IMREAD_IGNORE_ORIENTATION (cv2 НЕ крутит), затем применяем поворот
    один раз по нашему парсеру — детерминированно, независимо от версии OpenCV.
    """
    if not data:
        return None
    buf = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    if img is None:
        return None
    return apply_exif_orientation(img, exif_orientation(data))


def letterbox(img: np.ndarray, target_w: int, target_h: int, pad_value: int = 0) -> np.ndarray:
    """Вписать img в (target_w, target_h) с сохранением пропорций + поля.

    Пропорции сохраняются, лишнее пространство заполняется pad_value (по умолч.
    чёрный). Так круглые объекты остаются круглыми (не растягиваются).
    """
    h, w = img.shape[:2]
    if w <= 0 or h <= 0:
        return np.full((target_h, target_w, 3), pad_value, dtype=np.uint8)
    scale = min(target_w / w, target_h / h)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(img, (new_w, new_h), interpolation=interp)
    canvas = np.full((target_h, target_w, 3), pad_value, dtype=np.uint8)
    x0 = (target_w - new_w) // 2
    y0 = (target_h - new_h) // 2
    canvas[y0 : y0 + new_h, x0 : x0 + new_w] = resized
    return canvas
