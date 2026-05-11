# -*- coding: utf-8 -*-
"""RolesPanel — панель просмотра ролей (read-only в PR2).

Отображает список ролей слева (QListWidget) и матрицу permissions
справа (PermissionMatrix). Роли с hidden_in_ui=True (например, dev)
не показываются в списке.

Кнопки управления ролями (Создать / Изменить / Удалить) disabled в PR2 —
активируются в PR4.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .permission_matrix import PermissionMatrix

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


class RolesPanel(QWidget):
    """Панель просмотра ролей (read-only в PR2).

    Кнопки управления ролями disabled — активируются в PR4.
    Роли с hidden_in_ui=True (dev) не отображаются в списке.
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._auth_manager = ctx.auth_manager()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # Если AuthManager недоступен — показываем заглушку
        if self._auth_manager is None:
            placeholder = QLabel("AuthManager не инициализирован")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: gray; font-size: 13px;")
            main_layout.addWidget(placeholder)
            return

        # --- Заголовок ---
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        title_label = QLabel("Роли")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        readonly_label = QLabel("(только чтение)")
        readonly_label.setStyleSheet("color: gray; font-size: 12px;")

        header_layout.addWidget(title_label)
        header_layout.addWidget(readonly_label)
        header_layout.addStretch()

        main_layout.addLayout(header_layout)

        # --- Основная область: список + матрица + кнопки ---
        content_layout = QHBoxLayout()
        content_layout.setSpacing(8)

        # Список ролей (фиксированная ширина ~160px)
        self._roles_list = QListWidget()
        self._roles_list.setFixedWidth(160)
        self._roles_list.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )

        # Матрица прав (растягивается)
        self._matrix = PermissionMatrix()
        self._matrix.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # Панель кнопок управления (фиксированная ширина ~140px, все disabled)
        buttons_layout = QVBoxLayout()
        buttons_layout.setSpacing(4)

        btn_create = QPushButton("Создать роль")
        btn_edit = QPushButton("Изменить права")
        btn_delete = QPushButton("Удалить роль")

        for btn in (btn_create, btn_edit, btn_delete):
            btn.setEnabled(False)
            btn.setToolTip("Доступно в PR4")
            btn.setFixedWidth(140)
            buttons_layout.addWidget(btn)

        buttons_layout.addStretch()

        content_layout.addWidget(self._roles_list)
        content_layout.addWidget(self._matrix, stretch=1)
        content_layout.addLayout(buttons_layout)

        main_layout.addLayout(content_layout, stretch=1)

        # --- Инициализация данных ---
        self._roles_by_name: dict[str, dict] = {}
        self._load_roles()

        # Сигнал выбора роли
        self._roles_list.currentTextChanged.connect(self._on_role_selected)

    # ------------------------------------------------------------------
    # Методы работы с данными
    # ------------------------------------------------------------------

    def _load_roles(self) -> None:
        """Загрузить роли через auth_manager.list_roles(), заполнить список.

        Роли с hidden_in_ui=True (dev и системные) не добавляются в список.
        """
        self._roles_by_name.clear()
        self._roles_list.clear()

        roles: list[dict] = self._auth_manager.list_roles()

        for role in roles:
            # Скрываем роли, помеченные как скрытые в UI
            if role.get("hidden_in_ui", False):
                continue

            name = role.get("name", "")
            if not name:
                continue

            self._roles_by_name[name] = role
            self._roles_list.addItem(name)

        # Автоматически выбрать первую роль (если список не пуст)
        if self._roles_list.count() > 0:
            self._roles_list.setCurrentRow(0)

    def _on_role_selected(self, role_name: str) -> None:
        """Передать выбранную роль в PermissionMatrix для отображения."""
        if not role_name:
            self._matrix.clear()
            return

        role_dict = self._roles_by_name.get(role_name)
        if role_dict is None:
            self._matrix.clear()
            return

        self._matrix.set_role(role_dict)
