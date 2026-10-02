# -*- coding: utf-8 -*-
"""Ф7 G.5.b — zero-copy чтение кадра (restore_frame отдаёт view, а не .copy()).

С 4.7b гейтов и флагов нет: view у ``restore_frame`` всегда, у ``on_receive`` — копия
(seqlock-заголовок слота — всегда, Task 4.4). Ключевой инвариант владельца: форма view берётся
из per-image заголовка → переменная форма кадра (grayscale/resize/crop) корректна.

post-use re-check поколения (безопасность УДЕРЖАНИЯ view) — G.5.c; здесь проверяется
только read-side механика view + мета для будущего re-check. View дропается до
close_handle_cache (иначе backing-mmap не закрыть — «cannot close exported pointers»,
ровно опасность use-after-free, которую и покрывает протокол владения G.5.c/d).
"""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)


def _writer_reader():
    """Writer и reader на РАЗНЫХ MemoryManager → path-1 (mm) у reader'а не находит
    чужого owner'а → падает на path-2 (raw open по ref["name"]) = zero-copy путь."""
    writer = FrameShmMiddleware(MemoryManager(), owner="cam0", slot="output_frames", coll=4)
    reader = FrameShmMiddleware(MemoryManager(), owner="reader", slot="unused")
    return writer, reader


def _restore_probe(reader, out):
    """restore → снять (shape, первый_пиксель, is_view) → ДРОПНУТЬ view (чтобы backing
    mmap можно было закрыть на teardown). None если кадр не восстановлен."""
    frame = reader.restore_frame({"data": out})["frame"]
    if frame is None:
        return None
    probe = (tuple(frame.shape), int(frame.reshape(-1)[0]), frame.base is not None)
    del frame
    return probe


class TestGate:
    """4.7b: гейтов нет — конвейер (``restore_frame``) всегда получает read-only view,
    copy-out (``on_receive``) — копию."""

    def test_restore_frame_is_view_without_any_env(self):
        """Без env restore_frame отдаёт view в слот (не копию), билет re-check'а есть."""
        writer, reader = _writer_reader()
        try:
            out = writer.strip_and_write({"frame": np.full((32, 48, 3), 7, np.uint8)})
            probe = _restore_probe(reader, out)
            assert probe is not None and probe[1] == 7
            assert probe[2] is True  # view
            assert out.get("_shm_views") == [out["_shm_refs"]["frame"]]
        finally:
            reader.close_handle_cache()
            writer.release_owned_memory()

    def test_on_receive_is_copy_out(self):
        """GUI-путь (``on_receive``) — независимая копия и без view-билетов; кэш handles живёт."""
        writer, reader = _writer_reader()
        try:
            out = writer.strip_and_write({"frame": np.full((32, 48, 3), 9, np.uint8)})
            msg = reader.on_receive({"data": out})
            frame = msg["frame"] if msg.get("frame") is not None else msg["data"]["frame"]
            assert frame.flags.owndata and frame.flags.writeable
            assert int(frame.min()) == int(frame.max()) == 9
            assert out.get("_shm_views") is None
            assert reader.frame_handle_cache_size == 1
            del frame, msg
        finally:
            reader.close_handle_cache()
            writer.release_owned_memory()


class TestZeroCopyView:
    def test_restore_returns_view(self):
        """restore_frame → view в слот (shares buffer), не копия + мета."""
        writer, reader = _writer_reader()
        try:
            out = writer.strip_and_write({"frame": np.full((32, 48, 3), 11, np.uint8)})
            probe = _restore_probe(reader, out)
            assert probe == ((32, 48, 3), 11, True)  # форма, значение, IS view
            # Билет для post-use re-check (G.5.c): сама ссылка на кадр (name + gen записи).
            assert out.get("_shm_views") == [out["_shm_refs"]["frame"]]
            assert out["_shm_refs"]["frame"]["gen"] > 0
        finally:
            reader.close_handle_cache()
            writer.release_owned_memory()

    def test_view_variable_shape_crop(self):
        """Ключевой инвариант владельца: crop-кадр МЕНЬШЕ слота → view имеет форму из
        per-image заголовка, не тянет max-слот/padding/соседний кадр."""
        writer, reader = _writer_reader()
        try:
            # Первый кадр большой → слот выделен под 64×64×3.
            writer.strip_and_write({"frame": np.full((64, 64, 3), 1, np.uint8)})
            # Второй — маленький crop (16×20×3) в тот же большой слот (ring idx 1).
            out = writer.strip_and_write({"frame": np.full((16, 20, 3), 9, np.uint8)})
            probe = _restore_probe(reader, out)
            assert probe == ((16, 20, 3), 9, True)  # форма из заголовка, не 64×64; view
        finally:
            reader.close_handle_cache()
            writer.release_owned_memory()

    def test_view_grayscale_channel(self):
        """grayscale (c=1) через view: форма (h,w,1) корректна."""
        writer, reader = _writer_reader()
        try:
            writer.strip_and_write({"frame": np.full((32, 48, 3), 1, np.uint8)})  # alloc цветной
            out = writer.strip_and_write({"frame": np.full((32, 48, 1), 5, np.uint8)})  # c=1
            probe = _restore_probe(reader, out)
            assert probe == ((32, 48, 1), 5, True)
        finally:
            reader.close_handle_cache()
            writer.release_owned_memory()

    def test_view_is_readonly(self):
        """Ревью-фикс 8: zero-copy view READ-ONLY — in-place мутация плагином мимо
        seqlock (тихая порча чужого слота) невозможна; попытка записи → ValueError."""
        import pytest

        writer, reader = _writer_reader()
        try:
            out = writer.strip_and_write({"frame": np.full((16, 16, 3), 7, np.uint8)})
            frame = reader.restore_frame({"data": out})["frame"]
            assert frame.flags.writeable is False  # view защищён от записи
            with pytest.raises(ValueError):
                frame[0, 0, 0] = 99  # in-place мутация → громкий отказ, не порча
            del frame
        finally:
            reader.close_handle_cache()
            writer.release_owned_memory()
