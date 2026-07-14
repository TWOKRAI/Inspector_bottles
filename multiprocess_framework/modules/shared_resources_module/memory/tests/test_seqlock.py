# -*- coding: utf-8 -*-
"""Ф7 G.3(b): seqlock на слоте SHM — репродьюсер torn-frame + верификация фикса.

GATE (правило фазы): без КРАСНОГО репродьюсера не начинать правку записи.

Сценарий: writer заливает кадр ОДНИМ значением (v), reader копирует и проверяет
однородность (``min == max``). Порванный кадр = writer перезаписал буфер под
читателем во время memcpy (numpy отпускает GIL на больших массивах) → в копии
смесь старого и нового значения → ``min != max``.

- ДО seqlock (сырой ``unpack_images``): reader ловит порванный кадр (torn > 0).
- ПОСЛЕ seqlock (``unpack_images(verify_seqlock=True)``): reader сверяет
  generation до/после копии; при расхождении — drop (None), НЕ порча → torn == 0.
"""

from __future__ import annotations

import struct
import threading
import time

import numpy as np
import pytest

from multiprocess_framework.modules.shared_resources_module.memory import format as fmt
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager
from multiprocess_framework.modules.shared_resources_module.memory.format import buffer as buf_mod


# Прод-размер кадра: 1024x1024x3 (~3 МБ) — гарантированное отпускание GIL в memcpy,
# чтобы гонка reader×writer была наблюдаема (тест-параметры не прячут окно дефекта).
# На меньшем кадре numpy может не отпустить GIL и tearing не воспроизведётся.
_SHAPE = (1024, 1024, 3)
_DTYPE = np.uint8


def _run_contention(read_fn, *, shape=_SHAPE, iters: int = 6000, seqlock: bool = False, writer_gap: float = 0.0):
    """Один writer + один reader на ОБЩИЙ буфер (bytearray, shared между threads).

    Буфер приваймлен (валиден до старта reader); threading.Barrier синхронизирует
    старт reader и writer (иначе reader успевает отработать все итерации до первой
    записи — гонка не наблюдается).

    ``writer_gap`` — пауза writer между кадрами. gap=0 (дефолт) = пат-контеншн
    (writer занимает почти всё время; для торн-репродьюсера). gap>0 моделирует
    реальную камеру с межкадровым интервалом (reader получает чистые окна).

    Returns: (torn, drops, valid) — порванных кадров, дропов (None), валидных.
    """
    size = fmt.calculate_buffer_size(1, shape, _DTYPE, seqlock=seqlock)
    buf = bytearray(size)
    mv = memoryview(buf)
    max_shape = shape
    dtype = np.dtype(_DTYPE)
    fmt.pack_images(mv, [np.full(shape, 1, dtype=_DTYPE)], max_shape, dtype, seqlock=seqlock)
    stop = threading.Event()
    barrier = threading.Barrier(2)
    writer_err: list[str] = []

    def writer() -> None:
        v = 2
        try:
            barrier.wait()
            while not stop.is_set():
                frame = np.full(shape, v, dtype=_DTYPE)
                fmt.pack_images(mv, [frame], max_shape, dtype, seqlock=seqlock)
                v = 1 + (v % 254)
                if writer_gap:
                    time.sleep(writer_gap)
        except Exception as exc:  # noqa: BLE001 — поднимем в основном потоке
            writer_err.append(repr(exc))

    torn = drops = valid = 0
    t = threading.Thread(target=writer, daemon=True)
    t.start()
    barrier.wait()
    try:
        for _ in range(iters):
            frame = read_fn(mv, max_shape, dtype)
            if frame is None:
                drops += 1
                continue
            if int(frame.min()) != int(frame.max()):
                torn += 1
            else:
                valid += 1
    finally:
        stop.set()
        t.join(timeout=3)
    assert not writer_err, f"writer упал: {writer_err}"
    return torn, drops, valid


def _raw_read(mv, max_shape, dtype):
    """Сырое чтение БЕЗ синхронизации (текущее поведение до G.3)."""
    imgs = fmt.unpack_images(mv, max_shape, dtype, n=1, copy=True)
    return imgs[0] if imgs else None


def _seqlock_read(mv, max_shape, dtype):
    """Чтение с проверкой seqlock: None при torn/in-progress (drop)."""
    imgs = fmt.unpack_images(mv, max_shape, dtype, n=1, copy=True, verify_seqlock=True)
    if imgs is None:  # torn / write-in-progress → drop
        return None
    return imgs[0] if imgs else None


