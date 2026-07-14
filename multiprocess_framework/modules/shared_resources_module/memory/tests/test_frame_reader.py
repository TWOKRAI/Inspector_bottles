# -*- coding: utf-8 -*-
"""Ф7 H-задача (Этап 2) + H-ревью: изолированные contract-тесты фасада `FrameReader`.

Симметрично `test_frame_pool.py` для `FramePool`: проверяют reader-side тракт В ИЗОЛЯЦИИ
от транспорта (`FrameShmMiddleware`) — Protocol-соответствие, кэш handles, teardown,
post-use re-check (`view_valid`) и наблюдаемость счётчиков (`stale_drops`/`close_errors`).
Интеграция zero-copy с реальным SHM — `router_module/tests/test_g5b_zero_copy.py`/
`test_g5c_stale_recheck.py`.
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.shared_resources_module.memory.reader import (
    FrameReader,
    ShmFrameReader,
)


class _FakeShm:
    """Мок SharedMemory-handle: считает close() и опц. бросает (эмуляция BufferError)."""

    def __init__(self, *, raise_on_close: bool = False) -> None:
        self.closed = 0
        self._raise = raise_on_close
        self.buf = memoryview(bytearray(64))

    def close(self) -> None:
        self.closed += 1
        if self._raise:
            raise BufferError("exported view alive")


def _reader(**kw: Any) -> ShmFrameReader:
    base = dict(cache_enabled=True, zero_copy=False, cap=2)
    base.update(kw)
    return ShmFrameReader(**base)  # type: ignore[arg-type]


class TestProtocolConformance:
    def test_shm_frame_reader_is_frame_reader(self):
        """ShmFrameReader удовлетворяет Protocol FrameReader (runtime_checkable)."""
        assert isinstance(_reader(), FrameReader)

    def test_counters_start_zero(self):
        r = _reader()
        assert r.stale_drops == 0
        assert r.close_errors == 0


class TestViewValid:
    def test_negative_generation_is_stale(self):
        """gen_at_read<0 (без seqlock) → drop + счётчик (re-check неактивен)."""
        r = _reader(zero_copy=True)
        assert r.view_valid("any", -1) is False
        assert r.stale_drops == 1

    def test_missing_handle_is_conservative_drop(self):
        """Handle не в кэше (эвиктнут/сменился) → консервативный drop."""
        r = _reader(zero_copy=True)
        assert r.view_valid("missing", 0) is False
        assert r.stale_drops == 1

    def test_generation_match_and_mismatch(self):
        r = _reader(zero_copy=True)
        shm = _FakeShm()
        # заголовок generation по смещению 0 (uint32 LE) — используем read_generation
        # косвенно: положим handle в кэш и сверим против прочитанного поколения.
        r._cache["v"] = shm
        from multiprocess_framework.modules.shared_resources_module.memory.format import (
            read_generation,
        )

        gen = read_generation(shm.buf)
        assert r.view_valid("v", gen) is True
        assert r.view_valid("v", gen + 1) is False  # разошлось → drop
        assert r.stale_drops == 1


class TestCloseAndErrors:
    def test_close_empty_is_safe(self):
        r = _reader()
        r.close()  # не падает
        assert r.close_errors == 0

    def test_close_closes_all_and_clears(self):
        r = _reader()
        a, b = _FakeShm(), _FakeShm()
        r._cache["a"] = a
        r._cache["b"] = b
        r.close()
        assert a.closed == 1 and b.closed == 1
        assert r._cache == {}
        assert r.close_errors == 0

    def test_close_error_counted_not_swallowed(self):
        """H-ревью (S3): ошибка close() СЧИТАЕТСЯ (не глотается молча) + опц. лог."""
        logs: list[str] = []
        r = _reader(log=logs.append)
        r._cache["bad"] = _FakeShm(raise_on_close=True)
        r.close()
        assert r.close_errors == 1
        assert logs and "close()" in logs[0]

    def test_lru_eviction_closes_oldest_without_zero_copy(self):
        """Без zero-copy кэш эвиктит старейший handle при переполнении cap (с close)."""
        r = _reader(zero_copy=False, cap=1)
        old = _FakeShm()
        r._cache["old"] = old
        # добавить второй через locked-хелпер (эмулируем внутренний путь open)

        class _Mod:
            @staticmethod
            def SharedMemory(name: str, create: bool = False) -> _FakeShm:  # noqa: N802
                return _FakeShm()

        with r._lock:
            r._open_cached_locked("new", _Mod)
        assert old.closed == 1  # старейший закрыт при эвикции
        assert "old" not in r._cache
