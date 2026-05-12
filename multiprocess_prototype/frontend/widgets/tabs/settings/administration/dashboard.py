"""AdminDashboard — обзорная панель секции «Администрация».

Показывается при клике на корневой узел «Администрация» в дереве навигации.
Содержит:
  - Карточку текущей сессии (пользователь, роль, время входа, права)
  - Кнопки быстрого перехода к подразделам (Пользователи, Роли, Сессии, Audit)
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.state.auth_state import AuthState


class AdminDashboard(QWidget):
    """Обзорная панель администрации — сессия + навигация."""

    # Сигнал: пользователь хочет перейти в подраздел (ключ: users/roles/sessions/audit_log)
    navigate_to = Signal(str)

    def __init__(self, auth_state: "AuthState | None", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._auth_state = auth_state
        self._init_ui()
        self._refresh_session_card()

        if self._auth_state is not None:
            self._auth_state.access_context_changed.connect(
                lambda _ctx: self._refresh_session_card()
            )

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        # === Кнопки навигации (первыми — быстрый доступ) ===
        nav_group = QGroupBox("Разделы администрации")
        nav_layout = QHBoxLayout(nav_group)
        nav_layout.setSpacing(8)

        nav_items = [
            ("users", "Пользователи", "Управление учётными записями"),
            ("roles", "Роли", "Настройка ролей и прав"),
            ("sessions", "Сессии", "Активные сессии пользователей"),
            ("audit_log", "Audit log", "Журнал действий"),
        ]

        for key, title, tooltip in nav_items:
            btn = QPushButton(title)
            btn.setToolTip(tooltip)
            btn.setMinimumHeight(48)
            btn.setMinimumWidth(120)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, k=key: self.navigate_to.emit(k))
            nav_layout.addWidget(btn)

        nav_layout.addStretch()
        layout.addWidget(nav_group)

        # === Карточка текущей сессии ===
        self._session_group = QGroupBox("Текущая сессия")
        session_layout = QVBoxLayout(self._session_group)
        session_layout.setSpacing(6)

        self._lbl_user = QLabel()
        self._lbl_user.setStyleSheet("font-size: 14px; font-weight: bold;")
        session_layout.addWidget(self._lbl_user)

        self._lbl_role = QLabel()
        session_layout.addWidget(self._lbl_role)

        self._lbl_time = QLabel()
        session_layout.addWidget(self._lbl_time)

        self._lbl_permissions = QLabel()
        self._lbl_permissions.setWordWrap(True)
        self._lbl_permissions.setStyleSheet("color: #9ea6b2; font-size: 11px;")
        session_layout.addWidget(self._lbl_permissions)

        layout.addWidget(self._session_group)
        layout.addStretch()

    def _refresh_session_card(self) -> None:
        """Обновить карточку сессии из AuthState."""
        if self._auth_state is None or not self._auth_state.is_authenticated:
            self._lbl_user.setText("Не авторизован")
            self._lbl_role.setText("")
            self._lbl_time.setText("")
            self._lbl_permissions.setText("")
            return

        user = self._auth_state.current_user or {}
        ctx = self._auth_state.access_context

        username = user.get("username", "—")
        self._lbl_user.setText(f"Пользователь: {username}")
        self._lbl_role.setText(f"Роль: {ctx.role_name or '—'}")

        # Время входа (если есть в user dict)
        login_ts = user.get("logged_in_at")
        if login_ts:
            try:
                ts_str = datetime.fromtimestamp(float(login_ts)).strftime("%H:%M:%S %d.%m.%Y")
            except (ValueError, TypeError, OSError):
                ts_str = str(login_ts)
            self._lbl_time.setText(f"Вход: {ts_str}")
        else:
            self._lbl_time.setText(f"Вход: {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}")

        # Права
        if "*" in ctx.permissions:
            perms_str = "Все права (*)"
        else:
            perms_list = sorted(ctx.permissions)
            perms_str = ", ".join(perms_list[:20])
            if len(perms_list) > 20:
                perms_str += f" ... (+{len(perms_list) - 20})"
        self._lbl_permissions.setText(f"Права: {perms_str}")
