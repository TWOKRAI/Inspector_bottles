"""
Формат буфера SharedMemory для изображений.

Структура (seqlock=False, legacy — дефолт):
  [4 bytes: num_images (uint32)]
  [per-image: 12 bytes (h,w,c uint32) + 1 byte (dtype char) + payload + padding]

Структура (seqlock=True, Ф7 G.3(b), ADR-SRM-011) — перед блоком изображений
добавлен фиксированный 8-байтовый SLOT-header (little-endian):
  [offset 0 : generation uint32]  seqlock: нечётное = запись идёт, чётное = стабильно
  [offset 4 : state      uint8 ]  0=free 1=writing 2=ready 3=reading (lifecycle пула G.4)
  [offset 5 : refcount   uint8 ]  fan-out: читателей держат слот (G.4)
  [offset 6 : reserved   uint16]  выравнивание / будущие флаги
  [offset 8 : num_images uint32]  далее — тот же блок изображений, что и в legacy
  ...

Один формат сразу под будущий frame-pool (G.4 не переопределяет — state/refcount уже здесь).

Padding: каждый слот изображения имеет фиксированный размер max_h*max_w*max_c*itemsize
для быстрого доступа по индексу.

Режимы pack/unpack:
  - pack_images_legacy / unpack_images(copy=True): через tobytes() и .copy() — безопасно,
    совместимо, ~2× медленнее при записи, ~1× при чтении.
  - pack_images_fast / unpack_images(copy=False): np.copyto и view — без лишних копий,
    ~2× быстрее запись, ~2× быстрее чтение. copy=False: возвращает view, данные живут
    до следующей записи в слот — использовать сразу.

Seqlock (verify_seqlock=True при чтении): reader сверяет generation до/после копии;
при нечётном g1 (запись идёт) или g1 != g2 (writer перезаписал под читателем) —
возвращает None (drop), НЕ порванный кадр. См. ADR-SRM-011.
"""

import struct
from typing import Any, List, Optional

import numpy as np

# Размер заголовка блока изображений: количество изображений (uint32)
HEADER_SIZE = 4
# Размер заголовка одного изображения: h, w, c (3x uint32) + dtype (1 byte)
IMAGE_HEADER_SIZE = 12 + 1

# --- SLOT-header (seqlock, Ф7 G.3(b) / ADR-SRM-011) -------------------------------
# Фиксированный префикс перед блоком изображений, когда слот в seqlock-формате.
SLOT_HEADER_SIZE = 8
_GEN_OFFSET = 0  # uint32 generation
_STATE_OFFSET = 4  # uint8  state
_REFCOUNT_OFFSET = 5  # uint8  refcount
# offset 6:8 — reserved (uint16), под будущие флаги пула/QoS

# Состояния слота (lifecycle пула G.4; сейчас используется writing/ready, free — по нулям)
SLOT_STATE_FREE = 0
SLOT_STATE_WRITING = 1
SLOT_STATE_READY = 2
SLOT_STATE_READING = 3

_UINT32_MASK = 0xFFFFFFFF

# Буфер нулей для padding (избегаем b"\x00"*N при больших N)
_PADDING_CHUNK_SIZE = 65536
_PADDING_CHUNK = b"\x00" * _PADDING_CHUNK_SIZE


def _image_block_base(seqlock: bool) -> int:
    """Смещение, с которого начинается блок изображений (num_images + per-image)."""
    return SLOT_HEADER_SIZE if seqlock else 0


# --- SLOT-header примитивы (seqlock) ---------------------------------------------


def read_generation(buffer: memoryview) -> int:
    """Прочитать generation слота (seqlock). Нечётное = запись в процессе."""
    return struct.unpack_from("<I", buffer, _GEN_OFFSET)[0]


def _write_generation(buffer: memoryview, value: int) -> None:
    struct.pack_into("<I", buffer, _GEN_OFFSET, value & _UINT32_MASK)


def read_slot_state(buffer: memoryview) -> int:
    """Прочитать state слота (free/writing/ready/reading — под пул G.4)."""
    return buffer[_STATE_OFFSET]


def write_slot_state(buffer: memoryview, state: int) -> None:
    """Записать state слота (под пул G.4)."""
    buffer[_STATE_OFFSET] = state & 0xFF


