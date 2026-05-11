# -*- coding: utf-8 -*-
"""AdministrationSection — секция «Администрация» в табе настроек.

Структура (при наличии прав):
  SideNavLayout
    «Пользователи» → UsersPanel(ctx)      (если есть право users.view)
    «Роли»         → RolesPanel(ctx)       (если есть право roles.view)

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
    """Секция «Администрация» — SideNavLayout с подсекциями «Пользователи» и «Роли».

    Содержимое перестраивается при изменении access_context (сигнал AuthState),
    поэтому корректно реагирует на login и logout даже если виджет создан до входа.

    Структура (при наличии прав):
      SideNavLayout
        «Пользователи» → UsersPanel(ctx)   (только если есть users.view)
        «Роли»         → RolesPanel(ctx)    (только если есть roles.view)

    Если доступна только одна подсекция — SideNav содержит один пункт.
    Если нет ни одной — отображается placeholder «Недостаточно прав».
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._auth_state: AuthState | None = ctx.auth_state()

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

        permissions: frozenset[str] = frozenset()
        if self._auth_state is not None:
            permissions = self._auth_state.access_context.permissions

        has_users = "users.view" in permissions
        has_roles = "roles.view" in permissions

        if not has_users and not has_roles:
            self._current = self._build_restricted_placeholder()
        else:
            self._current = self._build_sidenav(has_users=has_users, has_roles=has_roles)

        self._outer_layout.addWidget(self._current)

    # ------------------------------------------------------------------
    # Строители содержимого
    # ------------------------------------------------------------------

    def _build_sidenav(self, *, has_users: bool, has_roles: bool) -> QWidget:
        """Построить SideNavLayout с теми подсекциями, на которые есть права."""
        nav = SideNavLayout()
        first_key: str | None = None

        if has_users:
            from .users_panel import UsersPanel
            nav.add_section("users", "Пользователи", UsersPanel(self._ctx))
            if first_key is None:
                first_key = "users"

        if has_roles:
            from .roles_panel import RolesPanel
            nav.add_section("roles", "Роли", RolesPanel(self._ctx))
            if first_key is None:
                first_key = "roles"

        if first_key is not None:
            nav.set_current(first_key)

        return nav

    @staticmethod
    def _build_restricted_placeholder() -> QWidget:
        """Плейсхолдер «Недостаточно прав» для всей секции."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel("Недостаточно прав для просмотра раздела «Администрация»")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: gray; font-size: 14px;")
        layout.addWidget(label)
        return widget