def test_torn_frame_reproduced_without_seqlock():
    """РЕПРОДЬЮСЕР (GATE): без seqlock конкурентный reader ловит порванный кадр.

    Робастность против ложного зелёного: до 6 раундов, засчитываем первый же
    раунд с torn > 0 (при сильной гонке — практически всегда первый).
    """
    for _ in range(6):
        torn, _drops, valid = _run_contention(_raw_read, seqlock=False)
        if torn > 0:
            assert valid > 0, "reader должен был поймать и валидные кадры тоже"
            return
    # Ни одного порванного за 6 раундов — гонка не воспроизвелась (машина слишком
    # быстрая/GIL не отпущен). Тест-репродьюсер бесполезен → явный сигнал.
    raise AssertionError("torn-frame не воспроизвёлся за 6 раундов — усилить контеншн")


def test_no_torn_frame_with_seqlock():
    """ФИКС (безопасность): под ПАТ-контеншеном (writer без пауз) seqlock reader
    НИКОГДА не возвращает порванный кадр — torn == 0.

    valid здесь может быть ~0 (writer занимает почти всё время → каждое окно чтения
    перекрывается записью → честный drop). Это КОРРЕКТНО: seqlock превращает гонку
    в drop, не в порчу. Что seqlock реально ОТДАЁТ кадры при read<<write — проверяют
    ``test_seqlock_delivers_valid_frames_under_light_contention`` и детерминированные
    roundtrip-тесты ниже.
    """
    torn, _drops, _valid = _run_contention(_seqlock_read, seqlock=True)
    assert torn == 0, f"seqlock обязан исключить torn-frame, поймано {torn}"


def test_seqlock_delivers_valid_frames_under_light_contention():
    """Seqlock НЕ чёрная дыра: при read << write_period reader стабильно отдаёт кадры.

    Малый кадр (быстрое чтение) + пауза writer 3мс (реальный межкадровый интервал) →
    reader попадает в чистые окна: valid > 0, при этом torn == 0.
    """
    torn, _drops, valid = _run_contention(
        _seqlock_read, shape=(128, 128, 3), iters=2000, seqlock=True, writer_gap=0.003
    )
    assert torn == 0, f"seqlock не должен отдавать torn, поймано {torn}"
    assert valid > 0, "seqlock обязан отдавать валидные кадры при read << write_period"


# --- Детерминированные unit-тесты формата seqlock (без гонки) --------------------


def _alloc(shape=(4, 4, 3), *, seqlock: bool) -> tuple[memoryview, tuple, np.dtype]:
    size = fmt.calculate_buffer_size(1, shape, _DTYPE, seqlock=seqlock)
    return memoryview(bytearray(size)), shape, np.dtype(_DTYPE)


def test_seqlock_buffer_size_is_legacy_plus_slot_header():
    shape = (10, 10, 3)
    legacy = fmt.calculate_buffer_size(1, shape, _DTYPE, seqlock=False)
    seq = fmt.calculate_buffer_size(1, shape, _DTYPE, seqlock=True)
    assert seq - legacy == fmt.SLOT_HEADER_SIZE == 8


def test_seqlock_roundtrip():
    mv, shape, dtype = _alloc(seqlock=True)
    frame = np.full(shape, 7, dtype=_DTYPE)
    fmt.pack_images(mv, [frame], shape, dtype, seqlock=True)
    imgs = fmt.unpack_images(mv, shape, dtype, n=1, copy=True, verify_seqlock=True)
    assert imgs is not None and len(imgs) == 1
    assert np.array_equal(imgs[0], frame)


def test_seqlock_generation_increments_by_two_per_write():
    mv, shape, dtype = _alloc(seqlock=True)
    assert fmt.read_generation(mv) == 0
    frame = np.zeros(shape, dtype=_DTYPE)
    for expected in (2, 4, 6):
        fmt.pack_images(mv, [frame], shape, dtype, seqlock=True)
        assert fmt.read_generation(mv) == expected
    # После завершённой записи generation чётный + state = ready.
    assert fmt.read_slot_state(mv) == fmt.SLOT_STATE_READY


