"""П3 (Task 2.8a) — hazards автора ``LeafCopy`` сверх слепых тестов.

Слепые H1-H3 и H6 лежат в ``test_leaf_copy.py`` / ``test_read_model_leaf_copy.py``.
Здесь — то, что слепые не покрывают: индекс не течёт (``_kids``), сырая запись
видна индексу, сосед с общим строковым префиксом, ресинк с окном, открытым ДРУГОЙ
дельтой, и обслуживание номеров/истории read-model при замене поддерева.
"""

from __future__ import annotations

from multiprocess_framework.modules.state_store_module.core.delta import MISSING
from multiprocess_framework.modules.state_store_module.core.leaf_copy import LeafCopy
from multiprocess_framework.modules.telemetry_readmodel_module import TelemetryReadModel

from .test_resync_offthread_hazards import _d, _Stand


# --------------------------------------------------------------------------- #
#  индекс не течёт                                                             #
# --------------------------------------------------------------------------- #


def test_h4_index_is_empty_after_drop():
    copy = LeafCopy()
    copy.put("a.b.c", 1)
    assert copy.drop("a") == ["a.b.c"]
    assert copy._kids == {}
    assert dict(copy) == {}


def test_index_is_empty_after_deleting_every_leaf_one_by_one():
    copy = LeafCopy()
    copy["a.b"] = 1
    copy["a.c.d"] = 2
    copy["e"] = 3
    for path in ("a.b", "e", "a.c.d"):
        del copy[path]
    assert copy._kids == {}


def test_index_keeps_branch_while_a_sibling_leaf_lives():
    copy = LeafCopy()
    copy["a.b"] = 1
    copy["a.c"] = 2
    del copy["a.b"]
    assert copy._leaves_under("a") == ["a.c"]
    assert copy._kids == {"": {"a"}, "a": {"a.c"}}


def test_index_is_empty_after_scalar_replaces_subtree():
    copy = LeafCopy()
    copy.put("a.b.c", 1)
    copy.put("a", 5)
    assert dict(copy) == {"a": 5}
    assert copy._kids == {"": {"a"}}


# --------------------------------------------------------------------------- #
#  сырая запись, граница-точка, возврат put                                     #
# --------------------------------------------------------------------------- #


def test_raw_setitem_is_visible_to_the_index():
    """Запись ``copy[path] = v`` в обход ``put`` (ресинк) не разводит индекс и данные."""
    copy = LeafCopy()
    copy["a.b.c"] = 1
    assert copy.put("a.b", {"x": 2}) == (["a.b.x"], ["a.b.c"])
    assert dict(copy) == {"a.b.x": 2}


def test_drop_does_not_touch_sibling_with_common_string_prefix():
    copy = LeafCopy()
    copy.put("p.capture", {"fps": 1})
    copy.put("p.capture2", {"fps": 2})
    assert copy.drop("p.capture") == ["p.capture.fps"]
    assert dict(copy) == {"p.capture2.fps": 2}


def test_put_returns_written_and_removed():
    copy = LeafCopy()
    assert copy.put("a.n", {"x": 1, "y": 2}) == (["a.n.x", "a.n.y"], [])
    assert copy.put("a.n", {"x": 3}) == (["a.n.x"], ["a.n.y"])
    assert copy.put("a.n", {}) == ([], ["a.n.x"])
    assert dict(copy) == {}


def test_drop_of_absent_path_returns_empty_and_keeps_copy():
    copy = LeafCopy()
    copy.put("a.b", 1)
    assert copy.drop("x.y") == []
    assert dict(copy) == {"a.b": 1}


# --------------------------------------------------------------------------- #
#  ресинк StateProxy: окно открыто ДРУГОЙ дельтой                               #
# --------------------------------------------------------------------------- #


