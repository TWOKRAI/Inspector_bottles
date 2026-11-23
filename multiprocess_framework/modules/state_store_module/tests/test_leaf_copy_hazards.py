"""П3 (Task 2.8a) — hazards автора ``LeafCopy`` сверх слепых тестов.

Слепые H1-H3 и H6 лежат в ``test_leaf_copy.py`` / ``test_read_model_leaf_copy.py``.
Здесь — то, что слепые не покрывают: индекс не течёт (``_kids``), сырая запись
видна индексу, сосед с общим строковым префиксом, ресинк с окном, открытым ДРУГОЙ
дельтой, и обслуживание номеров/истории read-model при замене поддерева.
"""

from __future__ import annotations

import sys
import threading
import time

import pytest

from multiprocess_framework.modules.state_store_module.core.delta import MISSING
from multiprocess_framework.modules.state_store_module.core.leaf_copy import LeafCopy, project_leaves
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy
from multiprocess_framework.modules.telemetry_readmodel_module import TelemetryReadModel

from .test_resync_offthread_hazards import _d, _Stand
from .test_state_proxy import MockRouter


def _in_daemon(fn, deadline: float = 5.0) -> None:
    """Вызвать ``fn`` в потоке-демоне; не уложился в дедлайн — тест падает, а не виснет."""
    box: list[BaseException] = []

    def target() -> None:
        try:
            fn()
        except BaseException as exc:  # noqa: BLE001 - пробрасываем в поток теста
            box.append(exc)

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(deadline)
    assert not t.is_alive(), f"вызов завис дольше {deadline} с"
    if box:
        raise box[0]


def _race(write_once, read_once, seconds: float = 1.0) -> None:
    """Писатель и читатель в потоках-демонах; любое исключение читателя — красный тест."""
    errors: list[str] = []
    stop = threading.Event()

    def writer() -> None:
        while not stop.is_set():
            write_once()

    def reader() -> None:
        while not stop.is_set():
            try:
                read_once()
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))
                return

    threads = [threading.Thread(target=writer, daemon=True), threading.Thread(target=reader, daemon=True)]
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for t in threads:
            t.start()
        time.sleep(seconds)
        stop.set()
        for t in threads:
            t.join(5.0)
    finally:
        sys.setswitchinterval(old)
    assert not any(t.is_alive() for t in threads), "поток гонки завис"
    assert errors == [], errors[:3]


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


# --------------------------------------------------------------------------- #
#  ревью П3 (1): пустой путь — отказ, а не зависание                           #
# --------------------------------------------------------------------------- #


def test_empty_path_is_rejected_loudly_instead_of_hanging():
    def scenario() -> None:
        copy = LeafCopy()
        with pytest.raises(ValueError):
            copy.put("", 1)
        with pytest.raises(ValueError):
            copy.put("", {"a": 1})
        with pytest.raises(ValueError):
            copy[""] = 1
        copy.put("a.b", 1)
        assert copy.drop("") == []  # корень не сносит копию
        assert dict(copy) == {"a.b": 1}

    _in_daemon(scenario)


# --------------------------------------------------------------------------- #
#  ревью П3 (2): копия целиком — одним вызовом, читатель не ловит KeyError      #
# --------------------------------------------------------------------------- #


def test_copy_returns_plain_dict_with_same_leaves():
    copy = LeafCopy()
    copy.put("a.n", {"x": 1, "y": 2})
    snap = copy.copy()
    assert type(snap) is dict
    assert snap == {"a.n.x": 1, "a.n.y": 2}
    snap["z"] = 3  # копия независима
    assert "z" not in copy


def _preloaded_copy() -> LeafCopy:
    copy = LeafCopy()
    for i in range(200):
        copy[f"p.x{i}.v"] = i
    return copy


def test_leaf_copy_copy_survives_concurrent_replace():
    copy = _preloaded_copy()

    def write() -> None:
        copy.drop("w")
        copy.put("w", {f"k{i}": i for i in range(20)})

    _race(write, copy.copy)


def test_read_model_full_snapshot_survives_concurrent_replace():
    m = TelemetryReadModel()
    for i in range(200):
        m.ingest(f"p.x{i}.v", i)

    def write() -> None:
        m.ingest("w", None, deleted=True)
        m.ingest("w", {f"k{i}": i for i in range(20)})

    _race(write, lambda: m.snapshot(""))


def test_state_proxy_cache_survives_concurrent_replace():
    proxy = StateProxy("camera_0", router=MockRouter())
    for i in range(200):
        proxy._cache[f"p.x{i}.v"] = i
    gone = [_d("w", MISSING, revision=0)]
    put = [_d("w", {f"k{i}": i for i in range(20)}, revision=0)]

    def write() -> None:
        proxy._update_cache(gone)
        proxy._update_cache(put)

    _race(write, lambda: proxy.cache)


