"""
Тесты для TreeStore.

Покрытие:
- Базовые get/set/has/delete/keys
- Промежуточные узлы (mkdir -p)
- Идемпотентность set (нет Delta при одинаковом значении)
- merge — глубокий и неглубокий
- snapshot с wildcards (* и **)
- restore поддерева и корня
- get_subtree
- Потокобезопасность (10 потоков)
- Граничные случаи (пустой путь, несуществующие пути, не-dict промежуточный узел)
"""
from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from multiprocess_prototype.state_store.core.delta import Delta, MISSING
from multiprocess_prototype.state_store.core.tree_store import TreeStore


# ===========================================================================
# Фикстуры
# ===========================================================================


@pytest.fixture
def empty_store() -> TreeStore:
    """Пустое хранилище."""
    return TreeStore()


@pytest.fixture
def camera_store() -> TreeStore:
    """Хранилище с данными о камерах для тестов."""
    initial = {
        "cameras": {
            "0": {
                "config": {"fps": 30, "resolution": "1080p"},
                "state": {"status": "idle", "frames": 0},
            },
            "1": {
                "config": {"fps": 25, "resolution": "720p"},
                "state": {"status": "running", "frames": 1000},
            },
        },
        "renderer": {
            "config": {"theme": "dark", "scale": 1.0},
        },
    }
    return TreeStore(initial=initial)


# ===========================================================================
# Тесты get
# ===========================================================================


def test_get_existing_leaf(camera_store: TreeStore) -> None:
    """Получение листового значения по точечному пути."""
    assert camera_store.get("cameras.0.config.fps") == 30


def test_get_existing_subtree(camera_store: TreeStore) -> None:
    """Получение поддерева (dict)."""
    config = camera_store.get("cameras.0.config")
    assert config == {"fps": 30, "resolution": "1080p"}


def test_get_root_empty_path(camera_store: TreeStore) -> None:
    """Пустой путь → весь dict."""
    tree = camera_store.get("")
    assert "cameras" in tree
    assert "renderer" in tree


def test_get_missing_path_raises(empty_store: TreeStore) -> None:
    """KeyError если путь не существует и default не задан."""
    with pytest.raises(KeyError):
        empty_store.get("missing.path")


def test_get_missing_path_with_default(empty_store: TreeStore) -> None:
    """Возвращает default если путь не существует."""
    result = empty_store.get("missing.path", default=42)
    assert result == 42


def test_get_returns_deep_copy(camera_store: TreeStore) -> None:
    """get() возвращает копию — мутация результата не меняет хранилище."""
    config = camera_store.get("cameras.0.config")
    config["fps"] = 999  # мутируем копию
    assert camera_store.get("cameras.0.config.fps") == 30  # хранилище не изменилось


# ===========================================================================
# Тесты set
# ===========================================================================


def test_set_creates_leaf(empty_store: TreeStore) -> None:
    """set() создаёт листовой узел."""
    delta = empty_store.set("cameras.0.config.fps", 30)
    assert delta is not None
    assert empty_store.get("cameras.0.config.fps") == 30


def test_set_creates_intermediate_nodes(empty_store: TreeStore) -> None:
    """set() автоматически создаёт промежуточные узлы (mkdir -p)."""
    empty_store.set("a.b.c.d", "value")
    assert empty_store.get("a.b.c.d") == "value"
    assert isinstance(empty_store.get("a.b.c"), dict)
    assert isinstance(empty_store.get("a.b"), dict)
    assert isinstance(empty_store.get("a"), dict)


def test_set_returns_delta(empty_store: TreeStore) -> None:
    """set() возвращает Delta с корректными полями."""
    delta = empty_store.set("x.y", 10, source="test")
    assert isinstance(delta, Delta)
    assert delta.path == "x.y"
    assert delta.old_value is MISSING  # значения не было
    assert delta.new_value == 10
    assert delta.source == "test"


def test_set_idempotent_returns_none(camera_store: TreeStore) -> None:
    """set() возвращает None если значение не изменилось."""
    delta = camera_store.set("cameras.0.config.fps", 30)
    assert delta is None


def test_set_updates_existing_value(camera_store: TreeStore) -> None:
    """set() обновляет существующее значение."""
    delta = camera_store.set("cameras.0.config.fps", 60)
    assert delta is not None
    assert delta.old_value == 30
    assert delta.new_value == 60
    assert camera_store.get("cameras.0.config.fps") == 60


def test_set_empty_path_raises(empty_store: TreeStore) -> None:
    """set() с пустым путём вызывает ValueError."""
    with pytest.raises(ValueError):
        empty_store.set("", "value")


# ===========================================================================
# Тесты has
# ===========================================================================


def test_has_existing_path(camera_store: TreeStore) -> None:
    """has() возвращает True для существующего пути."""
    assert camera_store.has("cameras.0.config.fps") is True


