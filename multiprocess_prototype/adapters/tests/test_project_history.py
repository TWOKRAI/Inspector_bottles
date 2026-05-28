# -*- coding: utf-8 -*-
"""
adapters/tests/test_project_history.py — unit-тесты ProjectHistory (Task G.4.1).

Покрывает чистый snapshot-стек (без holder/repo/EventBus):
    1. record + take_undo/take_redo round-trip
    2. coalescing: одинаковый coalesce_key мержит записи (keep before первого)
    3. новая запись чистит redo-стек
    4. max_history overflow выбрасывает старейшие
    5. empty стек: take_* -> None, can_* -> False
    6. entries() возвращает HistoryEntry с label/command_type

Refs: plans/2026-05-27_cross-tab-architecture/phase-g.md (Task G.4.1)
"""

from __future__ import annotations

from multiprocess_prototype.adapters.dispatch.history import ProjectHistory
from multiprocess_prototype.domain.entities.project import Project
from multiprocess_prototype.domain.entities.topology import Topology
from multiprocess_prototype.domain.protocols import HistoryEntry


def _project(*process_names: str) -> Project:
    """Project с заданными процессами (для различимых снимков)."""
    topo = Topology.from_dict(
        {
            "processes": [{"process_name": n, "plugins": []} for n in process_names],
            "wires": [],
            "displays": [],
        }
    )
    return Project.from_topology(topo)


def _names(project: Project) -> set[str]:
    return {p.process_name for p in project.topology.processes}


# ---------------------------------------------------------------------------
# Тест 1: record + take_undo/take_redo round-trip
# ---------------------------------------------------------------------------


def test_record_and_undo_redo_roundtrip() -> None:
    hist = ProjectHistory()
    before = _project()
    after = _project("cam")

    assert hist.can_undo() is False
    hist.record(before=before, after=after, label="AddProcess: cam", command_type="AddProcess")
    assert hist.can_undo() is True
    assert hist.can_redo() is False

    # undo -> снимок before
    undone = hist.take_undo()
    assert undone is before
    assert _names(undone) == set()
    assert hist.can_undo() is False
    assert hist.can_redo() is True

    # redo -> снимок after
    redone = hist.take_redo()
    assert redone is after
    assert _names(redone) == {"cam"}
    assert hist.can_undo() is True
    assert hist.can_redo() is False


# ---------------------------------------------------------------------------
# Тест 2: coalescing — одинаковый ключ мержит, keep before первого
# ---------------------------------------------------------------------------


def test_coalescing_merges_same_key() -> None:
    hist = ProjectHistory()
    p0 = _project()
    p1 = _project("a")
    p2 = _project("a", "b")

    hist.record(before=p0, after=p1, label="edit", command_type="SetPluginConfig", coalesce_key="field:x")
    hist.record(before=p1, after=p2, label="edit", command_type="SetPluginConfig", coalesce_key="field:x")

    # Слились в одну запись
    assert len(hist.entries(50)) == 1

    # undo откатывает всю серию до самого первого before (p0)
    undone = hist.take_undo()
    assert undone is p0
    assert hist.can_undo() is False

    # redo восстанавливает последний after (p2)
    redone = hist.take_redo()
    assert redone is p2


def test_coalescing_different_key_keeps_separate() -> None:
    hist = ProjectHistory()
    p0, p1, p2 = _project(), _project("a"), _project("a", "b")
    hist.record(before=p0, after=p1, label="e1", command_type="SetPluginConfig", coalesce_key="field:x")
    hist.record(before=p1, after=p2, label="e2", command_type="SetPluginConfig", coalesce_key="field:y")
    assert len(hist.entries(50)) == 2


# ---------------------------------------------------------------------------
# Тест 3: новая запись чистит redo-стек
# ---------------------------------------------------------------------------


def test_new_record_clears_redo() -> None:
    hist = ProjectHistory()
    p0, p1, p2 = _project(), _project("a"), _project("b")

    hist.record(before=p0, after=p1, label="r1", command_type="AddProcess")
    hist.take_undo()
    assert hist.can_redo() is True

    # Новая запись после undo обнуляет redo
    hist.record(before=p0, after=p2, label="r2", command_type="AddProcess")
    assert hist.can_redo() is False


# ---------------------------------------------------------------------------
# Тест 4: max_history overflow
# ---------------------------------------------------------------------------


def test_max_history_overflow_drops_oldest() -> None:
    hist = ProjectHistory(max_history=3)
    for i in range(5):
        hist.record(
            before=_project(),
            after=_project(f"p{i}"),
            label=f"add p{i}",
            command_type="AddProcess",
        )
    entries = hist.entries(50)
    assert len(entries) == 3
    # Остались 3 последние (p2, p3, p4)
    assert [e.label for e in entries] == ["add p2", "add p3", "add p4"]


# ---------------------------------------------------------------------------
# Тест 5: empty стек — no-op
# ---------------------------------------------------------------------------


def test_empty_stack_noop() -> None:
    hist = ProjectHistory()
    assert hist.take_undo() is None
    assert hist.take_redo() is None
    assert hist.can_undo() is False
    assert hist.can_redo() is False
    assert hist.entries() == []


def test_clear() -> None:
    hist = ProjectHistory()
    hist.record(before=_project(), after=_project("a"), label="x", command_type="AddProcess")
    hist.take_undo()
    hist.clear()
    assert hist.can_undo() is False
    assert hist.can_redo() is False


# ---------------------------------------------------------------------------
# Тест 6: entries() -> HistoryEntry
# ---------------------------------------------------------------------------


def test_entries_returns_history_entry() -> None:
    hist = ProjectHistory()
    hist.record(before=_project(), after=_project("cam"), label="AddProcess: cam", command_type="AddProcess")
    entries = hist.entries()
    assert len(entries) == 1
    assert isinstance(entries[0], HistoryEntry)
    assert entries[0].label == "AddProcess: cam"
    assert entries[0].command_type == "AddProcess"
    assert entries[0].timestamp > 0
