"""RED-тесты П3 (Task 2.8a2): проекция копии-листьев на шаблон.

Контракт (`core/leaf_copy.py`):
  - ``project_leaves(pattern, leaves) -> list[(путь, значение)]``: пары по путям,
    которые матчит шаблон; узел приходит целиком (dict, собранный из листьев),
    если шаблон не матчит его потомков, иначе приходят потомки; порядок — по
    первому листу узла в ``leaves``;
  - ``paths_with_matched_descendants(pairs) -> set[str]``: пути, у которых среди
    ``pairs`` есть потомок; корень ``""`` входит при хотя бы одном непустом пути.

Ожидаемые значения — литералы, не выводятся из кода.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.state_store_module.core.leaf_copy import (
    paths_with_matched_descendants,
    project_leaves,
)

# Копия-листья L; порядок вставки — ровно такой.
_L = {
    "system.run.state": "fault",
    "system.run.last_fault.at": 100.0,
    "system.run.last_fault.acknowledged_at": None,
    "devices.state.robot_main.conn.conn": "connected",
    "devices.state.robot_main.conn.ts": 7,
    "devices.state.belt.conn.conn": "connected",
    "devices.state.belt.conn.ts": 3,
}


@pytest.mark.timeout(10)
def test_star_gives_node_dict():
    """`system.run.*`: лист-сосед отдельно, узел last_fault целиком dict-ом."""
    assert project_leaves("system.run.*", _L) == [
        ("system.run.state", "fault"),
        ("system.run.last_fault", {"at": 100.0, "acknowledged_at": None}),
    ]


@pytest.mark.timeout(10)
def test_star_mid_gives_two_conn_dicts():
    """`devices.state.*.conn`: два узла conn целиком, в порядке первого листа."""
    assert project_leaves("devices.state.*.conn", _L) == [
        ("devices.state.robot_main.conn", {"conn": "connected", "ts": 7}),
        ("devices.state.belt.conn", {"conn": "connected", "ts": 3}),
    ]


@pytest.mark.timeout(10)
def test_tail_doublestar_gives_leaves():
    """`system.**` матчит потомков каждого узла -> приходят листья, не узлы."""
    assert project_leaves("system.**", _L) == [
        ("system.run.state", "fault"),
        ("system.run.last_fault.at", 100.0),
        ("system.run.last_fault.acknowledged_at", None),
    ]


@pytest.mark.timeout(10)
def test_head_doublestar_conn_loses_ts():
    """`**.conn` матчит только листья с именем conn; соседний лист ts не приходит."""
    assert project_leaves("**.conn", _L) == [
        ("devices.state.robot_main.conn.conn", "connected"),
        ("devices.state.belt.conn.conn", "connected"),
    ]


@pytest.mark.timeout(10)
def test_mid_doublestar():
    """`a.**.b`: матчится только путь, оканчивающийся на b; `a.x.b.d` не матчится."""
    assert project_leaves("a.**.b", {"a.x.b.c.b": 1, "a.x.b.d": 2}) == [("a.x.b.c.b", 1)]


@pytest.mark.timeout(10)
def test_paths_with_matched_descendants_exact():
    """Предки пар, включая корень `""`; сами листья и соседи не входят."""
    pairs = [("p.q.r.s1", 1), ("p.q.r.s2", 2), ("p.q.t", 3)]
    assert paths_with_matched_descendants(pairs) == {"", "p", "p.q", "p.q.r"}