def test_seqlock_odd_generation_means_write_in_progress_drops():
    mv, shape, dtype = _alloc(seqlock=True)
    fmt.pack_images(mv, [np.full(shape, 3, dtype=_DTYPE)], shape, dtype, seqlock=True)
    # Симулируем «writer начал запись» — generation нечётный (writing).
    buf_mod._write_generation(mv, fmt.read_generation(mv) + 1)
    imgs = fmt.unpack_images(mv, shape, dtype, n=1, copy=True, verify_seqlock=True)
    assert imgs is None, "нечётный generation обязан дать drop (None)"


def test_seqlock_generation_change_during_read_drops():
    """Детерминированная симуляция torn: generation меняется 'во время' чтения.

    Патчим read_generation так, что g_before != g_after (writer перезаписал слот),
    и проверяем, что unpack возвращает None (drop), а не порванные данные.
    """
    mv, shape, dtype = _alloc(seqlock=True)
    fmt.pack_images(mv, [np.full(shape, 5, dtype=_DTYPE)], shape, dtype, seqlock=True)
    gen0 = fmt.read_generation(mv)  # чётный, стабильный

    calls = {"n": 0}
    real = buf_mod.read_generation

    def fake_read_gen(buf):
        calls["n"] += 1
        # Первый вызов (g_before) — истинный чётный; второй (g_after) — уже другой.
        return gen0 if calls["n"] == 1 else gen0 + 2

    # Патчим в модуле buffer — именно оттуда unpack_images резолвит имя (не из
    # пакета format, куда символ лишь ре-экспортирован).
    buf_mod.read_generation = fake_read_gen  # type: ignore[assignment]
    try:
        imgs = fmt.unpack_images(mv, shape, dtype, n=1, copy=True, verify_seqlock=True)
    finally:
        buf_mod.read_generation = real  # type: ignore[assignment]
    assert imgs is None, "смена generation во время чтения обязана дать drop"


def test_legacy_format_unaffected_by_seqlock_default():
    """seqlock=False (дефолт) → байт-в-байт прежний формат (base=0, без SLOT-header)."""
    mv, shape, dtype = _alloc(seqlock=False)
    frame = np.full(shape, 9, dtype=_DTYPE)
    fmt.pack_images(mv, [frame], shape, dtype)  # seqlock не передан → False
    # num_images в самом начале буфера (offset 0), не сдвинут.
    assert struct.unpack_from("I", mv, 0)[0] == 1
    imgs = fmt.unpack_images(mv, shape, dtype, n=1, copy=True)  # verify_seqlock=False
    assert imgs is not None and np.array_equal(imgs[0], frame)


# --- MemoryManager: сквозная проводка seqlock (standalone-режим) -----------------


def test_memory_manager_seqlock_roundtrip():
    """MemoryManager(seqlock_frames=True): слот стампуется seqlock, write→read корректно."""
    mm = MemoryManager(seqlock_frames=True)
    try:
        assert mm.create_memory_dict("owner", {"frames": (1, (8, 8, 3), "uint8")}, coll=2)
        md = mm.get_memory_data("owner", "frames")
        assert md["seqlock"] is True
        frame = np.full((8, 8, 3), 42, dtype=np.uint8)
        name = mm.write_images("owner", "frames", [frame], 0)
        assert name, "write_images должен вернуть имя слота"
        imgs = mm.read_images("owner", "frames", 0, n=1)
        assert imgs is not None and np.array_equal(imgs[0], frame)
    finally:
        mm.close_all()


def test_memory_manager_seqlock_off_by_default():
    """Без ctor-флага и без env FW_SHM_SEQLOCK → seqlock=False (прежний формат)."""
    mm = MemoryManager()
    try:
        assert mm.create_memory_dict("o", {"f": (1, (4, 4, 3), "uint8")}, coll=1)
        assert mm.get_memory_data("o", "f")["seqlock"] is False
    finally:
        mm.close_all()


# --- H1: живучесть слота (отравление/exception/clear по протоколу) ----------------


