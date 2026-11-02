# -*- coding: utf-8 -*-
"""Слепая приёмка Task 1.15 (C-30): ``TopologySession.mark_layout_saved`` гасит ``layout_unsaved``.

Успешный автосейв раскладки узлов записал позиции в файл — сессия должна перестать считать их потерянными.
Здесь только чистая логика сессии: что гасится, кого уведомляют, что остаётся нетронутым.

* ACC 1: флаг поднят -> ``mark_layout_saved`` гасит его, подписчик уведомлён ровно один раз;
* ACC 2: повторный вызов при погашенном флаге молчит;
* ACC 3: ``dirty`` и ``diverged`` вызов не трогает.

Ожидаемые значения — литералы (True/False, число вызовов подписчика).
"""

from __future__ import annotations

from collections.abc import Callable

from multiprocess_prototype.domain.topology_session import TopologySession


def _counter(session: TopologySession) -> Callable[[], int]:
    """Подписаться на изменения сессии; вернуть функцию «сколько уведомлений пришло»."""
    calls = 0

    def _cb() -> None:
        nonlocal calls
        calls += 1

    session.add_change_callback(_cb)
    return lambda: calls


def test_mark_layout_saved_clears_flag_and_notifies_once() -> None:
    """ACC 1: layout_unsaved True -> mark_layout_saved -> False; от самого вызова ровно одно уведомление."""
    session = TopologySession()
    session.mark_layout_unsaved()
    assert session.layout_unsaved is True
    calls = _counter(session)  # считаем только вызовы после mark_layout_unsaved

    session.mark_layout_saved()

    assert session.layout_unsaved is False
    assert calls() == 1


def test_mark_layout_saved_repeat_is_silent() -> None:
    """ACC 2: повторный mark_layout_saved при погашенном флаге не уведомляет подписчиков, флаг остаётся False."""
    session = TopologySession()
    session.mark_layout_unsaved()
    session.mark_layout_saved()
    assert session.layout_unsaved is False  # парная проверка: флаг действительно был погашен первым вызовом
    calls = _counter(session)

    session.mark_layout_saved()

    assert session.layout_unsaved is False
    assert calls() == 0


def test_mark_layout_saved_keeps_dirty_and_diverged() -> None:
    """ACC 3: dirty=True, diverged=True, layout_unsaved=True -> mark_layout_saved гасит только layout_unsaved."""
    session = TopologySession()
    session.mark_edited()  # публичный путь: ставит dirty и diverged
    session.mark_layout_unsaved()
    assert (session.dirty, session.diverged, session.layout_unsaved) == (True, True, True)

    session.mark_layout_saved()

    assert session.dirty is True
    assert session.diverged is True
    assert session.layout_unsaved is False
