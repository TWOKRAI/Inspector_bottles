# -*- coding: utf-8 -*-
"""AdministrationSection — секция «Администрация» в табе настроек.

Структура:
  SideNavLayout
    «Пользователи» → UsersPanel(ctx)
    «Роли»         → заглушка (будет реализована в Group D)

Права: секция отображает содержимое только при наличии хотя бы одного
из permissions «users.view» или «roles.view». При отсутствии обоих —
показывает placeholder «Недостаточно прав».
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from multiprocess_prototype.frontend.widgets.primitives import SideNavLayout

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


class AdministrationSection(QWidget):
    """Секция «Администрация» — SideNavLayout с двумя подсекциями.

    Структура:
      SideNavLayout
        «Пользователи» → UsersPanel(ctx)
        «Роли»         → RolesPanel(ctx)  # Group D — пока stub

    Права: секция видима только при наличии хотя бы одного permission
    «users.view» или «roles.view». При отсутствии обоих — placeholder
    «Недостаточно прав».
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Проверяем наличие прав для отображения содержимого
        if not self._has_access(ctx):
            layout.addWidget(self._build_no_access_placeholder())
            return

        # Боковая навигация с двумя подсекциями
        nav = SideNavLayout()

        # Подсекция «Пользователи» — только если есть право users.view
        auth_state = ctx.auth_state()
        permissions: frozenset[str] = frozenset()
        if auth_state is not None:
            permissions = auth_state.access_context.permissions

        if "users.view" in permissions:
            from .users_panel import UsersPanel
            users_widget: QWidget = UsersPanel(ctx)
        else:
            users_widget = self._build_restricted_placeholder("Пользователи")

        nav.add_section("users", "Пользователи", users_widget)

        # Подсекция «Роли» — stub (будет реализована в Group D)
        roles_stub = QLabel("Раздел «Роли» — будет реализован в Group D")
        roles_stub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        roles_stub.setStyleSheet("color: gray; font-size: 13px;")
        nav.add_section("roles", "Роли", roles_stub)

        # Открываем первую доступную подсекцию
        nav.set_current("users")

        layout.addWidget(nav)

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    @staticmethod
    def _has_access(ctx: "AppContext") -> bool:
        """Проверить наличие хотя бы одного из прав users.view / roles.view."""
        auth_state = ctx.auth_state()
        if auth_state is None:
            return False
        permissions = auth_state.access_context.permissions
        return bool(permissions & {"users.view", "roles.view"})

    @staticmethod
    def _build_no_access_placeholder() -> QWidget:
        """Плейсхолдер «Недостаточно прав» для всей секции."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel("Недостаточно прав для просмотра раздела «Администрация»")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: gray; font-size: 14px;")
        layout.addWidget(label)
        return widget

    @staticmethod
    def _build_restricted_placeholder(section_title: str) -> QWidget:
        """Плейсхолдер для отдельной подсекции при недостаточных правах."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel(f"Недостаточно прав для доступа к разделу «{section_title}»")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: gray; font-size: 13px;")
        layout.addWidget(label)
        return widget
