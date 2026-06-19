# -*- coding: utf-8 -*-
"""
tests/test_snapshot_history.py -- контракт generic SnapshotHistory[T] (ADR ACT-002).

Покрывает чистый snapshot-стек на произвольном immutable-агрегате T (здесь _Doc):
    1. record + take_undo/take_redo round-trip (идентичность снимков)
    2. coalescing: одинаковый ключ мержит (keep before первого), разный — раздельно
    3. новая запись чистит redo-стек
    4. max_history overflow выбрасывает старейшие
    5. empty стек: take_* -> None, can_* -> False, entries() == []
    6. entries() -> SnapshotEntry с label/command_type/timestamp; n=0 -> все
    7. clear()
"""

from __future__ import annotations

from dataclasses import dataclass

from multiprocess_framework.modules.actions_module import SnapshotEntry, SnapshotHistory


@dataclass(frozen=True, slots=True)
class _Doc:
    """Произвольный immutable-агрегат для теста generic-стека."""

    value: str


def test_record_and_undo_redo_roundtrip() -> None:
    hist: SnapshotHistory[_Doc] = SnapshotHistory()
    before, after = _Doc("v0"), _Doc("v1")

    assert hist.can_undo() is False
    hist.record(before=before, after=after, label="edit", command_type="Set")
    assert hist.can_undo() is True
    assert hist.can_redo() is False

    undone = hist.take_undo()
    assert undone is before  # идентичность снимка, не копия
    assert hist.can_undo() is False
    assert hist.can_redo() is True

    redone = hist.take_redo()
    assert redone is after
    assert hist.can_undo() is True
    assert hist.can_redo() is False


def test_coalescing_merges_same_key() -> None:
    hist: SnapshotHistory[_Doc] = SnapshotHistory()
    p0, p1, p2 = _Doc("0"), _Doc("1"), _Doc("2")

    hist.record(before=p0, after=p1, label="e", command_type="Set", coalesce_key="x")
    hist.record(before=p1, after=p2, label="e", command_type="Set", coalesce_key="x")

    assert len(hist.entries(50)) == 1
    assert hist.take_undo() is p0  # откат всей серии до первого before
    assert hist.can_undo() is False
    assert hist.take_redo() is p2  # redo восстанавливает последний after


def test_coalescing_different_key_keeps_separate() -> None:
    hist: SnapshotHistory[_Doc] = SnapshotHistory()
    p0, p1, p2 = _Doc("0"), _Doc("1"), _Doc("2")
    hist.record(before=p0, after=p1, label="e1", command_type="Set", coalesce_key="x")
    hist.record(before=p1, after=p2, label="e2", command_type="Set", coalesce_key="y")
    assert len(hist.entries(50)) == 2


def test_new_record_clears_redo() -> None:
    hist: SnapshotHistory[_Doc] = SnapshotHistory()
    p0, p1, p2 = _Doc("0"), _Doc("1"), _Doc("2")

    hist.record(before=p0, after=p1, label="r1", command_type="Set")
    hist.take_undo()
    assert hist.can_redo() is True

    hist.record(before=p0, after=p2, label="r2", command_type="Set")
    assert hist.can_redo() is False


def test_max_history_overflow_drops_oldest() -> None:
    hist: SnapshotHistory[_Doc] = SnapshotHistory(max_history=3)
    for i in range(5):
        hist.record(before=_Doc("b"), after=_Doc(f"p{i}"), label=f"add p{i}", command_type="Set")
    entries = hist.entries(50)
    assert len(entries) == 3
    assert [e.label for e in entries] == ["add p2", "add p3", "add p4"]


def test_empty_stack_noop() -> None:
    hist: SnapshotHistory[_Doc] = SnapshotHistory()
    assert hist.take_undo() is None
    assert hist.take_redo() is None
    assert hist.can_undo() is False
    assert hist.can_redo() is False
    assert hist.entries() == []


def test_clear() -> None:
    hist: SnapshotHistory[_Doc] = SnapshotHistory()
    hist.record(before=_Doc("0"), after=_Doc("1"), label="x", command_type="Set")
    hist.take_undo()
    hist.clear()
    assert hist.can_undo() is False
    assert hist.can_redo() is False


def test_entries_returns_snapshot_entry() -> None:
    hist: SnapshotHistory[_Doc] = SnapshotHistory()
    hist.record(before=_Doc("0"), after=_Doc("1"), label="Set: x", command_type="Set")
    entries = hist.entries()
    assert len(entries) == 1
    assert isinstance(entries[0], SnapshotEntry)
    assert entries[0].label == "Set: x"
    assert entries[0].command_type == "Set"
    assert entries[0].timestamp > 0


def test_entries_n_zero_returns_all() -> None:
    hist: SnapshotHistory[_Doc] = SnapshotHistory()
    for i in range(4):
        hist.record(before=_Doc("b"), after=_Doc(f"p{i}"), label=f"e{i}", command_type="Set")
    assert len(hist.entries(0)) == 4  # n=0 → все (паритет с ActionBus.history/ProjectHistory)
