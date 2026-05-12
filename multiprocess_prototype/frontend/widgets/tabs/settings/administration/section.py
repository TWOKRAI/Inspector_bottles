# -*- coding: utf-8 -*-
"""AdministrationSection — секция «Администрация» в табе настроек.

Структура (при наличии прав):
  SideNavLayout
    «Пользователи» → UsersPanel(ctx)      (если есть право users.view)
    «Роли»         → RolesPanel(ctx)       (если есть право roles.view)
    «Сессии»       → SessionsPanel(ctx)    (если есть право users.view)
    «Audit log»    → AuditLogPanel(ctx)    (если есть право roles.view)

Права: при отсутствии обоих permissions «users.view» и «roles.view» —
показывает placeholder «Недостаточно прав». Содержимое перестраивается
при каждом изменении access_context (login / logout / смена роли).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from multiprocess_prototype.frontend.widgets.primitives import SideNavLayout

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.managers.access_context import AccessContext
    from multiprocess_prototype.frontend.app_context import AppContext
    from multiprocess_prototype.frontend.state.auth_state import AuthState


class AdministrationSection(QWidget):
    """Секция «Администрация» — SideNavLayout с четырьмя подсекциями.

    Содержимое перестраивается при изменении access_context (сигнал AuthState),
    поэтому корректно реагирует на login и logout даже если виджет создан до входа.

    Структура (при наличии прав):
      SideNavLayout
        «Пользователи» → UsersPanel(ctx)    (только если есть users.view)
        «Роли»         → RolesPanel(ctx)    (только если есть roles.view)
        «Сессии»       → SessionsPanel(ctx) (только если есть users.view)
        «Audit log»    → AuditLogPanel(ctx) (только если есть roles.view)

    Если доступна только одна подсекция — SideNav содержит один пункт.
    Если нет ни одной — отображается placeholder «Недостаточно прав».
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        auth = ctx.auth
        self._auth_state: AuthState | None = auth.state if auth is not None else None

        # Внешний layout с одним «слотом» — текущим содержимым
        self._outer_layout = QVBoxLayout(self)
        self._outer_layout.setContentsMargins(0, 0, 0, 0)
        self._outer_layout.setSpacing(0)
        self._current: QWidget | None = None

        self._rebuild()

        if self._auth_state is not None:
            self._auth_state.access_context_changed.connect(self._on_access_changed)

    # ------------------------------------------------------------------
    # Слоты
    # ------------------------------------------------------------------

    def _on_access_changed(self, _ctx: "AccessContext") -> None:
        """Перестроить содержимое при смене контекста прав."""
        self._rebuild()

    # ------------------------------------------------------------------
    # Rebuild
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        """Удалить старое содержимое и построить новое по текущим правам."""
        if self._current is not None:
            self._outer_layout.removeWidget(self._current)
            self._current.deleteLater()
            self._current = None

        if self._auth_state is not None:
            access_ctx = self._auth_state.access_context
            has_users = access_ctx.has_permission("users.view")
            has_roles = access_ctx.has_permission("roles.view")
        else:
            has_users = has_roles = False

        if not has_users and not has_roles:
            self._current = self._build_restricted_placeholder()
        else:
            self._current = self._build_sidenav(
                has_users=has_users,
                has_roles=has_roles,
            )

        self._outer_layout.addWidget(self._current)

    # ------------------------------------------------------------------
    # Строители содержимого
    # ------------------------------------------------------------------

    def _build_sidenav(
        self, *, has_users: bool, has_roles: bool
    ) -> QWidget:
        """Построить SideNavLayout с теми подсекциями, на которые есть права.

        Порядок: Пользователи → Роли → Сессии → Audit log.
        «Сессии» видим при has_users, «Audit log» — при has_roles.
        RolesPanel сам читает permission из ctx.access_context.
        """
        nav = SideNavLayout()
        auth = self._ctx.auth
        bus = self._ctx.action_bus()

        if has_users:
            from .users_panel import UsersPanel
            panel = UsersPanel(auth)
            nav.add_section("users", "Пользователи", panel)
            nav.set_actions("users", panel.action_buttons())

        if has_roles:
            from .roles_panel import RolesPanel
            panel = RolesPanel(auth, bus)
            nav.add_section("roles", "Роли", panel)
            nav.set_actions("roles", panel.action_buttons())

        # PR4 Group C: read-only панели аудита
        has_sessions = has_users
        has_audit = has_roles

        if has_sessions:
            from .sessions_panel import SessionsPanel
            panel = SessionsPanel(auth)
            nav.add_section("sessions", "Сессии", panel)
            nav.set_actions("sessions", panel.action_buttons())

        if has_audit:
            from .audit_log_panel import AuditLogPanel
            panel = AuditLogPanel(auth)
            nav.add_section("audit_log", "Audit log", panel)
            nav.set_actions("audit_log", panel.action_buttons())

        nav.set_current("users" if has_users else "roles")

        return nav

    @staticmethod
    def _build_restricted_placeholder() -> QWidget:
        """Плейсхолдер «Недостаточно прав» для всей секции."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel("Недостаточно прав для просмотра раздела «Администрация»")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setObjectName("PlaceholderLabel")
        layout.addWidget(label)
        return widget
