# -*- coding: utf-8 -*-
"""SessionsPanel — read-only панель просмотра сессий пользователей.

Отображает таблицу сессий из SqliteAuditStorage.
Scope фильтра:
  - admin/dev (wildcard users.view) → все сессии (user_id=None)
  - остальные                       → только свои (user_id=current_user_id)

Регистрируется как подсекция «Сессии» через фабрику в settings/_sections.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QPushButton,
    QTableWidgetItem,
    QWidget,
)

from Services.auth import SessionEntry

from multiprocess_prototype.frontend.widgets.tabs.settings.administration._formatters import (
    format_dt as _format_dt,
    format_duration as _format_duration,
)

from ._base_panel import BaseAdminPanel

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.auth_context import AuthContext


class SessionsPanel(BaseAdminPanel):
    """Read-only панель просмотра сессий.

    Колонки: Пользователь | Вход | Выход | Длительность | Хост
    """

    _HEADER_TITLE = "Сессии"
    _TABLE_COLUMNS = [
        ("username", "Пользователь", 140),
        ("login_at", "Вход", 140),
        ("logout_at", "Выход", 140),
        ("duration", "Длительность", 110),
        ("host", "Хост", 120),
    ]

    def __init__(self, auth: "AuthContext | None", parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._storage = auth.audit if auth is not None else None
        self._access_context = auth.state.access_context if auth is not None else None

        self._sessions: list[SessionEntry] = []
        self._setup_ui()
        self._load()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Построить layout панели."""
        root = self._create_group()

        # Таблица из BaseAdminPanel
        self._table = self._create_table()
        root.addWidget(self._table, stretch=1)

        # Кнопка создаётся здесь, но размещается в action panel секции
        self._btn_refresh = QPushButton("Обновить")
        self._btn_refresh.setToolTip("Перезагрузить список сессий")
        self._btn_refresh.clicked.connect(self._load)

    def action_buttons(self) -> list[QPushButton]:
        """Кнопки действий для размещения в action panel секции."""
        return [self._btn_refresh]

    # ------------------------------------------------------------------
    # Загрузка данных
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Загрузить сессии из хранилища и заполнить таблицу."""
        if self._storage is None:
            return

        # Определяем scope: admin/dev видят все сессии, остальные — только свои
        user_id: str | None = None
        if self._access_context is not None:
            if not self._access_context.has_permission("users.view"):
                # Ограниченный доступ — только свои сессии
                user_id = getattr(self._access_context, "user_id", None)
            # Если has_permission("users.view") → wildcard (admin/dev) → user_id=None (все)

        try:
            self._sessions = self._storage.list_sessions(user_id=user_id, limit=50)
        except Exception:
            self._sessions = []

        self._fill_table()

    def _fill_table(self) -> None:
        """Заполнить таблицу из self._sessions."""
        self._table.setRowCount(len(self._sessions))
        for row, entry in enumerate(self._sessions):
            login_at = entry.login_at
            logout_at = entry.logout_at

            cells = [
                entry.username,
                _format_dt(login_at),
                _format_dt(logout_at),
                _format_duration(login_at, logout_at),
                entry.host,
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col, item)

    # Форматирование: _format_dt и _format_duration вынесены в _formatters.py