def read_refcount(buffer: memoryview) -> int:
    """Прочитать refcount слота (fan-out, под пул G.4)."""
    return buffer[_REFCOUNT_OFFSET]


def write_refcount(buffer: memoryview, value: int) -> None:
    """Записать refcount слота (fan-out, под пул G.4)."""
    buffer[_REFCOUNT_OFFSET] = value & 0xFF


def calculate_buffer_size(num_images: int, image_shape: tuple, dtype: Any, *, seqlock: bool = False) -> int:
    """
    Вычислить размер буфера для блока изображений.

    Args:
        num_images: максимальное количество изображений
        image_shape: (h, w, c) — максимальные размеры
        dtype: numpy dtype (например np.uint8)
        seqlock: True — добавить 8-байтовый SLOT-header (Ф7 G.3(b))

    Returns:
        Размер в байтах
    """
    h, w, c = image_shape
    itemsize = np.dtype(dtype).itemsize
    base = _image_block_base(seqlock)
    return base + HEADER_SIZE + num_images * (IMAGE_HEADER_SIZE + h * w * c * itemsize)


def pack_images_legacy(
    buffer: memoryview,
    images: List[np.ndarray],
    max_shape: tuple,
    expected_dtype: np.dtype,
    *,
    base: int = 0,
) -> None:
    """
    Записать изображения в буфер (legacy: tobytes).

    Совместимый режим: ndarray → bytes → buffer. ~2× медленнее pack_images_fast.
    ``base`` — смещение блока изображений (SLOT_HEADER_SIZE при seqlock, иначе 0).
    """
    max_h, max_w, max_c = max_shape
    buffer[base : base + HEADER_SIZE] = struct.pack("I", len(images))
    offset = base + HEADER_SIZE
    for img in images:
        if img.dtype != expected_dtype:
            raise ValueError(f"dtype mismatch: {img.dtype} != {expected_dtype}")
        h, w = img.shape[:2]
        c = 1 if img.ndim == 2 else img.shape[2]
        if h > max_h or w > max_w or c > max_c:
            raise ValueError(f"Image shape ({h}x{w}x{c}) exceeds max ({max_h}x{max_w}x{max_c})")
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
    *,
    base: int = 0,
) -> None:
    """
    Записать изображения в буфер (fast: np.copyto).

    Прямое копирование ndarray → buffer без tobytes. ~2× быстрее legacy.
    Padding не записывается (слот перезаписывается при следующей записи).
    ``base`` — смещение блока изображений (SLOT_HEADER_SIZE при seqlock, иначе 0).
    """
    max_h, max_w, max_c = max_shape
    itemsize = np.dtype(expected_dtype).itemsize
    slot_size = max_h * max_w * max_c * itemsize

    buffer[base : base + HEADER_SIZE] = struct.pack("I", len(images))
    offset = base + HEADER_SIZE
    for img in images:
        if img.dtype != expected_dtype:
            raise ValueError(f"dtype mismatch: {img.dtype} != {expected_dtype}")
        h, w = img.shape[:2]
        c = 1 if img.ndim == 2 else img.shape[2]
        if h > max_h or w > max_w or c > max_c:
            raise ValueError(f"Image shape ({h}x{w}x{c}) exceeds max ({max_h}x{max_w}x{max_c})")
        buffer[offset : offset + 12] = struct.pack("III", h, w, c)
        offset += 12
        buffer[offset] = ord(img.dtype.char)
        offset += 1
        dest = np.ndarray((h, w, c), dtype=img.dtype, buffer=buffer, offset=offset)
        np.copyto(dest, img)
        offset += slot_size


def pack_images(
    buffer: memoryview,
    images: List[np.ndarray],
    max_shape: tuple,
    expected_dtype: np.dtype,
    *,
    fast: bool = True,
    seqlock: bool = False,
) -> None:
    """
    Записать изображения в буфер.

    Args:
        fast: True — pack_images_fast (по умолчанию), False — pack_images_legacy
        seqlock: True — обернуть запись seqlock-протоколом (generation ++ до и после,
            state writing→ready). Требует, чтобы буфер был выделен с seqlock=True
            (calculate_buffer_size). См. ADR-SRM-011.
    """
    base = _image_block_base(seqlock)

    if seqlock:
        # Начало записи: generation → нечётное (writing). Reader, увидев нечётное или
        # изменение generation после копии, дропает кадр (не порванный).
        gen = read_generation(buffer)
        _write_generation(buffer, gen + 1)
        buffer[_STATE_OFFSET] = SLOT_STATE_WRITING

    if fast:
        pack_images_fast(buffer, images, max_shape, expected_dtype, base=base)
    else:
        pack_images_legacy(buffer, images, max_shape, expected_dtype, base=base)

    if seqlock:
        # Конец записи: generation → чётное (стабильно), state = ready.
        buffer[_STATE_OFFSET] = SLOT_STATE_READY
        _write_generation(buffer, gen + 2)


