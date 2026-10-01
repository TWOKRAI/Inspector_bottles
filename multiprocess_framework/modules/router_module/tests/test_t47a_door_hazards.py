# -*- coding: utf-8 -*-
"""Task 4.7a (P-2) — авторские тесты опасных мест механизма «дверь проверяет входы, только если
трогала чужую память». Слепой набор (``test_t47a_door_owndata.py``) закрывает контракт; здесь —
то, что видно только изнутри:

* флаги ``owndata`` снимаются ДО ``_write_item_arrays`` (он вынимает массивы из item) — иначе
  крупный срез входа, ушедший в кольцо, не оставит следа и дверь пропустит устаревший кадр;
* fan-out повтор item-а (один dict на несколько targets) не меняет вердикт;
* ``mm=None`` (pickle-by-design) — проверки входов не было и нет;
* ``_copy_inline_views`` возвращает bool «копировал» — на нём держится вторая половина условия.

Стенд — настоящие кольца, как в слепом наборе: писатель ``A``, отправитель ``B`` с zero-copy view.
"""

from __future__ import annotations

import gc
import os

import numpy as np
import pytest

from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import FrameShmMiddleware
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager

SHAPES = {"frame": (48, 64, 3), "mask": (100, 120)}  # оба >= 8192 Б -> уходят в кольцо ссылкой


@pytest.fixture(autouse=True)
def _clean_shm_flags(monkeypatch):
    for name in [k for k in os.environ if k.startswith("FW_SHM_")]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def made():
    items: list[tuple[FrameShmMiddleware, MemoryManager]] = []
    yield items
    gc.collect()
    for mw, mm in reversed(items):
        for fin in (mw.close_handle_cache, mw.release_owned_memory, mm.close_all):
            try:
                fin()
            except Exception:  # noqa: BLE001
                pass


def _mw(made, owner: str, *, view: bool = False) -> FrameShmMiddleware:
    mm = MemoryManager()
    extra = dict(owner_incarnation=True, cache_shm_handles=True, zero_copy=True) if view else {"zero_copy": False}
    mw = FrameShmMiddleware(mm, owner=owner, slot="output_frames", coll=3, **extra)
    made.append((mw, mm))
    return mw


def _arr(key: str, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 250, size=SHAPES[key]).astype(np.uint8)


def _send(mw: FrameShmMiddleware, item: dict):
    return mw.strip_data_frame_on_send({"target": "t", "type": "data", "channel": "data", "data": item})


def _received(made) -> tuple[FrameShmMiddleware, FrameShmMiddleware, dict]:
    writer, sender = _mw(made, "A"), _mw(made, "B", view=True)
    out = _send(writer, {"frame": _arr("frame", 1), "n": 1})
    msg = sender.restore_frame(out)
    item = dict(msg["data"])
    item["frame"] = msg["frame"]
    assert item["_shm_views"] and not item["frame"].flags.owndata, "стенд неисправен"
    return writer, sender, item


def _overwrite_input(writer: FrameShmMiddleware) -> None:
    for s in range(3):  # coll=3: кольцо обернулось -> ячейка первой записи перезаписана
        _send(writer, {"frame": _arr("frame", 100 + s)})


def _output(received: dict, **outputs) -> dict:
    return {"n": received["n"], "_shm_views": received["_shm_views"], **outputs}


# --------------------------------------------------------------------------- fan-out replay
def test_fanout_replay_of_owndata_output_not_dropped_on_either_send(made):
    """Один item-dict на два target-а: выход — крупный owndata-массив (уходит в кольцо ссылкой),
    вход перезаписан. Первый вызов отправляет без дропа, повтор (``_has_own_ref`` -> replay) не
    заводит метку ``_shm_dropped`` и не считает stale."""
    writer, sender, received = _received(made)
    item = _output(received, mask=_arr("mask", 7))
    _overwrite_input(writer)

    first = sender.strip_and_write(item)
    assert not first.get("_shm_dropped")
    assert "mask" in first["_shm_refs"]
    second = sender.strip_and_write(item)

    assert not second.get("_shm_dropped"), "fan-out повтор owndata-выхода помечен дропнутым"
    assert sender.frame_stale_drops == 0