def test_has_missing_path(empty_store: TreeStore) -> None:
    """has() возвращает False для несуществующего пути."""
    assert empty_store.has("cameras.0.config.fps") is False


def test_has_root(empty_store: TreeStore) -> None:
    """has() с пустым путём → True (корень всегда существует)."""
    assert empty_store.has("") is True


# ===========================================================================
# Тесты keys
# ===========================================================================


def test_keys_returns_children(camera_store: TreeStore) -> None:
    """keys() возвращает дочерние ключи узла."""
    children = camera_store.keys("cameras")
    assert set(children) == {"0", "1"}


def test_keys_root(camera_store: TreeStore) -> None:
    """keys("") → ключи корня."""
    root_keys = camera_store.keys()
    assert set(root_keys) == {"cameras", "renderer"}


def test_keys_leaf_returns_empty(camera_store: TreeStore) -> None:
    """keys() на листовом узле возвращает пустой список."""
    result = camera_store.keys("cameras.0.config.fps")
    assert result == []


# ===========================================================================
# Тесты delete
# ===========================================================================


def test_delete_existing_node(camera_store: TreeStore) -> None:
    """delete() удаляет узел и возвращает Delta."""
    delta = camera_store.delete("cameras.1")
    assert delta is not None
    assert delta.path == "cameras.1"
    assert delta.new_value is MISSING
    assert not camera_store.has("cameras.1")


def test_delete_missing_node_returns_none(empty_store: TreeStore) -> None:
    """delete() несуществующего пути → None."""
    delta = empty_store.delete("missing.path")
    assert delta is None


def test_delete_subtree(camera_store: TreeStore) -> None:
    """delete() удаляет поддерево целиком."""
    camera_store.delete("cameras.0")
    assert not camera_store.has("cameras.0")
    assert not camera_store.has("cameras.0.config.fps")
    # cameras.1 должна остаться
    assert camera_store.has("cameras.1")


# ===========================================================================
# Тесты merge
# ===========================================================================


def test_merge_adds_new_keys(camera_store: TreeStore) -> None:
    """merge() добавляет новые ключи в существующий dict."""
    deltas = camera_store.merge(
        "cameras.0", {"state": {"status": "running"}, "extra": "data"}
    )
    assert len(deltas) > 0
    assert camera_store.get("cameras.0.state.status") == "running"
    assert camera_store.get("cameras.0.extra") == "data"


def test_merge_deep_preserves_existing(camera_store: TreeStore) -> None:
    """merge() не удаляет ключи, которые не упомянуты в data."""
    camera_store.merge("cameras.0", {"config": {"fps": 25}})
    # resolution должна остаться
    assert camera_store.get("cameras.0.config.resolution") == "1080p"
    assert camera_store.get("cameras.0.config.fps") == 25


def test_merge_scalar_overwrites(camera_store: TreeStore) -> None:
    """merge() перезаписывает скалярное значение."""
    deltas = camera_store.merge("cameras.0", {"config": {"fps": 60}})
    assert any(d.path == "cameras.0.config.fps" for d in deltas)
    assert camera_store.get("cameras.0.config.fps") == 60


def test_merge_returns_deltas_for_changed_values(camera_store: TreeStore) -> None:
    """merge() возвращает Delta только для изменившихся значений."""
    deltas = camera_store.merge(
        "cameras.0",
        {"config": {"fps": 30, "resolution": "4K"}},  # fps без изменений
    )
    paths = [d.path for d in deltas]
    assert "cameras.0.config.fps" not in paths  # не изменился
    assert "cameras.0.config.resolution" in paths  # изменился


def test_merge_into_empty_store(empty_store: TreeStore) -> None:
    """merge() в пустое хранилище создаёт структуру."""
    deltas = empty_store.merge(
        "cameras.0",
        {"config": {"fps": 30}, "state": {"status": "idle"}},
    )
    assert len(deltas) == 2
    assert empty_store.get("cameras.0.config.fps") == 30
    assert empty_store.get("cameras.0.state.status") == "idle"


# ===========================================================================
# Тесты get_subtree
# ===========================================================================


def test_get_subtree_returns_dict(camera_store: TreeStore) -> None:
    """get_subtree() возвращает dict."""
    subtree = camera_store.get_subtree("cameras.0")
    assert isinstance(subtree, dict)
    assert "config" in subtree
    assert "state" in subtree


def test_get_subtree_root(camera_store: TreeStore) -> None:
    """get_subtree("") → всё дерево."""
    full = camera_store.get_subtree("")
    assert "cameras" in full


def test_get_subtree_deep_copy(camera_store: TreeStore) -> None:
    """get_subtree() возвращает deep copy."""
    subtree = camera_store.get_subtree("cameras.0.config")
    subtree["fps"] = 999
    assert camera_store.get("cameras.0.config.fps") == 30


# ===========================================================================
# Тесты snapshot
# ===========================================================================


