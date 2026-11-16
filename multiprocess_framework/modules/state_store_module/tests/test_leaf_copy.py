"""П3 (Task 2.8a) — слепые RED-тесты копии-листьев ``LeafCopy`` и её потребителя ``StateProxy``.

Контракт: ``core/leaf_copy.py`` (``LeafCopy``), ``StateProxy._cache`` хранит ``LeafCopy``.
``LeafCopy`` импортируется внутри тестов, а не на уровне модуля: тесты ``StateProxy``
(8, H5) должны падать по СОДЕРЖАНИЮ, а не по ``ImportError`` всего файла.

Hazards H1-H4 — только публичный API ``LeafCopy``; H5 — ресинк ``StateProxy`` с открытым окном.
"""

from __future__ import annotations

import time

import pytest

from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy

from .test_resync_offthread_hazards import _d, _Stand
from .test_state_proxy import MockRouter


def _new_copy():
    from multiprocess_framework.modules.state_store_module.core.leaf_copy import LeafCopy

    return LeafCopy()


# --------------------------------------------------------------------------- #
#  цена put — размер поддерева, а не размер копии                              #
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_put_cost_uses_index():
    """12 000 листьев в копии; ``put`` в маленькое поддерево стоит < 100 мкс в среднем."""
    copy = _new_copy()
    for i in range(12_000):
        copy[f"processes.p{i % 12}.plugins.x{i}.v"] = i
    assert len(copy) == 12_000, "копия не наполнена — сценарий не воспроизведён"

    calls = 200
    t0 = time.perf_counter()
    for i in range(calls):
        copy.put("devices.state.vfd1.status", {"running": True, "ts": float(i), "heartbeat": i})
    mean_sec = (time.perf_counter() - t0) / calls

    assert mean_sec < 100e-6, f"put стоит {mean_sec * 1e6:.1f} мкс на вызов, ожидалось < 100 мкс (индекс по префиксу)"
    # Якорь: put реально записал листья последней итерации.
    assert copy["devices.state.vfd1.status.heartbeat"] == 199


# --------------------------------------------------------------------------- #
#  StateProxy._cache хранит листья                                             #
# --------------------------------------------------------------------------- #


def test_state_proxy_dict_delta_replaces_subtree():
    """Вторая dict-дельта на тот же путь заменяет поддерево, а не дополняет его."""
    proxy = StateProxy("camera_0", router=MockRouter())
    proxy._update_cache(
        [
            Delta(path="a.n", old_value=MISSING, new_value={"x": 1, "y": 2}, source="hb"),
            Delta(path="a.n", old_value={"x": 1, "y": 2}, new_value={"x": 3}, source="hb"),
        ]
    )
    assert dict(proxy._cache) == {"a.n.x": 3}


# --------------------------------------------------------------------------- #
#  hazards LeafCopy (публичный API)                                            #
# --------------------------------------------------------------------------- #


def test_h1_leaf_ancestor_is_removed_when_child_is_written():
    """H1: лист-предок ``a`` снимается, когда пишут ``a.b``."""
    copy = _new_copy()
    copy.put("a", 5)
    copy.put("a.b", 1)
    assert dict(copy) == {"a.b": 1}


def test_h2_scalar_over_subtree_drops_subtree_and_leaf_is_droppable():
    """H2: скаляр на ``a`` снимает поддерево ``a.b``; потом ``drop("a")`` снимает ровно ``a``."""
    copy = _new_copy()
    copy.put("a.b", 1)
    copy.put("a", 5)
    assert dict(copy) == {"a": 5}
    assert copy.drop("a") == ["a"]


def test_h3_rewritten_leaf_keeps_insertion_position():
    """H3: лист, который есть и в старом, и в новом поддереве, держит свою позицию."""
    copy = _new_copy()
    copy.put("a.x", 1)
    copy.put("b", 2)
    copy.put("a", {"x": 3})
    assert list(copy) == ["a.x", "b"]
    assert copy["a.x"] == 3


def test_h4_put_after_drop_does_not_see_dropped_subtree():
    """H4: после ``drop("a")`` индекс чист — ``put("a", 2)`` не находит призраков ``a.b.c``."""
    copy = _new_copy()
    copy.put("a.b.c", 1)
    copy.drop("a")
    copy.put("a", 2)
    assert dict(copy) == {"a": 2}
    assert copy.drop("a") == ["a"]


# --------------------------------------------------------------------------- #
#  H5: ресинк StateProxy, окно открыто, dict-дельта заменила поддерево         #
# --------------------------------------------------------------------------- #


def test_h5_resync_snapshot_does_not_resurrect_leaf_removed_by_window_dict_delta():
    """Живая dict-дельта окна заменила ``n`` на ``{x: 3}``; снимок постарше с ``y`` не воскрешает ``y``.

    Стенд подписан на ``foo.**``, поэтому вместо литерального ``a`` из брифа — ``foo``
    (шаблон снимка ``foo.**``). К литералам брифа добавлен якорь ``foo.extra``: он
    доказывает, что снимок применён, а не выброшен целиком.
    """
    stand = _Stand("h5_leaf")
    try:
        # Кэш: foo.n.x = 0, foo.n.y = 5 (rev 1).
        stand.deliver(
            [_d("foo.n", {"x": 0, "y": 5}, revision=1, old=MISSING)],
            first_revision=1,
            revision=1,
        )
        assert dict(stand.proxy.cache) == {"foo.n.x": 0, "foo.n.y": 5}, "стартовый кэш не собран — стенд неисправен"

        # Живая dict-дельта rev 10 с разрывом (ожидался rev 2) — открывает окно ресинка.
        stand.deliver(
            [_d("foo.n", {"x": 3}, revision=10, old={"x": 0, "y": 5})],
            first_revision=10,
            revision=10,
        )
        assert stand.proxy._resync_inflight_id is not None, "окно ресинка не открыто — сценарий не воспроизведён"

        # Снимок rev 7 (старше дельты) — со старым y и посторонним якорем.
        stand.answer_resync({"foo": {"n": {"x": 0, "y": 5}, "extra": 42}}, revision=7)
        cache = dict(stand.proxy.cache)
    finally:
        stand.close()

    assert cache == {"foo.n.x": 3, "foo.extra": 42}, cache