# --------------------------------------------------------------------------- #
#  ревью П3 (3): лист и его ребёнок вместе — проекция не падает                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "leaves",
    [
        {"a.n": 5, "a.n.x": 1},  # предок вставлен раньше ребёнка
        {"a.n.x": 1, "a.n": 5},  # ребёнок вставлен раньше предка
    ],
    ids=["ancestor_first", "child_first"],
)
def test_leaf_ancestor_wins_over_its_children_in_projection(leaves):
    assert project_leaves("a.*", leaves) == [("a.n", 5)]


def test_leaf_ancestor_wins_over_nested_child_below_the_node():
    assert project_leaves("a.*", {"a.n.x": 1, "a.n.x.y": 2, "a.n.z": 3}) == [("a.n", {"x": 1, "z": 3})]


def test_poll_snapshot_leaf_under_leaf_does_not_break_projection():
    """Сценарий ревью: опрос кладёт ребёнка рядом с листом (сырая запись) — привязка не падает."""
    m = TelemetryReadModel()
    m.ingest("a.n", 5)
    assert m.ingest_poll_snapshot({"a.n.x": 1}, requested_at_seq=m.write_seq) == ["a.n.x"]
    assert project_leaves("a.*", m.snapshot("a")) == [("a.n", 5)]


# --------------------------------------------------------------------------- #
#  ревью П3 (5): скаляр поверх поддерева в окне ресинка                         #
# --------------------------------------------------------------------------- #


def test_scalar_over_subtree_in_the_window_is_not_undone_by_an_old_snapshot():
    stand = _Stand("scalar_in_window")
    try:
        stand.deliver([_d("foo.n", {"x": 0, "y": 5}, revision=1, old=MISSING)], first_revision=1, revision=1)
        stand.deliver([_d("foo.bar", 2, revision=5, old=MISSING)], first_revision=5, revision=5)
        assert stand.proxy._resync_inflight_id is not None, "окно ресинка не открыто — сценарий не воспроизведён"
        stand.deliver([_d("foo.n", 99, revision=6, old={"x": 0, "y": 5})], first_revision=6, revision=6)
        assert dict(stand.proxy.cache) == {"foo.bar": 2, "foo.n": 99}

        stand.answer_resync({"foo": {"bar": 2, "n": {"x": 0, "y": 5}}}, revision=5)
        cache = dict(stand.proxy.cache)
    finally:
        stand.close()

    assert cache == {"foo.bar": 2, "foo.n": 99}, cache


# --------------------------------------------------------------------------- #
#  ревью П3 (6): пустое множество детей не остаётся в индексе                   #
# --------------------------------------------------------------------------- #


def test_raw_leaf_that_lost_its_only_child_keeps_no_empty_set_in_index():
    copy = LeafCopy()
    copy["a"] = 1
    copy["a.b"] = 2
    del copy["a.b"]
    assert copy._kids == {"": {"a"}}
    del copy["a"]
    assert copy._kids == {}


# --------------------------------------------------------------------------- #
#  ревью П3 (7): record_history=False и лист-предок в put                       #
# --------------------------------------------------------------------------- #


def test_ingest_without_record_history_updates_snapshot_but_not_ring():
    m = TelemetryReadModel(tracked_suffixes=("x_mm",), clock=lambda: 1.0)
    m.ingest("r.s.x_mm", 5.0, record_history=False)
    m.ingest("r.d", {"x_mm": 6.0}, record_history=False)
    assert m.snapshot("r") == {"r.s.x_mm": 5.0, "r.d.x_mm": 6.0}
    assert m.history("r.s.x_mm") == []
    assert m.history("r.d.x_mm") == []


def test_put_over_leaf_ancestor_reports_it_removed_and_read_model_cleans_it():
    copy = LeafCopy()
    copy.put("a", 5)
    assert copy.put("a.b", 1) == (["a.b"], ["a"])

    m = TelemetryReadModel(tracked_suffixes=("x_mm",), clock=lambda: 1.0)
    m.ingest("r.x_mm", 10.0)  # лист-предок с историей и номером записи
    m.ingest("r.x_mm.v", 1.0)  # ребёнок снимает предка
    assert m.snapshot("r") == {"r.x_mm.v": 1.0}
    assert m.history("r.x_mm") == []
    # Номера записи у снятого предка нет: ответ опроса, снятый до всех записей, принимается.
    assert m.ingest_poll_snapshot({"r.x_mm": 3.0}, requested_at_seq=0) == ["r.x_mm"]


def test_read_model_ingest_of_empty_path_does_not_raise_and_changes_nothing():
    """Контракт ``ingest``: пустой путь не бросает (``test_short_paths_do_not_raise``); копия его не хранит."""
    m = TelemetryReadModel()
    before = m.write_seq
    m.ingest("", 1.0)
    m.ingest("", {"a": 1})
    assert m.snapshot("") == {}
    assert m.write_seq == before


