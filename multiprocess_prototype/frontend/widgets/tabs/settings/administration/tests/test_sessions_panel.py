# -*- coding: utf-8 -*-
"""Тесты SessionsPanel — PR4 Group C.

Проверяет:
  - test_panel_loads_sessions   — таблица заполняется из audit_storage.list_sessions()
  - test_panel_refresh_button   — кнопка «Обновить» перезагружает данные
  - test_duration_format        — _format_duration возвращает правильные строки
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from multiprocess_prototype.frontend.widgets.tabs.settings.administration.sessions_panel import (
    SessionsPanel,
)
from multiprocess_prototype.frontend.widgets.tabs.settings.administration._formatters import (
    format_duration as _format_duration_fn,
)

# ---------------------------------------------------------------------------
# Вспомогательные данные
# ---------------------------------------------------------------------------

_DT_LOGIN = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc)
_DT_LOGOUT = datetime(2026, 5, 1, 11, 23, 0, tzinfo=timezone.utc)


def _make_session(username: str, login_at: datetime, logout_at=None, host: str = "localhost"):
    """Создать mock SessionEntry с нужными полями."""
    entry = MagicMock()
    entry.username = username
    entry.login_at = login_at
    entry.logout_at = logout_at
    entry.host = host
    return entry


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_storage():
    """Мок SqliteAuditStorage с пустым list_sessions по умолчанию."""
    storage = MagicMock()
    storage.list_sessions.return_value = []
    return storage


@pytest.fixture
def mock_ctx(mock_storage):
    """Мок AuthContext: audit = mock_storage, state — auto MagicMock."""
    ctx = MagicMock()
    ctx.audit = mock_storage
    return ctx


# ---------------------------------------------------------------------------
# test_panel_loads_sessions
# ---------------------------------------------------------------------------


class TestSessionsPanelLoadSessions:
    """Таблица заполняется из list_sessions()."""

    def test_panel_loads_sessions_two_rows(self, qtbot, mock_ctx, mock_storage):
        """При list_sessions() с 2 сессиями таблица содержит 2 строки."""
        mock_storage.list_sessions.return_value = [
            _make_session("alice", _DT_LOGIN, _DT_LOGOUT),
            _make_session("bob", _DT_LOGIN),
        ]

        panel = SessionsPanel(mock_ctx)
        qtbot.addWidget(panel)

        assert panel._table.rowCount() == 2

    def test_panel_loads_sessions_empty(self, qtbot, mock_ctx, mock_storage):
        """При пустом list_sessions() таблица содержит 0 строк."""
        mock_storage.list_sessions.return_value = []

        panel = SessionsPanel(mock_ctx)
        qtbot.addWidget(panel)

        assert panel._table.rowCount() == 0

    def test_panel_loads_sessions_first_cell_username(self, qtbot, mock_ctx, mock_storage):
        """Первая ячейка первой строки — username первой сессии."""
        mock_storage.list_sessions.return_value = [
            _make_session("alice", _DT_LOGIN),
        ]

        panel = SessionsPanel(mock_ctx)
        qtbot.addWidget(panel)

        item = panel._table.item(0, 0)
        assert item is not None
        assert item.text() == "alice"

    def test_panel_calls_list_sessions_with_user_id_none_when_has_permission(
        self, qtbot, mock_ctx, mock_storage
    ):
        """Если access_context.has_permission("users.view") → list_sessions(user_id=None)."""
        # auth_state с разрешением users.view
        access_ctx = MagicMock()
        access_ctx.has_permission.return_value = True  # wildcard
        access_ctx.user_id = "u-alice"

        auth_state = MagicMock()
        auth_state.access_context = access_ctx
        mock_ctx.state = auth_state

        panel = SessionsPanel(mock_ctx)
        qtbot.addWidget(panel)

        mock_storage.list_sessions.assert_called_with(user_id=None, limit=50)

    def test_panel_calls_list_sessions_with_own_user_id_when_no_permission(
        self, qtbot, mock_ctx, mock_storage
    ):
        """Если нет users.view → list_sessions(user_id=current_user_id)."""
        access_ctx = MagicMock()
        access_ctx.has_permission.return_value = False
        access_ctx.user_id = "u-bob"

        auth_state = MagicMock()
        auth_state.access_context = access_ctx
        mock_ctx.state = auth_state

        panel = SessionsPanel(mock_ctx)
        qtbot.addWidget(panel)

        mock_storage.list_sessions.assert_called_with(user_id="u-bob", limit=50)


# ---------------------------------------------------------------------------
# test_panel_refresh_button
# ---------------------------------------------------------------------------


class TestSessionsPanelRefreshButton:
    """Кнопка «Обновить» перезагружает данные из хранилища."""

    def test_refresh_button_calls_list_sessions_again(self, qtbot, mock_ctx, mock_storage):
        """После нажатия «Обновить» list_sessions вызывается ещё раз."""
        mock_storage.list_sessions.return_value = []

        panel = SessionsPanel(mock_ctx)
        qtbot.addWidget(panel)

        # Сбросить счётчик после __init__
        mock_storage.list_sessions.reset_mock()

        qtbot.mouseClick(panel._btn_refresh, __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.MouseButton.LeftButton)

        mock_storage.list_sessions.assert_called_once()

    def test_refresh_button_updates_table(self, qtbot, mock_ctx, mock_storage):
        """После «Обновить» таблица обновляется с новыми данными."""
        mock_storage.list_sessions.return_value = []

        panel = SessionsPanel(mock_ctx)
        qtbot.addWidget(panel)

        assert panel._table.rowCount() == 0

        # Теперь storage вернёт одну сессию
        mock_storage.list_sessions.return_value = [
            _make_session("carol", _DT_LOGIN),
        ]
        panel._load()  # вызываем напрямую (кнопка → _load)

        assert panel._table.rowCount() == 1


# ---------------------------------------------------------------------------
# test_duration_format
# ---------------------------------------------------------------------------


class TestDurationFormat:
    """Функция _format_duration из _formatters возвращает правильные строки.

    После рефакторинга nitpick-1 (PR4 Group C iter 1) функция вынесена
    из SessionsPanel в _formatters.format_duration.
    """

    def test_active_session_returns_aktivna(self):
        """logout_at=None → «активна»."""
        result = _format_duration_fn(_DT_LOGIN, None)
        assert result == "активна"

    def test_hours_and_minutes(self):
        """Сессия 1ч 23мин."""
        login = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc)
        logout = datetime(2026, 5, 1, 11, 23, 0, tzinfo=timezone.utc)
        result = _format_duration_fn(login, logout)
        assert result == "1ч 23мин"

    def test_only_minutes(self):
        """Сессия 45 мин (без часов)."""
        login = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc)
        logout = datetime(2026, 5, 1, 10, 45, 0, tzinfo=timezone.utc)
        result = _format_duration_fn(login, logout)
        assert result == "45мин"

    def test_less_than_minute(self):
        """Сессия менее минуты → «< 1мин»."""
        login = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc)
        logout = datetime(2026, 5, 1, 10, 0, 30, tzinfo=timezone.utc)
        result = _format_duration_fn(login, logout)
        assert result == "< 1мин"

    def test_login_at_none_returns_dash(self):
        """login_at=None → «—»."""
        result = _format_duration_fn(None, None)
        assert result == "—"

    def test_zero_minutes_returns_less_than_minute(self):
        """Ровно 0 секунд разницы → «< 1мин»."""
        dt = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc)
        result = _format_duration_fn(dt, dt)
        assert result == "< 1мин"
