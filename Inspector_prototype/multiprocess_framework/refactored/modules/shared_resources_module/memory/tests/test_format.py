"""
Тесты format.py — формат буфера изображений.

Не требуют SharedMemory, работают на всех платформах.
"""

import numpy as np
import pytest

from ..format.buffer import (
    HEADER_SIZE,
    IMAGE_HEADER_SIZE,
    calculate_buffer_size,
    pack_images,
    pack_images_fast,
    pack_images_legacy,
    unpack_images,
)


class TestCalculateBufferSize:
    def test_single_image(self):
        size = calculate_buffer_size(1, (10, 10, 3), np.uint8)
        # 4 + 1 * (12 + 1 + 10*10*3) = 4 + 313 = 317
        expected = HEADER_SIZE + 1 * (IMAGE_HEADER_SIZE + 10 * 10 * 3)
        assert size == expected

    def test_multiple_images(self):
        size = calculate_buffer_size(2, (480, 640, 3), np.uint8)
        slot = IMAGE_HEADER_SIZE + 480 * 640 * 3
        assert size == HEADER_SIZE + 2 * slot

    def test_float_dtype(self):
        size = calculate_buffer_size(1, (5, 5, 1), np.float32)
        # 4 + (12 + 1 + 5*5*1*4) = 4 + 138 = 142
        assert size == HEADER_SIZE + IMAGE_HEADER_SIZE + 5 * 5 * 1 * 4


class TestPackUnpackRoundtrip:
    def test_single_image(self):
        shape = (10, 10, 3)
        dtype = np.uint8
        size = calculate_buffer_size(2, shape, dtype)
        buf = bytearray(size)
        mv = memoryview(buf)

        img = np.full(shape, 128, dtype=dtype)
        pack_images(mv, [img], shape, np.dtype(dtype))

        result = unpack_images(mv, shape, np.dtype(dtype))
        assert len(result) == 1
        assert np.array_equal(result[0], img)

    def test_multiple_images(self):
        shape = (5, 5, 3)
        dtype = np.uint8
        size = calculate_buffer_size(3, shape, dtype)
        buf = bytearray(size)
        mv = memoryview(buf)

        imgs = [
            np.full(shape, i, dtype=dtype)
            for i in (10, 20, 30)
        ]
        pack_images(mv, imgs, shape, np.dtype(dtype))

        result = unpack_images(mv, shape, np.dtype(dtype))
        assert len(result) == 3
        for i, (r, orig) in enumerate(zip(result, imgs)):
            assert np.array_equal(r, orig), f"Image {i} mismatch"

    def test_unpack_with_n_limit(self):
        shape = (5, 5, 3)
        dtype = np.uint8
        size = calculate_buffer_size(3, shape, dtype)
        buf = bytearray(size)
        mv = memoryview(buf)

        imgs = [np.full(shape, i, dtype=dtype) for i in (1, 2, 3)]
        pack_images(mv, imgs, shape, np.dtype(dtype))

        result = unpack_images(mv, shape, np.dtype(dtype), n=2)
        assert len(result) == 2
        assert np.array_equal(result[0], imgs[0])
        assert np.array_equal(result[1], imgs[1])

    def test_empty_buffer_returns_empty_list(self):
        shape = (5, 5, 3)
        dtype = np.uint8
        size = calculate_buffer_size(2, shape, dtype)
        buf = bytearray(size)
        mv = memoryview(buf)
        # num_images = 0
        mv[0:4] = (0).to_bytes(4, "little")

        result = unpack_images(mv, shape, np.dtype(dtype))
        assert result == []

    def test_dtype_mismatch_raises(self):
        shape = (5, 5, 3)
        size = calculate_buffer_size(2, shape, np.uint8)
        buf = bytearray(size)
        mv = memoryview(buf)

        wrong_img = np.zeros(shape, dtype=np.float32)
        with pytest.raises(ValueError, match="dtype mismatch"):
            pack_images(mv, [wrong_img], shape, np.dtype(np.uint8))


class TestPackFormatsInterchangeable:
    """pack_images_legacy и pack_images_fast дают одинаковый результат."""

    def test_legacy_and_fast_produce_same_output(self):
        shape = (10, 10, 3)
        dtype = np.uint8
        size = calculate_buffer_size(2, shape, dtype)
        img = np.full(shape, 77, dtype=dtype)

        buf_legacy = bytearray(size)
        buf_fast = bytearray(size)
        pack_images_legacy(memoryview(buf_legacy), [img], shape, np.dtype(dtype))
        pack_images_fast(memoryview(buf_fast), [img], shape, np.dtype(dtype))

        # Заголовок и данные должны совпадать (padding может отличаться)
        assert buf_legacy[:4] == buf_fast[:4]
        data_len = 12 + 1 + 10 * 10 * 3
        assert buf_legacy[4 : 4 + data_len] == buf_fast[4 : 4 + data_len]

    def test_unpack_copy_true_returns_own_data(self):
        shape = (5, 5, 3)
        size = calculate_buffer_size(2, shape, np.uint8)
        buf = bytearray(size)
        img = np.full(shape, 42, dtype=np.uint8)
        pack_images_fast(memoryview(buf), [img], shape, np.uint8)

        result = unpack_images(memoryview(buf), shape, np.uint8, copy=True)
        assert np.array_equal(result[0], img)
        result[0][0, 0, 0] = 99
        assert buf[4 + 12 + 1] != 99  # копия, буфер не изменился

    def test_unpack_copy_false_returns_view(self):
        shape = (5, 5, 3)
        size = calculate_buffer_size(2, shape, np.uint8)
        buf = bytearray(size)
        img = np.full(shape, 42, dtype=np.uint8)
        pack_images_fast(memoryview(buf), [img], shape, np.uint8)

        result = unpack_images(memoryview(buf), shape, np.uint8, copy=False)
        assert np.array_equal(result[0], img)
        result[0][0, 0, 0] = 99
        # view — изменение отражается в буфере
        assert buf[4 + 12 + 1] == 99
