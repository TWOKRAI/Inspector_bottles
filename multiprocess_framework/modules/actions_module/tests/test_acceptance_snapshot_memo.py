# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты: непрозрачный memo записи SnapshotHistory (Task 1.1, A7/A8/A9).

Контракт (plans/undo-restores-selection.md, «Зафиксированный API SnapshotHistory»):
  - record(*, before, after, label, command_type, coalesce_key=None,
           memo_before=None, memo_after=None);
  - take_undo_with_memo() -> (before, memo_before) | None;
  - take_redo_with_memo() -> (after, memo_after) | None;
  - coalescing хранит memo_before ПЕРВОЙ записи серии и memo_after НОВОЙ;
  - memo живут только внутри записей: обрезка по max_history и clear() их отпускают;
  - take_undo()/take_redo() и вызовы без memo ведут себя как раньше.

Тест писался БЕЗ доступа к реализации: только контракт плана. Ожидаемые значения —
литералы, не вычисляются из кода под тестом. Memo непрозрачен — сравниваем по ``is``.

Refs: plans/undo-restores-selection.md (Task 1.1)
"""

from __future__ import annotations

import gc
import weakref

import pytest

from multiprocess_framework.modules.actions_module.snapshot_history import SnapshotHistory


class _Memo:
    """Крошечный непрозрачный memo: обычный класс, поддерживает weakref."""

    def __init__(self, tag: str) -> None:
        self.tag = tag


def _rec(h: SnapshotHistory, before, after, *, key=None, memo_before=None, memo_after=None) -> None:
    h.record(
        before=before,
        after=after,
        label="op",
        command_type="Op",
        coalesce_key=key,
        memo_before=memo_before,
        memo_after=memo_after,
    )


# ---------------------------------------------------------------------------
# Зафиксированный API: memo_before/memo_after в record, *_with_memo в навигации
# ---------------------------------------------------------------------------


def test_record_accepts_memo_and_undo_returns_memo_before() -> None:
    """undo возвращает пару (before, memo_before) именно записи, а не после-снимок."""
    h: SnapshotHistory[str] = SnapshotHistory()
    mb, ma = _Memo("до"), _Memo("после")
    _rec(h, "S0", "S1", memo_before=mb, memo_after=ma)

    got = h.take_undo_with_memo()

    assert got is not None
    snapshot, memo = got
    assert snapshot == "S0"
    assert memo is mb  # тот же объект, без копирования и подмены на memo_after


def test_redo_returns_memo_after() -> None:
    """redo возвращает пару (after, memo_after), а не memo_before."""
    h: SnapshotHistory[str] = SnapshotHistory()
    mb, ma = _Memo("до"), _Memo("после")
    _rec(h, "S0", "S1", memo_before=mb, memo_after=ma)
    h.take_undo_with_memo()

    got = h.take_redo_with_memo()

    assert got is not None
    snapshot, memo = got
    assert snapshot == "S1"
    assert memo is ma


def test_memo_survives_repeated_undo_redo_cycles() -> None:
    """Запись при undo/redo переезжает между стеками вместе с memo — оба memo не теряются."""
    h: SnapshotHistory[str] = SnapshotHistory()
    mb, ma = _Memo("до"), _Memo("после")
    _rec(h, "S0", "S1", memo_before=mb, memo_after=ma)

    assert h.take_undo_with_memo() == ("S0", mb)
    assert h.take_redo_with_memo() == ("S1", ma)
    assert h.take_undo_with_memo() == ("S0", mb)
    assert h.take_redo_with_memo() == ("S1", ma)


def test_with_memo_on_empty_stacks_returns_none() -> None:
    """Пустые стеки: обе новые операции возвращают None (как take_undo/take_redo)."""
    h: SnapshotHistory[str] = SnapshotHistory()

    assert h.take_undo_with_memo() is None
    assert h.take_redo_with_memo() is None


def test_plain_take_undo_still_returns_only_snapshot_for_memo_entry() -> None:
    """take_undo()/take_redo() на записи С memo по-прежнему возвращают голый снимок, не пару."""
    h: SnapshotHistory[str] = SnapshotHistory()
    _rec(h, "S0", "S1", memo_before=_Memo("до"), memo_after=_Memo("после"))

    assert h.take_undo() == "S0"
    assert h.take_redo() == "S1"


def test_memo_stays_with_entry_when_mixing_plain_and_with_memo_calls() -> None:
    """undo обычным take_undo, redo через *_with_memo: memo_after всё равно на месте."""
    h: SnapshotHistory[str] = SnapshotHistory()
    ma = _Memo("после")
    _rec(h, "S0", "S1", memo_before=_Memo("до"), memo_after=ma)
    h.take_undo()

    assert h.take_redo_with_memo() == ("S1", ma)


def test_entry_without_memo_yields_none_memo() -> None:
    """Запись, сделанная без memo (старый вызов), отдаёт memo=None — не исключение."""
    h: SnapshotHistory[str] = SnapshotHistory()
    h.record(before="S0", after="S1", label="op", command_type="Op")

    assert h.take_undo_with_memo() == ("S0", None)
    assert h.take_redo_with_memo() == ("S1", None)


# ---------------------------------------------------------------------------
# A7 (framework): coalescing
# ---------------------------------------------------------------------------


def test_a7_coalescing_keeps_first_before_and_newest_after() -> None:
    """Три записи с одним coalesce_key = одна запись: memo_before 1-й, memo_after 3-й."""
    h: SnapshotHistory[str] = SnapshotHistory()
    mb1, ma1 = _Memo("до-1"), _Memo("после-1")
    mb2, ma2 = _Memo("до-2"), _Memo("после-2")
    mb3, ma3 = _Memo("до-3"), _Memo("после-3")
    _rec(h, "S0", "S1", key="k", memo_before=mb1, memo_after=ma1)
    _rec(h, "S1", "S2", key="k", memo_before=mb2, memo_after=ma2)
    _rec(h, "S2", "S3", key="k", memo_before=mb3, memo_after=ma3)

    assert len(h.entries(0)) == 1  # серия слита в одну запись

    undo = h.take_undo_with_memo()
    assert undo is not None
    assert undo[0] == "S0"
    assert undo[1] is mb1  # НЕ mb2/mb3: откат серии возвращает выбор ДО первой правки
    assert h.take_undo_with_memo() is None  # одним шагом

    redo = h.take_redo_with_memo()
    assert redo is not None
    assert redo[0] == "S3"
    assert redo[1] is ma3  # НЕ ma1/ma2: повтор возвращает выбор ПОСЛЕ последней правки


def test_a7_different_coalesce_keys_do_not_merge_memos() -> None:
    """Разные ключи: две отдельные записи, у каждой свои memo (граница coalescing)."""
    h: SnapshotHistory[str] = SnapshotHistory()
    mb1, ma1 = _Memo("до-1"), _Memo("после-1")
    mb2, ma2 = _Memo("до-2"), _Memo("после-2")
    _rec(h, "S0", "S1", key="a", memo_before=mb1, memo_after=ma1)
    _rec(h, "S1", "S2", key="b", memo_before=mb2, memo_after=ma2)

    assert len(h.entries(0)) == 2
    assert h.take_undo_with_memo() == ("S1", mb2)
    assert h.take_undo_with_memo() == ("S0", mb1)


# ---------------------------------------------------------------------------
# A8: memo живут только внутри записей
# ---------------------------------------------------------------------------


def _fill_with_tracked_memos(h: SnapshotHistory, count: int) -> list[weakref.ref]:
    """Записать count записей, у каждой два memo; вернуть weakref на все 2*count memo."""
    refs: list[weakref.ref] = []
    for i in range(count):
        mb, ma = _Memo(f"до-{i}"), _Memo(f"после-{i}")
        refs.append(weakref.ref(mb))
        refs.append(weakref.ref(ma))
        _rec(h, i, i + 1, memo_before=mb, memo_after=ma)
        del mb, ma  # локальные ссылки не должны удерживать memo
    return refs


@pytest.mark.parametrize("how", ["truncation", "clear"])
def test_a8_truncation_and_clear_release_memos(how: str) -> None:
    """Вытесненные обрезкой (или сброшенные clear()) записи отпускают свои memo."""
    max_history = 3
    h: SnapshotHistory[int] = SnapshotHistory(max_history=max_history)
    total = max_history + 5
    refs = _fill_with_tracked_memos(h, total)

    if how == "clear":
        h.clear()
        gc.collect()
        assert [r() for r in refs] == [None] * (2 * total)
        assert h.take_undo_with_memo() is None
        return

    gc.collect()
    evicted = refs[: 2 * (total - max_history)]
    kept = refs[2 * (total - max_history) :]
    assert all(r() is None for r in evicted), "memo вытесненных записей должны быть собраны"
    assert all(r() is not None for r in kept), "memo живых записей собраны раньше времени"

    # undo до дна не падает и отдаёт ровно max_history записей с memo из «хвоста»
    seen = []
    for _ in range(max_history):
        got = h.take_undo_with_memo()
        assert got is not None
        seen.append((got[0], got[1].tag))
    assert seen == [(7, "до-7"), (6, "до-6"), (5, "до-5")]
    assert h.take_undo_with_memo() is None


def test_a8_clear_releases_memos_of_redo_stack_too() -> None:
    """clear() отпускает и memo записей, уже переехавших в redo-стек."""
    h: SnapshotHistory[int] = SnapshotHistory()
    refs = _fill_with_tracked_memos(h, 3)
    h.take_undo_with_memo()
    h.take_undo_with_memo()  # две записи лежат в redo

    h.clear()
    gc.collect()

    assert [r() for r in refs] == [None] * 6
    assert h.take_redo_with_memo() is None


def test_a8_new_record_releases_memos_of_redo_stack() -> None:
    """Новая запись чистит redo-стек (как раньше) — вместе с memo отменённых записей."""
    h: SnapshotHistory[int] = SnapshotHistory()
    refs = _fill_with_tracked_memos(h, 2)
    h.take_undo_with_memo()  # запись №1 (refs[2], refs[3]) лежит в redo
    live_before = refs[:2]  # запись №0 осталась в undo

    _rec(h, 10, 11, memo_before=_Memo("до-новая"), memo_after=_Memo("после-новая"))
    gc.collect()

    assert refs[2]() is None and refs[3]() is None
    assert all(r() is not None for r in live_before)
    assert h.take_redo_with_memo() is None


# ---------------------------------------------------------------------------
# A9: без memo побайтно как раньше
# ---------------------------------------------------------------------------


def test_a9_without_memo_undo_redo_sequence_unchanged() -> None:
    """Три записи без memo: undo отдаёт before в обратном порядке, redo — after в прямом."""
    h: SnapshotHistory[str] = SnapshotHistory()
    for i in range(3):
        h.record(before=f"S{i}", after=f"S{i + 1}", label=f"op{i}", command_type="Op")

    assert h.take_undo() == "S2"
    assert h.take_undo() == "S1"
    assert h.take_undo() == "S0"
    assert h.take_undo() is None
    assert h.take_redo() == "S1"
    assert h.take_redo() == "S2"
    assert h.take_redo() == "S3"
    assert h.take_redo() is None


def test_a9_without_memo_returns_same_snapshot_object() -> None:
    """Идентичность снимков сохраняется (тот же объект, не копия) — контракт модуля."""
    h: SnapshotHistory[object] = SnapshotHistory()
    before, after = object(), object()
    h.record(before=before, after=after, label="op", command_type="Op")

    assert h.take_undo() is before
    assert h.take_redo() is after


def test_a9_without_memo_coalescing_unchanged() -> None:
    """Coalescing без memo: before первой, after новой; одна запись, label последней."""
    h: SnapshotHistory[str] = SnapshotHistory()
    h.record(before="S0", after="S1", label="first", command_type="Op", coalesce_key="k")
    h.record(before="S1", after="S2", label="last", command_type="Op", coalesce_key="k")

    entries = h.entries(0)
    assert [(e.label, e.command_type) for e in entries] == [("last", "Op")]
    assert h.take_undo() == "S0"
    assert h.take_redo() == "S2"


def test_a9_without_memo_max_history_truncation_unchanged() -> None:
    """Обрезка без memo: остаются последние max_history записей, глубже undo пуст."""
    h: SnapshotHistory[int] = SnapshotHistory(max_history=2)
    for i in range(5):
        h.record(before=i, after=i + 1, label=f"op{i}", command_type="Op")

    assert [e.label for e in h.entries(0)] == ["op3", "op4"]
    assert h.take_undo() == 4
    assert h.take_undo() == 3
    assert h.take_undo() is None
    assert h.can_undo() is False
    assert h.can_redo() is True


def test_a9_new_record_clears_redo_unchanged() -> None:
    """Новая запись чистит redo-стек (без memo)."""
    h: SnapshotHistory[str] = SnapshotHistory()
    h.record(before="S0", after="S1", label="a", command_type="Op")
    h.take_undo()
    assert h.can_redo() is True

    h.record(before="S0", after="S9", label="b", command_type="Op")

    assert h.can_redo() is False
    assert h.take_redo() is None