# --------------------------------------------------------------------------- #
#  ревью Opus (m1): одна раскладка dict -> листья                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({}, []),
        ({"a": {"b": 1, "c": {"d": 2}}}, [("p.a.b", 1), ("p.a.c.d", 2)]),
        (5, [("p", 5)]),
        ([1, 2], [("p", [1, 2])]),
        ({"x": 1, "y": {}, "z": {"w": [3]}, "k": None}, [("p.x", 1), ("p.z.w", [3]), ("p.k", None)]),
    ],
    ids=["empty_dict", "nested", "scalar", "list_value", "mixed"],
)
def test_one_flattening_for_cache_and_resync_journal(value, expected):
    """Литералы прежнего поведения ``_expand_leaf_paths`` / ``_cache_put`` на пяти входах ревью."""
    assert StateProxy._expand_leaf_paths("p", value) == [path for path, _ in expected]
    copy = LeafCopy()
    copy.put("p", value)
    assert dict(copy) == dict(expected)
    assert list(copy) == [path for path, _ in expected]


# --------------------------------------------------------------------------- #
#  ревью П3 раунд 2: R2-1 цена защиты окна, R2-2, R2-3                          #
# --------------------------------------------------------------------------- #


def _proxy_with_cache(n_leaves: int) -> StateProxy:
    proxy = StateProxy("camera_0", router=MockRouter())
    for i in range(n_leaves):
        proxy._cache[f"processes.p{i % 12}.plugins.x{i}.v"] = i
    proxy._resync_inflight_id = "window"  # окно ресинка «открыто»: _update_cache ведёт журнал
    return proxy


def test_r2_1_protector_cost_does_not_grow_with_window_roots():
    """500 скалярных замен узлов в окне, затем снимок на кэше 12 000: < 300 мс (было 1362 мс)."""
    proxy = _proxy_with_cache(12_000)
    # Скаляры на УЗЛАХ с детьми (…xI имеет лист …xI.v): каждому нужен корень в журнале.
    deltas = [_d(f"processes.p{i % 12}.plugins.x{i}", i, revision=10 + i, old=MISSING) for i in range(500)]
    proxy._update_cache(deltas)
    assert len(proxy._resync_dirty_deletes) == 500, "корни не поставлены — сценарий не воспроизведён"
    protected = proxy._make_resync_protector(dict(proxy._resync_dirty), dict(proxy._resync_dirty_deletes), 5)
    box: list[float] = []

    def apply() -> None:
        t0 = time.perf_counter()
        proxy._apply_resync_snapshot(["processes.**"], {}, protected=protected)
        box.append(time.perf_counter() - t0)

    _in_daemon(apply, deadline=15.0)
    assert box[0] < 0.3, f"применение снимка заняло {box[0] * 1000:.0f} мс, ожидалось < 300 мс"
    assert len(proxy._cache) == 500, "замененные узлы под защитой, остальное снято снимком"


def test_r2_1_scalar_without_children_does_not_set_a_root_and_scalar_with_children_does():
    proxy = _proxy_with_cache(0)
    proxy._cache["foo.leaf"] = 1
    proxy._cache["foo.node.v"] = 2
    proxy._update_cache([_d("foo.leaf", 5, revision=7, old=1), _d("foo.node", 6, revision=8, old=MISSING)])
    assert proxy._resync_dirty == {"foo.leaf": 7}  # лист без детей — только в журнале записей
    assert proxy._resync_dirty_deletes == {"foo.node": 8}  # узел с детьми — корень, без дубля в записях


def test_r2_1_protector_uses_prefix_boundary_and_revision():
    proxy = _proxy_with_cache(0)
    protect = proxy._make_resync_protector({}, {"foo.n": 6}, 5)
    assert protect("foo.n") and protect("foo.n.x.y")
    assert not protect("foo.n2.x") and not protect("foo")
    # Корень старше снимка — побеждает снимок.
    assert not proxy._make_resync_protector({}, {"foo.n": 4}, 5)("foo.n.x")


def test_r2_2_poll_snapshot_ignores_empty_path_like_ingest():
    m = TelemetryReadModel()
    assert m.ingest_poll_snapshot({"": 1, "a.b": 2}, requested_at_seq=m.write_seq) == ["a.b"]
    assert m.snapshot("") == {"a.b": 2}


def test_r2_3_scalar_leaf_ancestor_is_given_under_doublestar_with_its_children():
    assert project_leaves("a.**", {"a.n": 5, "a.n.x": 1}) == [("a.n", 5), ("a.n.x", 1)]
    assert project_leaves("a.**", {"a.n.x": 1, "a.n": 5}) == [("a.n.x", 1), ("a.n", 5)]
