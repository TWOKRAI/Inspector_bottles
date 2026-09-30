# -*- coding: utf-8 -*-
"""Task 4.5c — hazard-тесты автора: места, где счётчики байтов легко соврать.

* torn-чтение (слот переписывается во время чтения) не даёт байтов в ``bytes_read``;
* упавшая запись (``write_frame`` вернул ложь) не даёт байтов в ``bytes_written``;
* guard heartbeat ``any(shm.values())`` открывается и от одних только новых байтовых счётчиков
  (иначе процесс с трафиком, но без потерь, перестал бы публиковать секцию ``shm``).
"""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    build_router_shm_telemetry,
)
from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)
from multiprocess_framework.modules.shared_resources_module.memory.format import buffer as buf_mod


def _frame(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 250, size=(20, 20, 3)).astype(np.uint8)


def test_torn_read_adds_zero_to_bytes_read() -> None:
    """Поколение слота отравлено в нечёт (writer «в процессе»), ссылка называет его -> torn-дроп,
    ``frame_torn_reads`` == 1, ``bytes_read`` == 0. Красный revert: считать байты до проверки
    поколения (внутри reader'а) -> 1200."""
    prod = FrameShmMiddleware(MemoryManager(), owner="p", slot="s", zero_copy=False)
    consumer = FrameShmMiddleware(MemoryManager(), owner="c", slot="s", zero_copy=False)
    try:
        item = prod.strip_and_write({"frame": _frame(1)})
        ref = item["_shm_refs"]["frame"]
        handle = prod._mm.get_memory_data("p", "s")["handles"][ref["idx"]]
        odd = buf_mod.read_generation(handle.buf) + 1
        buf_mod._write_generation(handle.buf, odd)
        ref["gen"] = odd

        out = consumer.restore_frame({"data": dict(item)})

        assert out.get("frame") is None
        assert consumer.frame_torn_reads == 1
        assert consumer.bytes_read == 0
    finally:
        consumer.close_handle_cache()
        prod._mm.close_all()
        consumer._mm.close_all()


def test_failed_write_adds_zero_to_bytes_written() -> None:
    """``write_frame`` возвращает None (нет слота/валидация) -> кадр уходит pickle-fallback'ом,
    ``bytes_written`` == 0. Красный revert: считать байты до проверки результата записи -> 1200."""
    mm = MemoryManager()
    mw = FrameShmMiddleware(mm, owner="o", slot="s", zero_copy=False)
    mm.write_frame = lambda *a, **k: None  # type: ignore[method-assign]
    try:
        mw.strip_and_write({"frame": _frame(2)})
        assert mw.frame_pickle_fallbacks == 1, "стенд: запись обязана была провалиться"
        assert mw.bytes_written == 0
    finally:
        mm.close_all()


class _FakeRouter:
    def __init__(self, **stats: int) -> None:
        self._stats = stats

    def get_shm_stats(self) -> dict:
        return dict(self._stats)


def test_heartbeat_gate_opens_on_byte_counters_alone_and_stays_shut_on_zeros() -> None:
    """Guard heartbeat = ``any(shm.values())``. Все нули (включая три новых ключа) -> закрыт;
    только ``shm_bytes_written`` ненулевой -> открыт, и остальные семь новых/старых остаются 0."""
    zeros = build_router_shm_telemetry(_FakeRouter())
    assert {"bytes_written", "bytes_read", "restore_failures"} <= set(zeros)
    assert not any(zeros.values())

    only_bytes = build_router_shm_telemetry(_FakeRouter(shm_bytes_written=921_600))
    assert only_bytes["bytes_written"] == 921_600
    assert any(only_bytes.values())
    assert sum(1 for v in only_bytes.values() if v) == 1
