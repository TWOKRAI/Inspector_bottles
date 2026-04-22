"""
Формат буфера SharedMemory для изображений.

Структура:
  [4 bytes: num_images (uint32)]
  [per-image: 12 bytes (h,w,c uint32) + 1 byte (dtype char) + payload + padding]

Padding: каждый слот изображения имеет фиксированный размер max_h*max_w*max_c*itemsize
для быстрого доступа по индексу.

Режимы pack/unpack:
  - pack_images_legacy / unpack_images(copy=True): через tobytes() и .copy() — безопасно,
    совместимо, ~2× медленнее при записи, ~1× при чтении.
  - pack_images_fast / unpack_images(copy=False): np.copyto и view — без лишних копий,
    ~2× быстрее запись, ~2× быстрее чтение. copy=False: возвращает view, данные живут
    до следующей записи в слот — использовать сразу.
"""

import struct
from typing import Any, List

import numpy as np

# Размер заголовка: количество изображений (uint32)
HEADER_SIZE = 4
# Размер заголовка одного изображения: h, w, c (3x uint32) + dtype (1 byte)
IMAGE_HEADER_SIZE = 12 + 1

# Буфер нулей для padding (избегаем b"\x00"*N при больших N)
_PADDING_CHUNK_SIZE = 65536
_PADDING_CHUNK = b"\x00" * _PADDING_CHUNK_SIZE


def calculate_buffer_size(
    num_images: int, image_shape: tuple, dtype: Any
) -> int:
    """
    Вычислить размер буфера для блока изображений.

    Args:
        num_images: максимальное количество изображений
        image_shape: (h, w, c) — максимальные размеры
        dtype: numpy dtype (например np.uint8)

    Returns:
        Размер в байтах
    """
    h, w, c = image_shape
    itemsize = np.dtype(dtype).itemsize
    return HEADER_SIZE + num_images * (IMAGE_HEADER_SIZE + h * w * c * itemsize)


def pack_images_legacy(
    buffer: memoryview,
    images: List[np.ndarray],
    max_shape: tuple,
    expected_dtype: np.dtype,
) -> None:
    """
    Записать изображения в буфер (legacy: tobytes).

    Совместимый режим: ndarray → bytes → buffer. ~2× медленнее pack_images_fast.
    """
    max_h, max_w, max_c = max_shape
    buffer[0:HEADER_SIZE] = struct.pack("I", len(images))
    offset = HEADER_SIZE
    for img in images:
        if img.dtype != expected_dtype:
            raise ValueError(f"dtype mismatch: {img.dtype} != {expected_dtype}")
        h, w = img.shape[:2]
        c = 1 if img.ndim == 2 else img.shape[2]
        if h > max_h or w > max_w or c > max_c:
            raise ValueError(
                f"Image shape ({h}x{w}x{c}) exceeds max ({max_h}x{max_w}x{max_c})"
            )
        buffer[offset : offset + 12] = struct.pack("III", h, w, c)
        offset += 12
        buffer[offset] = ord(img.dtype.char)
        offset += 1
        img_bytes = img.tobytes()
        buffer[offset : offset + len(img_bytes)] = img_bytes
        offset += len(img_bytes)
        padding = max_h * max_w * max_c * img.dtype.itemsize - len(img_bytes)
        if padding > 0:
            _write_padding(buffer, offset, padding)
            offset += padding


def _write_padding(buffer: memoryview, offset: int, size: int) -> None:
    """Записать нули в buffer[offset:offset+size] без большой аллокации."""
    pos = offset
    remaining = size
    while remaining > 0:
        chunk = min(remaining, _PADDING_CHUNK_SIZE)
        buffer[pos : pos + chunk] = _PADDING_CHUNK[:chunk]
        pos += chunk
        remaining -= chunk


def pack_images_fast(
    buffer: memoryview,
    images: List[np.ndarray],
    max_shape: tuple,
    expected_dtype: np.dtype,
) -> None:
    """
    Записать изображения в буфер (fast: np.copyto).

    Прямое копирование ndarray → buffer без tobytes. ~2× быстрее legacy.
    Padding не записывается (слот перезаписывается при следующей записи).
    """
    max_h, max_w, max_c = max_shape
    itemsize = np.dtype(expected_dtype).itemsize
    slot_size = max_h * max_w * max_c * itemsize

    buffer[0:HEADER_SIZE] = struct.pack("I", len(images))
    offset = HEADER_SIZE
    for img in images:
        if img.dtype != expected_dtype:
            raise ValueError(f"dtype mismatch: {img.dtype} != {expected_dtype}")
        h, w = img.shape[:2]
        c = 1 if img.ndim == 2 else img.shape[2]
        if h > max_h or w > max_w or c > max_c:
            raise ValueError(
                f"Image shape ({h}x{w}x{c}) exceeds max ({max_h}x{max_w}x{max_c})"
            )
        buffer[offset : offset + 12] = struct.pack("III", h, w, c)
        offset += 12
        buffer[offset] = ord(img.dtype.char)
        offset += 1
        dest = np.ndarray(
            (h, w, c), dtype=img.dtype, buffer=buffer, offset=offset
        )
        np.copyto(dest, img)
        offset += slot_size


def pack_images(
    buffer: memoryview,
    images: List[np.ndarray],
    max_shape: tuple,
    expected_dtype: np.dtype,
    *,
    fast: bool = True,
) -> None:
    """
    Записать изображения в буфер.

    Args:
        fast: True — pack_images_fast (по умолчанию), False — pack_images_legacy
    """
    if fast:
        pack_images_fast(buffer, images, max_shape, expected_dtype)
    else:
        pack_images_legacy(buffer, images, max_shape, expected_dtype)


def unpack_images(
    buffer: memoryview,
    max_shape: tuple,
    expected_dtype: np.dtype,
    n: int = -1,
    *,
    copy: bool = True,
) -> List[np.ndarray]:
    """
    Прочитать изображения из буфера.

    Args:
        buffer: memoryview буфера SharedMemory
        max_shape: (max_h, max_w, max_c)
        expected_dtype: ожидаемый dtype
        n: максимум изображений для чтения (-1 = все)
        copy: True — вернуть копии (безопасно, данные живут после записи).
              False — вернуть view (быстрее, данные валидны до следующей записи в слот).

    Returns:
        Список numpy массивов
    """
    max_h, max_w, max_c = max_shape
    itemsize = np.dtype(expected_dtype).itemsize
    slot_size = max_h * max_w * max_c * itemsize

    num_images = struct.unpack("I", buffer[0:HEADER_SIZE])[0]
    if num_images == 0:
        return []
    if n != -1:
        num_images = min(n, num_images)

    offset = HEADER_SIZE
    images = []
    for _ in range(num_images):
        h, w, c = struct.unpack("III", buffer[offset : offset + 12])
        offset += 12
        dtype_char = chr(buffer[offset])
        dtype = np.dtype(dtype_char)
        offset += 1
        arr = np.frombuffer(buffer, dtype=dtype, count=h * w * c, offset=offset)
        reshaped = arr.reshape((h, w, c))
        images.append(reshaped.copy() if copy else reshaped)
        offset += slot_size

    return images