def test_fanout_replay_of_dropped_view_output_stays_dropped(made):
    """Парный случай: выход со срезом входа + перезапись -> первый вызов метит ``_shm_dropped``,
    повтор на том же dict возвращает метку (дропает send-middleware), stale посчитан ОДИН раз."""
    writer, sender, received = _received(made)
    item = _output(received, crop=received["frame"][:8, :8])
    _overwrite_input(writer)

    assert sender.strip_and_write(item).get("_shm_dropped") is True
    assert sender.strip_and_write(item).get("_shm_dropped") is True
    assert sender.frame_stale_drops == 1


# ------------------------------------------------------- entries (кольцо) vs inline — раздельные пути
def test_view_in_ring_entry_alone_triggers_validation(made):
    """Ловушка порядка: единственный не-owndata массив — крупный проброшенный ``frame`` (view), он
    уходит в кольцо и ИСЧЕЗАЕТ из item до ``_copy_inline_views`` (тот ничего не скопирует: остаток —
    только owndata-``crop``). Если owndata-флаги снимать после ``_write_item_arrays``, дверь пропустит
    устаревший кадр. Ожидание: дроп, stale == 1."""
    writer, sender, received = _received(made)
    own_crop = received["frame"][:8, :8].copy()
    assert own_crop.flags.owndata
    item = _output(received, frame=received["frame"], crop=own_crop)
    _overwrite_input(writer)

    assert _send(sender, item) is None
    assert sender.frame_stale_drops == 1


def test_inline_view_slice_alone_triggers_validation_with_owndata_ring_entry(made):
    """Обратная половина условия: в кольцо ушёл owndata ``mask``, а inline остался срез входа —
    флаг даёт только ``_copy_inline_views`` (entries чисты). Ожидание: дроп, stale == 1."""
    writer, sender, received = _received(made)
    item = _output(received, mask=_arr("mask", 7), crop=received["frame"][:8, :8])
    _overwrite_input(writer)

    assert _send(sender, item) is None
    assert sender.frame_stale_drops == 1


def test_owndata_ring_entry_plus_owndata_inline_not_dropped(made):
    """Оба пути чисты (mask owndata в кольцо, crop owndata inline) + перезаписанный вход -> уходит."""
    writer, sender, received = _received(made)
    item = _output(received, mask=_arr("mask", 7), crop=received["frame"][:8, :8].copy())
    _overwrite_input(writer)

    out = _send(sender, item)

    assert out is not None
    assert "mask" in out["data"]["_shm_refs"]
    assert sender.frame_stale_drops == 0


# ------------------------------------------------------------------------------- mm=None
def test_mm_none_path_untouched(made):
    """``mm=None`` -> pickle-by-design: проверки входов нет ни до, ни после 4.7a. Массивы остаются
    в item (даже срез view — копии в этой ветке не делается), ``_shm_views`` снят, дропа нет."""
    _, _, received = _received(made)
    sender = FrameShmMiddleware(None, owner="C", slot="output_frames", coll=3, zero_copy=False)
    crop = received["frame"][:8, :8]
    item = _output(received, crop=crop, mask=_arr("mask", 7))

    out = sender.strip_and_write(item)

    assert not out.get("_shm_dropped")
    assert "_shm_views" not in out
    assert out["crop"] is crop and out["mask"].shape == SHAPES["mask"]
    assert sender.frame_stale_drops == 0


# ----------------------------------------------------------------------- _copy_inline_views -> bool
def test_copy_inline_views_returns_true_only_when_copied():
    base = np.zeros((16, 16), dtype=np.uint8)
    view = base[:4, :4]
    own = np.zeros((4, 4), dtype=np.uint8)

    only_own = {"a": own, "s": "x", "n": 1}
    assert FrameShmMiddleware._copy_inline_views(only_own) is False
    assert only_own["a"] is own

    with_view = {"a": own, "v": view}
    assert FrameShmMiddleware._copy_inline_views(with_view) is True
    assert with_view["a"] is own
    assert with_view["v"].flags.owndata and with_view["v"] is not view
