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
from typing import Any, Callable, List, Optional

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
    on_recover: Optional[Callable[[int], None]] = None,
) -> None:
    """
    Записать изображения в буфер.

    Args:
        fast: True — pack_images_fast (по умолчанию), False — pack_images_legacy
        seqlock: True — обернуть запись seqlock-протоколом (generation ++ до и после,
            state writing→ready). Требует, чтобы буфер был выделен с seqlock=True
            (calculate_buffer_size). См. ADR-SRM-011.
        on_recover: колбэк(gen) при обнаружении НЕЧЁТНОГО generation на входе —
            прошлый writer не довёл запись (исключение / kill -9). Запись всё равно
            выполняется, generation восстанавливается; колбэк — для throttled WARNING
            через фасад (примитив сам не логирует).

    **Инвариант single-writer-per-slot (M4, ADR-SRM-011):** seqlock защищает reader
    от writer'а, НО НЕ двух writer'ов одного слота (оба стартуют с gen=N, оба
    финишируют gen=N+2 → reader увидит g1==g2 на смешанном кадре). Один слот пишет
    РОВНО один поток/процесс (round-robin в FrameShmMiddleware это обеспечивает).
    Жёсткий enforcement (state-машина владения слотом: refcount/release) — G.5
    (frame-pool; нагружен только с zero-copy, решение владельца 2026-07-14). G.4 —
    только глубина кольца per-camera + QoS, БЕЗ протокола владения.

    Exception-safety (H1a): при исключении внутри записи (dtype/shape mismatch)
    generation ВСЕГДА возвращается к чётному через finally (иначе слот отравлен —
    нечёт навсегда), а num_images=0 (пустой слот по протоколу) — reader получит [].
    """
    base = _image_block_base(seqlock)

    if not seqlock:
        if fast:
            pack_images_fast(buffer, images, max_shape, expected_dtype, base=base)
        else:
            pack_images_legacy(buffer, images, max_shape, expected_dtype, base=base)
        return

    # H1b: на входе generation может быть НЕЧЁТНЫМ (прошлый writer не довёл запись —
    # исключение выше по стеку без finally в старой версии, либо kill -9). writing_gen
    # обязан быть нечётным независимо от чётности входа: чёт → +1, нечёт → +2.
    gen = read_generation(buffer)
    if gen & 1:
        if on_recover is not None:
            on_recover(gen)
        writing_gen = gen + 2
    else:
        writing_gen = gen + 1
    _write_generation(buffer, writing_gen)  # нечёт — «идёт запись»
    buffer[_STATE_OFFSET] = SLOT_STATE_WRITING

    try:
        if fast:
            pack_images_fast(buffer, images, max_shape, expected_dtype, base=base)
        else:
            pack_images_legacy(buffer, images, max_shape, expected_dtype, base=base)
        buffer[_STATE_OFFSET] = SLOT_STATE_READY
    except Exception:
        # H1a: запись сорвалась — слот пуст по протоколу (num_images=0), не отравлен.
        struct.pack_into("I", buffer, base, 0)
        buffer[_STATE_OFFSET] = SLOT_STATE_FREE
        raise  # контракт: caller (write_images) ловит, логирует, возвращает None (pickle)
    finally:
        # generation ВСЕГДА → чётное (стабильно), даже при исключении.
        _write_generation(buffer, writing_gen + 1)