def unpack_images(
    buffer: memoryview,
    max_shape: tuple,
    expected_dtype: np.dtype,
    n: int = -1,
    *,
    copy: bool = True,
    verify_seqlock: bool = False,
) -> Optional[List[np.ndarray]]:
    """
    Прочитать изображения из буфера.

    Args:
        buffer: memoryview буфера SharedMemory
        max_shape: (max_h, max_w, max_c)
        expected_dtype: ожидаемый dtype
        n: максимум изображений для чтения (-1 = все)
        copy: True — вернуть копии (безопасно, данные живут после записи).
              False — вернуть view (быстрее, данные валидны до следующей записи в слот).
        verify_seqlock: True — сверить generation до/после чтения (Ф7 G.3(b)). При
              нечётном g1 (запись идёт) или g1 != g2 (перезапись под читателем) —
              вернуть None (drop, НЕ порванный кадр). Требует seqlock-формат буфера.

    Returns:
        Список numpy массивов; при verify_seqlock и обнаружении torn/in-progress — None.
    """
    base = _image_block_base(verify_seqlock)

    if verify_seqlock:
        gen_before = read_generation(buffer)
        if gen_before & 1:
            # Нечётное — writer в процессе записи. Дроп без копии.
            return None

    max_h, max_w, max_c = max_shape
    itemsize = np.dtype(expected_dtype).itemsize
    slot_size = max_h * max_w * max_c * itemsize

    num_images = struct.unpack_from("I", buffer, base)[0]
    if num_images == 0:
        # Пустой слот. При seqlock сверять generation не нужно (данных нет).
        return []
    if n != -1:
        num_images = min(n, num_images)

    offset = base + HEADER_SIZE
    images = []
    for _ in range(num_images):
        h, w, c = struct.unpack_from("III", buffer, offset)
        offset += 12
        dtype_char = chr(buffer[offset])
        dtype = np.dtype(dtype_char)
        offset += 1
        arr = np.frombuffer(buffer, dtype=dtype, count=h * w * c, offset=offset)
        reshaped = arr.reshape((h, w, c))
        images.append(reshaped.copy() if copy else reshaped)
        offset += slot_size

    if verify_seqlock:
        gen_after = read_generation(buffer)
        if gen_after != gen_before:
            # Writer перезаписал слот во время копии → кадр порван. Дроп.
            return None

    return images


def read_single_frame(buffer: memoryview, *, verify_seqlock: bool = False) -> Optional[np.ndarray]:
    """Прочитать ОДИН кадр из буфера, читая h/w/c из заголовка (без max_shape).

    Для cross-process raw-чтения (FrameShmMiddleware): consumer открывает чужой
    сегмент и не знает max_shape слота — берёт фактические размеры из per-image
    заголовка. Знает про SLOT-header (base offset при seqlock) и сверяет generation
    при ``verify_seqlock`` (ADR-SRM-011).

    Returns:
        ndarray (копия) или None — пустой слот / torn / write-in-progress.
    """
    base = _image_block_base(verify_seqlock)

    if verify_seqlock:
        gen_before = read_generation(buffer)
        if gen_before & 1:
            return None  # запись идёт

    num_images = struct.unpack_from("I", buffer, base)[0]
    if num_images == 0:
        return None

    offset = base + HEADER_SIZE
    h, w, c = struct.unpack_from("III", buffer, offset)
    offset += 12
    dtype = np.dtype(chr(buffer[offset]))
    offset += 1
    arr = np.frombuffer(buffer, dtype=dtype, count=h * w * c, offset=offset)
    frame = arr.reshape((h, w, c)).copy()

    if verify_seqlock:
        if read_generation(buffer) != gen_before:
            return None  # перезапись под читателем → torn, дроп
    return frame