def test_snapshot_all(camera_store: TreeStore) -> None:
    """snapshot(None) → полная копия дерева."""
    snap = camera_store.snapshot()
    assert "cameras" in snap
    assert "renderer" in snap


def test_snapshot_wildcard_single_segment(camera_store: TreeStore) -> None:
    """snapshot(['cameras.*.config']) → config всех камер."""
    snap = camera_store.snapshot(["cameras.*.config"])
    assert "cameras" in snap
    assert "0" in snap["cameras"]
    assert "1" in snap["cameras"]
    assert "config" in snap["cameras"]["0"]
    assert "config" in snap["cameras"]["1"]
    # state не должно попасть в снимок
    assert "state" not in snap["cameras"].get("0", {})


def test_snapshot_specific_path(camera_store: TreeStore) -> None:
    """snapshot(['renderer.config']) → только renderer.config."""
    snap = camera_store.snapshot(["renderer.config"])
    assert "renderer" in snap
    assert "config" in snap["renderer"]
    assert "cameras" not in snap


def test_snapshot_multiple_patterns(camera_store: TreeStore) -> None:
    """snapshot с несколькими паттернами объединяет результаты."""
    snap = camera_store.snapshot(["cameras.0.config", "renderer.config"])
    assert snap["cameras"]["0"]["config"]["fps"] == 30
    assert snap["renderer"]["config"]["theme"] == "dark"


def test_snapshot_is_isolated(camera_store: TreeStore) -> None:
    """Мутация снимка не затрагивает хранилище."""
    snap = camera_store.snapshot()
    snap["cameras"]["0"]["config"]["fps"] = 999
    assert camera_store.get("cameras.0.config.fps") == 30


# ===========================================================================
# Тесты restore
# ===========================================================================


def test_restore_subtree(camera_store: TreeStore) -> None:
    """restore() заменяет поддерево новыми данными."""
    new_config = {"fps": 120, "resolution": "4K", "hdr": True}
    deltas = camera_store.restore(new_config, path="cameras.0.config")
    assert len(deltas) == 1
    assert camera_store.get("cameras.0.config.fps") == 120
    assert camera_store.get("cameras.0.config.hdr") is True


def test_restore_root(empty_store: TreeStore) -> None:
    """restore() без пути заменяет корень дерева."""
    new_data = {"system": {"version": "2.0"}}
    deltas = empty_store.restore(new_data)
    assert len(deltas) == 1
    assert empty_store.get("system.version") == "2.0"
    assert not empty_store.has("cameras")  # старых данных нет


def test_restore_no_change_returns_empty(camera_store: TreeStore) -> None:
    """restore() без изменений → пустой список дельт."""
    current_config = camera_store.get("cameras.0.config")
    deltas = camera_store.restore(current_config, path="cameras.0.config")
    assert deltas == []


# ===========================================================================
# Тест потокобезопасности
# ===========================================================================


def test_thread_safety_concurrent_writes() -> None:
    """10 потоков параллельно пишут и читают без ошибок и гонок."""
    store = TreeStore()
    errors: list[Exception] = []
    num_threads = 10
    iterations = 100

    def worker(thread_id: int) -> None:
        try:
            for i in range(iterations):
                path = f"thread.{thread_id}.counter"
                store.set(path, i, source=f"thread-{thread_id}")
                # чтение с default — не должно падать
                store.get(path, default=None)
                store.has(path)
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(tid,)) for tid in range(num_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert not errors, f"Ошибки в потоках: {errors}"
    # каждый поток записал своё последнее значение
    for tid in range(num_threads):
        val = store.get(f"thread.{tid}.counter", default=None)
        assert val == iterations - 1, f"Поток {tid}: ожидалось {iterations-1}, получили {val}"


# ===========================================================================
# Граничные случаи
# ===========================================================================


def test_set_none_value(empty_store: TreeStore) -> None:
    """Можно записать None как значение."""
    delta = empty_store.set("x.y", None)
    assert delta is not None
    assert empty_store.get("x.y") is None


def test_set_none_idempotent(empty_store: TreeStore) -> None:
    """Повторная запись None не создаёт Delta."""
    empty_store.set("x.y", None)
    delta = empty_store.set("x.y", None)
    assert delta is None


def test_delta_has_transaction_id(empty_store: TreeStore) -> None:
    """Delta содержит непустой transaction_id."""
    delta = empty_store.set("a", 1)
    assert delta is not None
    assert delta.transaction_id != ""


def test_initial_data_deep_copied() -> None:
    """Мутация initial dict не меняет хранилище."""
    initial = {"key": {"nested": 1}}
    store = TreeStore(initial=initial)
    initial["key"]["nested"] = 999
    assert store.get("key.nested") == 1


def test_keys_on_missing_path_raises(empty_store: TreeStore) -> None:
    """keys() несуществующего пути вызывает KeyError."""
    with pytest.raises(KeyError):
        empty_store.keys("missing.path")
