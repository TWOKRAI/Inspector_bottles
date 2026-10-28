# -*- coding: utf-8 -*-
"""Слепая приёмка Task 1.12 (C-30): флаг ``layout_unsaved`` у TopologySession.

Автосохранение раскладки узлов при устаревшей базе не пишет в файл; сессия должна помнить, что
позиции узлов не сохранены, чтобы закрытие окна не теряло их молча. Здесь — только чистая логика
сессии: установка флага, уведомление подписчиков, какие вызовы флаг сбрасывают, какие не трогают.

Ожидаемые значения — литералы (число вызовов callback, True/False).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from multiprocess_prototype.domain.topology_session import TopologySession


def _counter(session: TopologySession) -> Callable[[], int]:
    """Подписаться на изменения сессии; вернуть функцию «сколько уведомлений пришло»."""
    calls = 0

    def _cb() -> None:
        nonlocal calls
        calls += 1

    session.add_change_callback(_cb)
    return lambda: calls


# ---------------------------------------------------------------------------
# A. Установка флага и три сброса
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reset_call", ["mark_saved", "mark_activated", "reset"])
def test_layout_unsaved_set_notifies_once_and_is_cleared_by(reset_call: str) -> None:
    """Флаг False -> mark_layout_unsaved -> True (1 уведомление); повтор молчит; сброс возвращает False."""
    session = TopologySession()
    assert session.layout_unsaved is False
    calls = _counter(session)

    session.mark_layout_unsaved()
    assert session.layout_unsaved is True
    assert calls() == 1

    session.mark_layout_unsaved()
    assert session.layout_unsaved is True
    assert calls() == 1, "повторная установка того же значения не должна уведомлять подписчиков"

    getattr(session, reset_call)()
    assert session.layout_unsaved is False


# ---------------------------------------------------------------------------
# B. mark_edited / mark_applied флаг не трогают
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("untouched_call", ["mark_edited", "mark_applied"])
def test_layout_unsaved_stays_false_on_clean_session(untouched_call: str) -> None:
    """Чистая сессия: mark_edited / mark_applied флаг не ставят."""
    session = TopologySession()

    getattr(session, untouched_call)()

    assert session.layout_unsaved is False


@pytest.mark.parametrize("untouched_call", ["mark_edited", "mark_applied"])
def test_layout_unsaved_stays_true_through(untouched_call: str) -> None:
    """Флаг поднят: mark_edited / mark_applied его не снимают."""
    session = TopologySession()
    session.mark_layout_unsaved()

    getattr(session, untouched_call)()

    assert session.layout_unsaved is True