def test_h5_window_dict_delta_replaces_subtree_and_old_snapshot_does_not_resurrect_leaf():
    """H5 по шаблону ADR-SS-022: окно открывает разрыв, dict-дельта приходит ВНУТРИ окна.

    В слепом H5 окно открывала сама dict-дельта; пакет, обнаруживший разрыв,
    применяется к кэшу ДО открытия окна (``on_state_changed``: сначала
    ``_update_cache``, потом ``_advance_revision_and_maybe_resync``), поэтому в
    журнал защиты не попадает — это поведение базы, не П3.

    Стартовый dict ``foo.n`` кладётся ДО окна: иначе его дельта в окне пометила бы
    лист ``y`` как изменённый, и защита корня dict-дельты (И6) осталась бы
    невидимой тесту.
    """
    stand = _Stand("h5_in_window")
    try:
        stand.deliver([_d("foo.n", {"x": 0, "y": 5}, revision=1, old=MISSING)], first_revision=1, revision=1)
        assert dict(stand.proxy.cache) == {"foo.n.x": 0, "foo.n.y": 5}, "стартовый кэш не собран"
        # Разрыв (ожидался rev 2): открывает окно ресинка.
        stand.deliver([_d("foo.bar", 2, revision=5, old=MISSING)], first_revision=5, revision=5)
        assert stand.proxy._resync_inflight_id is not None, "окно ресинка не открыто — сценарий не воспроизведён"
        # Живая dict-дельта ВНУТРИ окна заменяет поддерево: y снят, x = 3.
        stand.deliver([_d("foo.n", {"x": 3}, revision=6, old={"x": 0, "y": 5})], first_revision=6, revision=6)
        assert dict(stand.proxy.cache) == {"foo.bar": 2, "foo.n.x": 3}, "dict-дельта не заменила поддерево"

        # Снимок rev 5 (старше дельты) — со старым y и посторонним якорем.
        stand.answer_resync({"foo": {"bar": 2, "n": {"x": 0, "y": 5}, "extra": 42}}, revision=5)
        cache = dict(stand.proxy.cache)
    finally:
        stand.close()

    assert cache == {"foo.bar": 2, "foo.n.x": 3, "foo.extra": 42}, cache


# --------------------------------------------------------------------------- #
#  TelemetryReadModel: номера записей и история при замене поддерева           #
# --------------------------------------------------------------------------- #


def test_dict_delta_is_one_write_for_all_its_leaves():
    m = TelemetryReadModel()
    before = m.write_seq
    m.ingest("a.n", {"x": 1, "y": 2})
    assert m.write_seq == before + 1
    # Оба листа несут ОДИН номер: ответ опроса, снятый на этом номере, принимается.
    assert m.ingest_poll_snapshot({"a.n.x": 7, "a.n.y": 8}, requested_at_seq=before + 1) == ["a.n.x", "a.n.y"]
    # А снятый до дельты — отбрасывается целиком.
    assert m.ingest_poll_snapshot({"a.n.x": 9, "a.n.y": 9}, requested_at_seq=before) == []


def test_leaf_removed_by_dict_delta_loses_its_history_and_write_number():
    m = TelemetryReadModel(tracked_suffixes=("x_mm", "y_mm"), clock=lambda: 1.0)
    m.ingest("r.s.x_mm", 10.0)
    m.ingest("r.s.y_mm", 20.0)
    m.ingest("r.s", {"x_mm": 11.0})
    assert m.history("r.s.y_mm") == []
    assert m.history("r.s.x_mm") == [(1.0, 10.0), (1.0, 11.0)]
    # Номера записи у снятого листа нет: ответ опроса, снятый до всех записей, его принимает.
    assert m.ingest_poll_snapshot({"r.s.y_mm": 5.0}, requested_at_seq=0) == ["r.s.y_mm"]


def test_delete_subtree_purges_state_numbers_and_imported_history():
    m = TelemetryReadModel(tracked_suffixes=("x_mm",), clock=lambda: 1.0)
    m.ingest("r.s.x_mm", 10.0)
    m.import_history({"r.s.other": [(1.0, 2.0)], "r2.s.x_mm": [(1.0, 3.0)]})
    m.ingest("r.s", None, deleted=True)
    assert m.snapshot("") == {}
    assert m.history("r.s.x_mm") == []
    assert m.history("r.s.other") == []  # кольцо только от import_history чистится сканом
    assert m.history("r2.s.x_mm") == [(1.0, 3.0)]
    assert m._state._kids == {}
