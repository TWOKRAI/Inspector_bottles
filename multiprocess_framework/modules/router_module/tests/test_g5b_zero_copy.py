# -*- coding: utf-8 -*-
"""Ф7 G.5.b — zero-copy чтение кадра (restore_frame отдаёт view, а не .copy()).

Гейт активации: FW_SHM_ZERO_COPY И живой handle-кэш (FW_SHM_HANDLE_CACHE +
FW_SHM_OWNER_INCARNATION) И seqlock (FW_SHM_SEQLOCK). Без любого из них — копия
(бит-в-бит прежнее / безопасно). Ключевой инвариант владельца: форма view берётся
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


def _enable_zero_copy(monkeypatch) -> None:
    monkeypatch.setenv("FW_SHM_SEQLOCK", "1")
    monkeypatch.setenv("FW_SHM_OWNER_INCARNATION", "1")
    monkeypatch.setenv("FW_SHM_HANDLE_CACHE", "1")
    monkeypatch.setenv("FW_SHM_ZERO_COPY", "1")


def _writer_reader():
    """Writer и reader на РАЗНЫХ MemoryManager → path-1 (mm) у reader'а не находит
    чужого owner'а → падает на path-2 (raw open по shm_actual_name) = zero-copy путь."""
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
    def test_default_off_is_copy(self, monkeypatch):
        """Без флага zero-copy отключён; restore возвращает копию, меты view нет."""
        monkeypatch.delenv("FW_SHM_ZERO_COPY", raising=False)
        writer, reader = _writer_reader()
        assert reader._zero_copy is False
        try:
            out = writer.strip_and_write({"frame": np.full((32, 48, 3), 7, np.uint8)})
            probe = _restore_probe(reader, out)
            assert probe is not None and probe[1] == 7
            assert probe[2] is False  # копия (frombuffer-view отсутствует)
            assert out.get("_frame_is_view") is None  # маркера нет
        finally:
            reader.close_handle_cache()
            writer.release_owned_memory()

    def test_disabled_without_handle_cache(self, monkeypatch):
        """zero_copy запрошен, но кэш выключен → ОТКЛЮЧЁН (view повис бы)."""
        monkeypatch.setenv("FW_SHM_ZERO_COPY", "1")
        monkeypatch.delenv("FW_SHM_HANDLE_CACHE", raising=False)
        mw = FrameShmMiddleware(MemoryManager(), owner="o", slot="s")
        assert mw._zero_copy is False

    def test_ctor_optout_wins(self, monkeypatch):
        """GUI-паттерн: zero_copy=False в ctor перекрывает env-флаг (copy-out гарантирован)."""
        _enable_zero_copy(monkeypatch)
        mw = FrameShmMiddleware(MemoryManager(), owner="gui", slot="s", zero_copy=False)
        assert mw._zero_copy is False


class TestZeroCopyView:
    def test_restore_returns_view(self, monkeypatch):
        """restore_frame под гейтом → view в слот (shares buffer), не копия + мета."""
        _enable_zero_copy(monkeypatch)
        writer, reader = _writer_reader()
        assert reader._zero_copy is True
        try:
            out = writer.strip_and_write({"frame": np.full((32, 48, 3), 11, np.uint8)})
            probe = _restore_probe(reader, out)
            assert probe == ((32, 48, 3), 11, True)  # форма, значение, IS view
            # Мета для post-use re-check (G.5.c).
            assert out.get("_frame_is_view") is True
            assert out.get("_shm_view_name") == out["shm_actual_name"]
            assert out.get("_shm_view_generation", -1) >= 0  # seqlock → реальное поколение
        finally:
            reader.close_handle_cache()
            writer.release_owned_memory()

    def test_view_variable_shape_crop(self, monkeypatch):
        """Ключевой инвариант владельца: crop-кадр МЕНЬШЕ слота → view имеет форму из
        per-image заголовка, не тянет max-слот/padding/соседний кадр."""
        _enable_zero_copy(monkeypatch)
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

    def test_view_grayscale_channel(self, monkeypatch):
        """grayscale (c=1) через view: форма (h,w,1) корректна."""
        _enable_zero_copy(monkeypatch)
        writer, reader = _writer_reader()
        try:
            writer.strip_and_write({"frame": np.full((32, 48, 3), 1, np.uint8)})  # alloc цветной
            out = writer.strip_and_write({"frame": np.full((32, 48, 1), 5, np.uint8)})  # c=1
            probe = _restore_probe(reader, out)
            assert probe == ((32, 48, 1), 5, True)
        finally:
            reader.close_handle_cache()
            writer.release_owned_memory()

    def test_view_is_readonly(self, monkeypatch):
        """Ревью-фикс 8: zero-copy view READ-ONLY — in-place мутация плагином мимо
        seqlock (тихая порча чужого слота) невозможна; попытка записи → ValueError."""
        import pytest

        _enable_zero_copy(monkeypatch)
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
