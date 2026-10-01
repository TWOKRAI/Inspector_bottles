# -*- coding: utf-8 -*-
"""Task 4.7a (P-2) — авторские тесты опасных мест механизма «дверь проверяет входы, только если
трогала чужую память». Слепой набор (``test_t47a_door_owndata.py``) закрывает контракт; здесь —
то, что видно только изнутри:

* «чужая память» (корень цепочки ``.base`` не владеющий ndarray) определяется ДО ``_write_item_arrays``
  (он вынимает массивы из item) — иначе крупный срез входа, ушедший в кольцо, не оставит следа и
  дверь пропустит устаревший кадр;
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
    extra: dict = {}
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
    sender = FrameShmMiddleware(None, owner="C", slot="output_frames", coll=3)
    crop = received["frame"][:8, :8]
    item = _output(received, crop=crop, mask=_arr("mask", 7))

    out = sender.strip_and_write(item)

    assert not out.get("_shm_dropped")
    assert "_shm_views" not in out
    assert out["crop"] is crop and out["mask"].shape == SHAPES["mask"]
    assert sender.frame_stale_drops == 0


# ----------------------------------------------------------------------- _copy_inline_views -> bool
def test_copy_inline_views_returns_true_only_when_copied():
    own = np.zeros((4, 4), dtype=np.uint8)
    own_view = np.zeros((16, 16), dtype=np.uint8)[:4, :4]  # свой view: корень .base — ndarray
    foreign = np.frombuffer(bytearray(64), dtype=np.uint8)[:16]  # корень — bytearray, не ndarray

    only_own = {"a": own, "ov": own_view, "s": "x", "n": 1}
    assert FrameShmMiddleware._copy_inline_views(only_own) is False
    assert only_own["a"] is own and only_own["ov"] is own_view

    with_view = {"a": own, "v": foreign}
    assert FrameShmMiddleware._copy_inline_views(with_view) is True
    assert with_view["a"] is own
    assert with_view["v"].flags.owndata and with_view["v"] is not foreign


# ------------------------------------------ свои view плагина vs чужой слот (ревью A-1, корень .base)
def _own_views(received: dict) -> dict:
    own = received["frame"].copy()  # владелец данных, вне слота входа
    return {
        "reshape": own.reshape(-1, 3),  # крупный: уйдёт в кольцо
        "slice_of_copy": own[:8, :8],  # малый inline-срез собственной копии
        "expand": own[:8, :8, 0][..., None],  # [..., None] от собственного среза
        "small_view": own.reshape(-1)[:64],
    }


@pytest.mark.parametrize("name", ["reshape", "slice_of_copy", "expand", "small_view"])
def test_own_view_output_not_dropped_on_stale_input(made, name):
    """Собственные view плагина (корень .base — ndarray) не зависят от слота входа: при перезаписанном
    входе item уходит, stale не растёт. ``flags.owndata`` давал здесь ложный дроп."""
    writer, sender, received = _received(made)
    arr = _own_views(received)[name]
    assert not arr.flags.owndata, "стенд неисправен: нужен именно view"
    item = _output(received, out=arr)
    _overwrite_input(writer)

    out = _send(sender, item)

    assert out is not None, f"собственный view {name!r} дропнут из-за перезаписи входа"
    assert sender.frame_stale_drops == 0


def test_foreign_reshaped_slice_via_real_shm_view_dropped(made):
    """Парный случай: срез ЧУЖОГО слота (через reshape — цепочка .base длиннее одного звена) +
    перезаписанный вход -> дроп. Корень цепочки — не ndarray."""
    writer, sender, received = _received(made)
    arr = received["frame"].reshape(-1)[:64]
    assert FrameShmMiddleware._views_foreign_memory(arr)
    item = _output(received, out=arr)
    _overwrite_input(writer)

    assert _send(sender, item) is None
    assert sender.frame_stale_drops == 1


def test_ndarray_root_without_owndata_counts_as_foreign_memory():
    """N-2: корень цепочки ``.base`` — ndarray, но ``owndata=False`` и ``base is None`` (view из
    C-расширения без base): память он не владеет -> чужая. Такой ndarray из чистого Python не собрать
    (``np.ndarray(buffer=...)`` всегда ставит base), поэтому имитируем подклассом, у которого ``base`` и
    ``flags`` переопределены — ``_views_foreign_memory`` читает именно эти два атрибута.
    """

    class _NoBaseNoOwn(np.ndarray):
        @property
        def base(self):  # noqa: D102
            return None

        @property
        def flags(self):  # noqa: D102
            class _F:
                owndata = False

            return _F()

    root = np.zeros(8, dtype=np.uint8).view(_NoBaseNoOwn)
    assert FrameShmMiddleware._views_foreign_memory(root) is True
    # контроль: обычный владеющий массив и его срез — свои
    own = np.zeros(8, dtype=np.uint8)
    assert FrameShmMiddleware._views_foreign_memory(own) is False
    assert FrameShmMiddleware._views_foreign_memory(own[2:5]) is False
