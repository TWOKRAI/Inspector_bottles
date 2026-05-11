# -*- coding: utf-8 -*-
"""SessionsPanel — read-only панель просмотра сессий пользователей.

Отображает таблицу сессий из SqliteAuditStorage.
Scope фильтра:
  - admin/dev (wildcard users.view) → все сессии (user_id=None)
  - остальные                       → только свои (user_id=current_user_id)

Используется как подсекция «Сессии» в AdministrationSection.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from Services.auth import SessionEntry

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


class SessionsPanel(QWidget):
    """Read-only панель просмотра сессий.

    Колонки: Пользователь | Вход | Выход | Длительность | Хост
    """

    _TABLE_COLUMNS = [
        ("username",  "Пользователь",  140),
        ("login_at",  "Вход",          140),
        ("logout_at", "Выход",         140),
        ("duration",  "Длительность",  110),
        ("host",      "Хост",          120),
    ]

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._ctx = ctx
        self._storage = ctx.audit_storage()
        self._access_context = None

        # Получаем access_context через auth_state
        auth_state = ctx.auth_state()
        if auth_state is not None:
            self._access_context = auth_state.access_context

        self._sessions: list[SessionEntry] = []
        self._setup_ui()
        self._load()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Построить layout панели."""
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Заголовок + кнопка обновления
        header_layout = QHBoxLayout()
        header_label = QLabel("Сессии")
        font = header_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        header_label.setFont(font)
        header_layout.addWidget(header_label)
        header_layout.addStretch()

        self._btn_refresh = QPushButton("Обновить")
        self._btn_refresh.setFixedWidth(100)
        self._btn_refresh.setToolTip("Перезагрузить список сессий")
        self._btn_refresh.clicked.connect(self._load)
        header_layout.addWidget(self._btn_refresh)

        root.addLayout(header_layout)

        # Таблица
        self._table = QTableWidget(0, len(self._TABLE_COLUMNS))
        self._table.setHorizontalHeaderLabels(
            [col[1] for col in self._TABLE_COLUMNS]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)

        h = self._table.horizontalHeader()
        for i, (_, _, width) in enumerate(self._TABLE_COLUMNS):
            if i == len(self._TABLE_COLUMNS) - 1:
                h.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            else:
                self._table.setColumnWidth(i, width)
                h.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)

        root.addWidget(self._table, stretch=1)

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
                self._format_dt(login_at),
                self._format_dt(logout_at),
                self._format_duration(login_at, logout_at),
                entry.host,
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col, item)

    # ------------------------------------------------------------------
    # Форматирование
    # ------------------------------------------------------------------

    @staticmethod
    def _format_dt(value: datetime | None) -> str:
        """Отформатировать datetime для отображения в таблице."""
        if value is None:
            return "—"
        # Нормализация к строке
        val_str = str(value)
        if "T" in val_str:
            parts = val_str.split("T")
            date_part = parts[0]
            time_part = parts[1].split(".")[0] if len(parts) > 1 else ""
            return f"{date_part} {time_part}".strip()
        return val_str

    @staticmethod
    def _format_duration(login_at: datetime | None, logout_at: datetime | None) -> str:
        """Вернуть строку длительности сессии.

        Если logout_at is None — сессия ещё активна → «активна».
        Иначе: «1ч 23мин», «45мин», «< 1мин».
        """
        if login_at is None:
            return "—"
        if logout_at is None:
            return "активна"

        # Обеспечиваем совместимость naive/aware datetime
        if login_at.tzinfo is not None and logout_at.tzinfo is None:
            logout_at = logout_at.replace(tzinfo=timezone.utc)
        elif login_at.tzinfo is None and logout_at.tzinfo is not None:
            login_at = login_at.replace(tzinfo=timezone.utc)

        delta_seconds = int((logout_at - login_at).total_seconds())
        if delta_seconds < 0:
            return "—"
        if delta_seconds < 60:
            return "< 1мин"

        minutes_total = delta_seconds // 60
        hours = minutes_total // 60
        minutes = minutes_total % 60

        if hours > 0:
            return f"{hours}ч {minutes}мин"
        return f"{minutes}мин"
