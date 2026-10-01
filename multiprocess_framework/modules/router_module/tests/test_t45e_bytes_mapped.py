"""Task 4.5e — чтение по ссылке делится на скопированные и отображённые байты.

Ревью 4.5, находка 4: ``bytes_read`` считал и zero-copy view (``owndata False`` — копии не было),
и для отчёта о мощности «переданные байты» не отличались от «скопированных». Правило из цели
владельца — «копии/байты доминируют → упор в память» — судит только по копиям.

Контракт: копия → ``bytes_read`` += nbytes; view → ``bytes_mapped`` += nbytes, ``bytes_read`` не
растёт. ``get_shm_stats()["shm_bytes_mapped"]`` и ``state.shm.bytes_mapped`` — та же сумма.
"""

from __future__ import annotations

import gc

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.heartbeat.telemetry import build_router_shm_telemetry
from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
from multiprocess_framework.modules.router_module.tests import test_t45c_transport_counters as T

FRAME_BYTES = 921_600  # 480 × 640 × 3, uint8


@pytest.fixture
def zero_copy_env(monkeypatch):
    # zero-copy гейтнут на handle-кэш и уникальные имена (до 4.7 — флаги).
    monkeypatch.setenv("FW_SHM_HANDLE_CACHE", "1")
    monkeypatch.setenv("FW_SHM_OWNER_INCARNATION", "1")


def _pair(reader_zero_copy: bool):
    mmw, mmr = T.MemoryManager(), T.MemoryManager()
    w = FrameShmMiddleware(mmw, owner="A", slot="output_frames", coll=3, zero_copy=False)
    r = FrameShmMiddleware(mmr, owner="B", slot="output_frames", coll=3, zero_copy=reader_zero_copy)
    return mmw, mmr, w, r


def _close(*objs) -> None:
    gc.collect()
    for o in objs:
        for fin in ("close_handle_cache", "release_owned_memory", "close_all"):
            f = getattr(o, fin, None)
            if callable(f):
                try:
                    f()
                except Exception:  # noqa: BLE001 — уборка теста
                    pass


def _restore_one(w, r):
    msg = T._wire(T._send(w, {"frame": np.zeros((480, 640, 3), np.uint8)}))
    out = r.restore_frame(msg)
    return out.get("frame") if out.get("frame") is not None else out["data"].get("frame")


def test_t45e_view_read_counts_mapped_not_read(zero_copy_env) -> None:
    mmw, mmr, w, r = _pair(reader_zero_copy=True)
    try:
        assert r._zero_copy, "предпосылка: zero-copy у читателя активен"
        arr = _restore_one(w, r)
        assert arr is not None and not arr.flags.owndata, "предпосылка: прочитан view"
        assert r.bytes_mapped == FRAME_BYTES
        assert r.bytes_read == 0, "view засчитан как копия"
        del arr
    finally:
        _close(r, w, mmr, mmw)


def test_t45e_copy_read_counts_read_not_mapped() -> None:
    mmw, mmr, w, r = _pair(reader_zero_copy=False)
    try:
        arr = _restore_one(w, r)
        assert arr is not None and arr.flags.owndata, "предпосылка: прочитана копия"
        assert r.bytes_read == FRAME_BYTES
        assert r.bytes_mapped == 0
        del arr
    finally:
        _close(r, w, mmr, mmw)


def test_t45e_stats_and_telemetry_carry_mapped(zero_copy_env) -> None:
    mmw, mmr, w, r = _pair(reader_zero_copy=True)
    try:
        router = T._router_with(r)
        arr = _restore_one(w, r)
        assert router.get_shm_stats()["shm_bytes_mapped"] == FRAME_BYTES
        assert router.get_shm_stats()["shm_bytes_read"] == 0
        tel = build_router_shm_telemetry(router)
        assert (tel["bytes_mapped"], tel["bytes_read"]) == (FRAME_BYTES, 0)
        del arr
    finally:
        _close(r, w, mmr, mmw)
