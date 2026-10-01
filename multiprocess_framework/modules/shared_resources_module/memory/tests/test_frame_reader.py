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

    def __init__(self, *, raise_on_close: "Exception | None" = None) -> None:
        self.closed = 0
        self._raise = raise_on_close
        self.buf = memoryview(bytearray(64))

    def close(self) -> None:
        self.closed += 1
        if self._raise is not None:
            raise self._raise


def _reader(**kw: Any) -> ShmFrameReader:
    return ShmFrameReader(**kw)


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
        r = _reader()
        assert r.view_valid("any", -1) is False
        assert r.stale_drops == 1

    def test_missing_handle_is_conservative_drop(self):
        """Handle не в кэше (эвиктнут/сменился) → консервативный drop."""
        r = _reader()
        assert r.view_valid("missing", 0) is False
        assert r.stale_drops == 1

    def test_generation_match_and_mismatch(self):
        r = _reader()
        shm = _FakeShm()
        # заголовок generation по смещению 0 (uint32 LE) — используем read_generation
        # косвенно: положим handle в кэш и сверим против прочитанного поколения.
        r._cache[("v",)] = ("v", shm)
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
        r._cache[("a",)] = ("a", a)
        r._cache[("b",)] = ("b", b)
        r.close()
        assert a.closed == 1 and b.closed == 1
        assert r._cache == {}
        assert r.close_errors == 0

    def test_close_error_counted_not_swallowed(self):
        """H-ревью (S3): ошибка close() (не BufferError) СЧИТАЕТСЯ (не глотается молча) + опц. лог."""
        logs: list[str] = []
        r = _reader(log=logs.append)
        r._cache[("bad",)] = ("bad", _FakeShm(raise_on_close=OSError("boom")))
        r.close()
        assert r.close_errors == 1
        assert logs and "close()" in logs[0]

    def test_close_with_live_view_defers_not_error(self):
        """4.7b2: BufferError (живой view) — не ошибка: handle ждёт в ``_retired``, ``deferred_closes`` +1."""
        r = _reader()
        bad = _FakeShm(raise_on_close=BufferError("exported view alive"))
        r._cache[("bad",)] = ("bad", bad)
        r.close()
        assert r.close_errors == 0 and r.deferred_closes == 1
        assert r._retired == [bad] and r._cache == {}

    def test_new_name_under_same_key_retires_old_handle(self):
        """4.7b: новое имя под тем же ключом — старый handle закрыт и убран из кэша."""
        r = _reader()
        old = _FakeShm()
        r._cache[("o", "s", 0)] = ("old", old)

        class _Mod:
            @staticmethod
            def SharedMemory(name: str, create: bool = False) -> _FakeShm:  # noqa: N802
                return _FakeShm()

        with r._lock:
            r._open_cached_locked(("o", "s", 0), "new", _Mod)
        assert old.closed == 1
        assert r._cache[("o", "s", 0)][0] == "new"
        assert r.cache_size == 1
