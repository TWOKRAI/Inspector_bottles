# -*- coding: utf-8 -*-
"""4.7b2: ссылка без owner/slot/idx (легаси ``{name, gen}``) — ключ кэша по имени, не общий ``(None, None, None)``."""

from __future__ import annotations

import gc

import numpy as np

from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager


def test_legacy_refs_without_owner_do_not_share_one_cache_key() -> None:
    """Два писателя, ссылки только ``{name, gen}``, чтения вперемешку: оба view валидны, в кэше 2 handle'а.
    Красный revert: ``_ref_key`` -> ``(owner, slot, idx)`` без ветки owner is None (второе чтение отставляет handle
    первого, ``frame_view_valid`` первого view даёт False)."""
    wmms = [MemoryManager(), MemoryManager()]
    writers = [FrameShmMiddleware(m, owner=f"w{i}", slot="s", coll=2) for i, m in enumerate(wmms)]
    rmm = MemoryManager()
    reader = FrameShmMiddleware(rmm, owner="reader", slot="unused")
    try:
        refs = []
        for i, w in enumerate(writers):
            full = w.strip_and_write({"frame": np.full((16, 16, 3), i + 1, np.uint8)})["_shm_refs"]["frame"]
            refs.append({"name": full["name"], "gen": full["gen"]})
        views = [reader._read_ref(r, "frame", True)[0] for r in refs]
        assert all(v is not None for v in views)
        assert [int(v.min()) for v in views] == [1, 2]
        assert all(reader.frame_view_valid(r) for r in refs), "view одного ключа отставлен чтением другого"
        assert reader.frame_handle_cache_size == 2
        del views
    finally:
        gc.collect()
        reader.close_handle_cache()
        for w, m in zip(writers, wmms):
            w.release_owned_memory()
            m.close_all()
        rmm.close_all()