def test_seqlock_poisoned_odd_generation_heals_on_next_write():
    """H1b: слот с НЕЧЁТНЫМ generation (writer «завис») лечится следующей записью."""
    mv, shape, dtype = _alloc(seqlock=True)
    fmt.pack_images(mv, [np.full(shape, 5, dtype=_DTYPE)], shape, dtype, seqlock=True)
    # Отравить: generation нечёт (прошлый writer не довёл запись).
    buf_mod._write_generation(mv, fmt.read_generation(mv) + 1)
    assert fmt.read_generation(mv) & 1, "слот отравлен (нечёт)"
    # Валидные данные сейчас НЕ читаются (нечёт → drop).
    assert fmt.unpack_images(mv, shape, dtype, n=1, copy=True, verify_seqlock=True) is None

    recovered: list[int] = []
    frame = np.full(shape, 9, dtype=_DTYPE)
    fmt.pack_images(mv, [frame], shape, dtype, seqlock=True, on_recover=recovered.append)
    assert not (fmt.read_generation(mv) & 1), "после записи generation чёт (слот читаем)"
    assert recovered, "on_recover обязан сработать при нечётном входе"
    imgs = fmt.unpack_images(mv, shape, dtype, n=1, copy=True, verify_seqlock=True)
    assert imgs is not None and np.array_equal(imgs[0], frame)


def test_seqlock_pack_exception_leaves_generation_even_and_slot_empty():
    """H1a: исключение внутри записи → generation ВСЕГДА чёт (не отравлен), слот пуст."""
    mv, shape, dtype = _alloc(seqlock=True)  # max_shape (4,4,3)
    gen0 = fmt.read_generation(mv)
    big = np.full((8, 8, 3), 7, dtype=_DTYPE)  # больше max → ValueError в pack
    with pytest.raises(ValueError):
        fmt.pack_images(mv, [big], shape, dtype, seqlock=True)
    assert not (fmt.read_generation(mv) & 1), "generation вернулся к чёт (не отравлен)"
    assert fmt.read_generation(mv) == gen0 + 2
    # Слот пуст (num_images=0) — reader получает [] (не мусор), не падает.
    assert fmt.unpack_images(mv, shape, dtype, n=1, copy=True, verify_seqlock=True) == []


def test_clear_slot_seqlock_follows_protocol():
    """H1c: clear_slot_seqlock — generation чёт после, state FREE, num_images=0."""
    mv, shape, dtype = _alloc(seqlock=True)
    fmt.pack_images(mv, [np.full(shape, 5, dtype=_DTYPE)], shape, dtype, seqlock=True)
    fmt.clear_slot_seqlock(mv)
    assert not (fmt.read_generation(mv) & 1)
    assert fmt.read_slot_state(mv) == fmt.SLOT_STATE_FREE
    assert fmt.unpack_images(mv, shape, dtype, n=1, copy=True, verify_seqlock=True) == []


# --- M1: read-примитивы — torn = None, стабильная порча = исключение ---------------


def test_seqlock_malformed_header_stable_gen_raises():
    """M1: рваный header при СТАБИЛЬНОМ generation = реальная порча → исключение (caller логирует)."""
    mv, shape, dtype = _alloc(seqlock=True)
    fmt.pack_images(mv, [np.full(shape, 5, dtype=_DTYPE)], shape, dtype, seqlock=True)
    # Испортить h на огромное значение при неизменном generation → frombuffer:
    # "buffer smaller than requested size" (ValueError).
    h_off = fmt.SLOT_HEADER_SIZE + 4  # base + num_images(4) → поле h (uint32)
    struct.pack_into("I", mv, h_off, 999_999)
    with pytest.raises((ValueError, TypeError)):
        fmt.unpack_images(mv, shape, dtype, n=1, copy=True, verify_seqlock=True)


def test_seqlock_malformed_header_with_gen_change_is_torn_none():
    """M1: рваный header + смена generation (гонка) = torn → None, НЕ исключение."""
    mv, shape, dtype = _alloc(seqlock=True)
    fmt.pack_images(mv, [np.full(shape, 5, dtype=_DTYPE)], shape, dtype, seqlock=True)
    h_off = fmt.SLOT_HEADER_SIZE + 4
    struct.pack_into("I", mv, h_off, 999_999)  # огромный h → _read_image_block бросит

    gen0 = fmt.read_generation(mv)
    calls = {"n": 0}

    def fake_read_gen(buf):
        calls["n"] += 1
        return gen0 if calls["n"] == 1 else gen0 + 2  # g_before ок, g_after изменился

    real = buf_mod.read_generation
    buf_mod.read_generation = fake_read_gen
    try:
        result = fmt.unpack_images(mv, shape, dtype, n=1, copy=True, verify_seqlock=True)
    finally:
        buf_mod.read_generation = real
    assert result is None, "torn (gen изменился) обязан дать None, не исключение"
