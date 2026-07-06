# -*- coding: utf-8 -*-
"""RolesPanel — панель просмотра и редактирования ролей.

PR2: read-only. Кнопки Создать/Изменить/Удалить disabled.
PR4: при наличии прав roles.edit/create/delete кнопки активируются.
K1 (2026-06-18): legacy ActionBus-мост (V2ActionBuilder.role_update) снят —
проводка была мёртвой (bus всегда None). Матрица прав read-only до появления
domain-команды ROLE_UPDATE (Phase G+).

Роли с hidden_in_ui=True (например, dev) не показываются в списке.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .permission_matrix import PermissionMatrix

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.auth_context import AuthContext


class RolesPanel(QWidget):
    """Панель управления ролями.

    K1 (2026-06-18): legacy ActionBus-мост (V2ActionBuilder.role_update) снят —
    проводка была мёртвой (шина всегда None, сигнал не подключался). Матрица
    прав read-only до появления domain-команды ROLE_UPDATE (Phase G+).

    Кнопка «Удалить роль» вызывает auth_manager.delete_role() напрямую,
    так как удаление роли является необратимой операцией
    и не должно быть в undo-стеке.
    """

    def __init__(
        self,
        auth: "AuthContext | None",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._auth_manager = auth.manager if auth is not None else None

        # Определяем permissions текущего пользователя
        if auth is not None:
            access_ctx = auth.state.access_context
            self._can_create = access_ctx.has_permission("roles.create")
            self._can_edit = access_ctx.has_permission("roles.edit")
            self._can_delete = access_ctx.has_permission("roles.delete")
        else:
            self._can_create = False
            self._can_edit = False
            self._can_delete = False

        # Редактирование прав требует рабочего приёмника изменений. K1: legacy
        # ActionBus снят (шина всегда была None), domain-команды ROLE_UPDATE ещё
        # нет (Phase G+) → правки молча терялись бы при нажатии Save. Поэтому
        # матрица read-only, кнопка Save скрыта — без ложной affordance (план §11.5).
        self._edit_enabled = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        group = QGroupBox("Роли")
        main_layout = QVBoxLayout(group)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        outer.addWidget(group)

        # Если AuthManager недоступен — показываем заглушку внутри group
        if self._auth_manager is None:
            placeholder = QLabel("AuthManager не инициализирован")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setObjectName("PlaceholderLabel")
            main_layout.addWidget(placeholder)
            return

        # Подсказка «только чтение» (нет прав ИЛИ недоступен редактор)
        if not self._edit_enabled:
            # Различаем «нет прав» и «есть права, но нет приёмника изменений».
            if self._can_edit:
                hint = "(только чтение — редактор ролей недоступен)"
            else:
                hint = "(только чтение)"
            readonly_label = QLabel(hint)
            readonly_label.setProperty("role", "readonly-hint")
            main_layout.addWidget(readonly_label)

        # --- Основная область: список + матрица ---
        content_layout = QHBoxLayout()
        content_layout.setSpacing(8)

        # Список ролей (фиксированная ширина ~160px)
        self._roles_list = QListWidget()
        self._roles_list.setFixedWidth(160)
        self._roles_list.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        # Матрица прав: редактируема только при наличии прав И рабочего приёмника.
        # K1: приёмника нет (ActionBus снят) → всегда read-only; подписка на
        # permissions_changed вернётся вместе с domain-командой ROLE_UPDATE.
        self._matrix = PermissionMatrix(editable=self._edit_enabled)
        self._matrix.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        content_layout.addWidget(self._roles_list)
        content_layout.addWidget(self._matrix, stretch=1)

        main_layout.addLayout(content_layout, stretch=1)

        # Кнопки создаются здесь, но размещаются в action panel секции
        self._btn_create = QPushButton("Создать роль")
        self._btn_create.setEnabled(self._can_create)
        self._btn_create.setToolTip("" if self._can_create else "Недостаточно прав (roles.create)")

        self._btn_delete = QPushButton("Удалить роль")
        self._btn_delete.setEnabled(self._can_delete)
        self._btn_delete.setToolTip("" if self._can_delete else "Недостаточно прав (roles.delete)")
        self._btn_delete.clicked.connect(self._on_delete_clicked)

        # --- Инициализация данных ---
        self._roles_by_name: dict[str, dict] = {}
        self._load_roles()

        # Сигнал выбора роли
        self._roles_list.currentTextChanged.connect(self._on_role_selected)

    def action_buttons(self) -> list[QPushButton]:
        """Кнопки действий для размещения в action panel секции."""
        return [
            self._matrix._btn_save,
            self._matrix._btn_reset,
            self._btn_create,
            self._btn_delete,
        ]

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

    # ------------------------------------------------------------------
    # Обработчики кнопок
    # ------------------------------------------------------------------

    def _on_delete_clicked(self) -> None:
        """Удалить выбранную роль с подтверждением.

        Удаление роли — необратимая операция, поэтому выполняется напрямую
        через auth_manager.delete_role() и не попадает в undo-стек.
        """
        role_name = self._roles_list.currentItem()
        if role_name is None:
            return

        name = role_name.text()
        if not name:
            return

        reply = QMessageBox.warning(
            self,
            "Подтверждение удаления",
            f"Удалить роль «{name}»?\n\nЭто действие необратимо.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self._auth_manager.delete_role(name)
            self._load_roles()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Ошибка удаления",
                str(exc),
            )