def clear_slot_seqlock(buffer: memoryview) -> None:
    """H1c: обнулить seqlock-слот ПО ПРОТОКОЛУ (не raw buf[:]=0 мимо generation).

    Raw-обнуление всего буфера (включая header) создаёт окно «gen 0==0 при
    недообнулённом payload» — reader проходит проверку и читает мусор. Здесь:
    generation → нечёт (writing) → num_images=0 + payload=0 → generation → чёт.
    Reader во время очистки видит нечёт → drop.
    """
    gen = read_generation(buffer)
    writing_gen = gen + 2 if (gen & 1) else gen + 1
    _write_generation(buffer, writing_gen)  # нечёт
    buffer[_STATE_OFFSET] = SLOT_STATE_WRITING
    # Обнулить всё ПОСЛЕ SLOT-header (num_images + per-image + payload); generation
    # (offset 0..4) не трогаем — им управляет протокол.
    tail = len(buffer) - SLOT_HEADER_SIZE
    if tail > 0:
        buffer[SLOT_HEADER_SIZE:] = b"\x00" * tail
    buffer[_STATE_OFFSET] = SLOT_STATE_FREE
    buffer[_REFCOUNT_OFFSET] = 0
    _write_generation(buffer, writing_gen + 1)  # чёт


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
              нечётном g1 (запись идёт), g1 != g2 (перезапись под читателем) ИЛИ
              рваном per-image-заголовке (h,w,c не атомарная тройка) — вернуть None
              (drop). Исключение (ValueError/TypeError) НЕ выходит наружу при torn:
              примитив сам ловит и сверяет generation (M1). Требует seqlock-формат.

    Returns:
        Список numpy массивов; при verify_seqlock и torn/in-progress — None.

    Raises:
        ValueError/TypeError: только при verify_seqlock и СТАБИЛЬНОМ generation —
        реальная порча слота (не гонка); caller логирует через фасад.
    """
    base = _image_block_base(verify_seqlock)

    if not verify_seqlock:
        return _read_image_block(buffer, base, max_shape, expected_dtype, n, copy)

    gen_before = read_generation(buffer)
    if gen_before & 1:
        # Нечётное — writer в процессе записи. Дроп без копии.
        return None
    try:
        images = _read_image_block(buffer, base, max_shape, expected_dtype, n, copy)
    except (ValueError, TypeError, struct.error):
        # Рваный заголовок мог быть результатом гонки — сверить generation.
        if read_generation(buffer) != gen_before:
            return None  # torn (writer сменил размеры под читателем)
        raise  # generation стабилен → реальная порча слота (caller логирует)

    # Сверка generation ПОСЛЕ чтения — даже для пустого слота (M1: без шортката).
    if read_generation(buffer) != gen_before:
        return None  # перезапись во время копии → torn
    return images


def _read_image_block(
    buffer: memoryview,
    base: int,
    max_shape: tuple,
    expected_dtype: np.dtype,
    n: int,
    copy: bool,
) -> List[np.ndarray]:
    """Прочитать блок изображений с ``base`` (num_images + per-image). Без seqlock-логики."""
    max_h, max_w, max_c = max_shape
    itemsize = np.dtype(expected_dtype).itemsize
    slot_size = max_h * max_w * max_c * itemsize

    num_images = struct.unpack_from("I", buffer, base)[0]
    if num_images == 0:
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

    return images


def read_single_frame(buffer: memoryview, *, verify_seqlock: bool = False, copy: bool = True) -> Optional[np.ndarray]:
    """Прочитать ОДИН кадр из буфера, читая h/w/c из заголовка (без max_shape).

    Для cross-process raw-чтения (FrameShmMiddleware): consumer открывает чужой
    сегмент и не знает max_shape слота — берёт фактические размеры из per-image
    заголовка. Знает про SLOT-header (base offset при seqlock) и сверяет generation
    при ``verify_seqlock`` (ADR-SRM-011).

    Args:
        copy: True (дефолт) — вернуть КОПИЮ (безопасно, данные живут вечно). False
            (Ф7 G.5.b, zero-copy) — вернуть VIEW в ``buffer`` (форма по per-image
            заголовку h·w·c, переменная форма grayscale/resize/crop сохранена). View
            жив, ПОКА жив backing-mmap (у вызывающего — только при живом handle-кэше)
            И слот не перезаписан (post-use re-check поколения — обязанность
            вызывающего, G.5.c). При ``verify_seqlock`` read-moment torn ловится здесь
            (→ None); удержание view после возврата НЕ покрыто этой функцией.

    Returns:
        ndarray (копия при copy=True, иначе view) или None — пустой слот / torn /
        write-in-progress.

    Raises:
        ValueError/TypeError: только при verify_seqlock и СТАБИЛЬНОМ generation —
        реальная порча слота (не гонка). При torn примитив сам ловит → None (M1).
    """
    base = _image_block_base(verify_seqlock)

    if not verify_seqlock:
        return _read_one_frame(buffer, base, copy=copy)

    gen_before = read_generation(buffer)
    if gen_before & 1:
        return None  # запись идёт
    try:
        frame = _read_one_frame(buffer, base, copy=copy)
    except (ValueError, TypeError, struct.error):
        if read_generation(buffer) != gen_before:
            return None  # torn (рваный заголовок из-за гонки)
        raise  # generation стабилен → реальная порча (caller логирует через фасад)

    if read_generation(buffer) != gen_before:
        return None  # перезапись под читателем → torn, дроп
    return frame


def _read_one_frame(buffer: memoryview, base: int, *, copy: bool = True) -> Optional[np.ndarray]:
    """Прочитать ОДИН кадр с ``base`` (h/w/c из header). None при num_images==0. Без seqlock.

    ``copy=False`` → view в ``buffer`` (zero-copy, Ф7 G.5.b): форма (h,w,c) берётся из
    per-image заголовка, поэтому view сам по себе корректен для меньшего кадра
    (grayscale/resize/crop) — не тянет padding/хвост слота.
    """
    num_images = struct.unpack_from("I", buffer, base)[0]
    if num_images == 0:
        return None
    offset = base + HEADER_SIZE
    h, w, c = struct.unpack_from("III", buffer, offset)
    offset += 12
    dtype = np.dtype(chr(buffer[offset]))
    offset += 1
    arr = np.frombuffer(buffer, dtype=dtype, count=h * w * c, offset=offset)
    reshaped = arr.reshape((h, w, c))
    return reshaped.copy() if copy else reshaped
