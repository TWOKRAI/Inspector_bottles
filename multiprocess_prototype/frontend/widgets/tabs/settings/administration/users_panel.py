# -*- coding: utf-8 -*-
"""UsersPanel — панель управления пользователями.

Отображает таблицу пользователей с кнопками:
  «Добавить», «Удалить», «Сменить роль», «Сбросить пароль».

Использует IAuthManager через AppContext.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from Services.auth.exceptions import AuthError, LastAdminError, UserNotFound, WeakPassword

from ._base_panel import BaseAdminPanel
from .user_form import UserForm

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.auth_context import AuthContext
    from multiprocess_prototype.frontend.widgets.dialogs.confirm_with_password import (
        ConfirmWithPasswordDialog,
    )


class UsersPanel(BaseAdminPanel):
    """Панель управления пользователями.

    Колонки таблицы: Логин | Роль | Создан | Последний вход | Входов | Активен
    """

    _HEADER_TITLE = "Управление пользователями"
    _TABLE_COLUMNS = [
        ("username",      "Логин",           160),
        ("role_name",     "Роль",            100),
        ("created_at",    "Создан",          120),
        ("last_login_at", "Последний вход",  120),
        ("login_count",   "Входов",           60),
        ("is_active",     "Активен",          70),
    ]

    def __init__(self, auth: "AuthContext | None", parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._auth_manager = auth.manager if auth is not None else None
        self._auth_state = auth.state if auth is not None else None
        self._users: list[dict] = []

        self._setup_ui()
        self._wire_permissions()
        self._load_users()

    # ------------------------------------------------------------------
    # Построение интерфейса
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Построить layout панели."""
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Стандартный заголовок из BaseAdminPanel
        self._create_header(root)

        # Таблица пользователей из BaseAdminPanel
        self._table = self._create_table()

        root.addWidget(self._table, stretch=1)

        # Кнопки создаются здесь, но размещаются в action panel секции
        self._btn_add = QPushButton("Добавить")
        self._btn_add.setToolTip("Создать нового пользователя")
        self._btn_add.clicked.connect(self._on_add_clicked)

        self._btn_delete = QPushButton("Удалить")
        self._btn_delete.setToolTip("Удалить выбранного пользователя")
        self._btn_delete.clicked.connect(self._on_delete_clicked)

        self._btn_change_role = QPushButton("Сменить роль")
        self._btn_change_role.setToolTip("Изменить роль выбранного пользователя")
        self._btn_change_role.clicked.connect(self._on_change_role_clicked)

        self._btn_reset_pwd = QPushButton("Сбросить пароль")
        self._btn_reset_pwd.setToolTip("Сгенерировать новый пароль для выбранного пользователя")
        self._btn_reset_pwd.clicked.connect(self._on_reset_password_clicked)

    def action_buttons(self) -> list[QPushButton]:
        """Кнопки действий для размещения в action panel секции."""
        return [self._btn_add, self._btn_delete, self._btn_change_role, self._btn_reset_pwd]

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------

    _BUTTON_PERMISSIONS = (
        # (attr_name, permission)
        ("_btn_add",         "users.create"),
        ("_btn_delete",      "users.delete"),
        ("_btn_change_role", "users.edit"),
        ("_btn_reset_pwd",   "users.reset_password"),
    )

    def _wire_permissions(self) -> None:
        """Привязать CRUD-кнопки к users.* permissions с учётом transient-блокировки.

        Кнопка enabled только если выдан соответствующий permission. Transient
        блокировка (`_set_buttons_enabled(False)` во время операций) приоритетна
        над permission. Подписка на `AuthState.access_context_changed` реагирует
        на login/logout/смену роли.
        """
        if self._auth_state is None:
            return
        self._auth_state.access_context_changed.connect(
            lambda _ctx: self._apply_permissions()
        )
        self._apply_permissions()

    def _apply_permissions(self) -> None:
        """Установить enabled-состояние кнопок по текущим permissions.

        Сторонняя transient блокировка не учитывается — после её снятия
        вызывается этот же метод (см. `_set_buttons_enabled`).
        """
        if self._auth_state is None:
            return
        ctx = self._auth_state.access_context
        for attr, perm in self._BUTTON_PERMISSIONS:
            btn = getattr(self, attr)
            allowed = ctx.has_permission(perm)
            btn.setEnabled(allowed)
            btn.setProperty("readOnly", not allowed)
            style = btn.style()
            if style is not None:
                style.unpolish(btn)
                style.polish(btn)

    # ------------------------------------------------------------------
    # Загрузка данных
    # ------------------------------------------------------------------

    def _load_users(self) -> None:
        """Загрузить список через auth_manager.list_users() и заполнить таблицу."""
        if self._auth_manager is None:
            return
        try:
            self._users = self._auth_manager.list_users()
        except AuthError as e:
            QMessageBox.critical(self, "Ошибка загрузки", str(e))
            self._users = []
        self._fill_table()

    def _fill_table(self) -> None:
        """Заполнить таблицу из self._users."""
        self._table.setRowCount(len(self._users))
        for row, user in enumerate(self._users):
            for col, key in enumerate(self.column_keys):
                value = user.get(key, "")
                # Форматирование специальных полей
                if key == "is_active":
                    display = "Да" if value else "Нет"
                elif key == "last_login_at":
                    display = self._format_datetime(value)
                elif key == "created_at":
                    display = self._format_datetime(value)
                else:
                    display = str(value) if value is not None else "—"

                item = QTableWidgetItem(display)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col, item)

    @staticmethod
    def _format_datetime(value: object) -> str:
        """Отформатировать datetime-значение для отображения в таблице."""
        if value is None or value == "" or value == "None":
            return "—"
        # Значение может прийти как строка ISO-8601 или datetime
        val_str = str(value)
        # Обрезаем до даты+времени без микросекунд если строка длинная
        if "T" in val_str:
            # ISO-формат: 2024-01-15T10:30:00.123456
            parts = val_str.split("T")
            date_part = parts[0]
            time_part = parts[1].split(".")[0] if len(parts) > 1 else ""
            return f"{date_part} {time_part}".strip()
        return val_str

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _get_selected_username(self) -> str | None:
        """Вернуть username выбранной строки или None если ничего не выбрано."""
        row = self._table.currentRow()
        if row < 0 or row >= len(self._users):
            return None
        return self._users[row].get("username")

    def _set_buttons_enabled(self, enabled: bool) -> None:
        """Transient блокировка кнопок во время операций.

        При `False` отключает все кнопки. При `True` восстанавливает состояние
        из текущих permissions (без AuthState — включает все).
        """
        if not enabled:
            for attr, _ in self._BUTTON_PERMISSIONS:
                getattr(self, attr).setEnabled(False)
            return
        if self._auth_state is None:
            for attr, _ in self._BUTTON_PERMISSIONS:
                getattr(self, attr).setEnabled(True)
            return
        self._apply_permissions()

    def _open_confirm_dialog(self, action_text: str) -> bool:
        """Открыть ConfirmWithPasswordDialog и вернуть True если подтверждено."""
        from multiprocess_prototype.frontend.widgets.dialogs.confirm_with_password import (
            ConfirmWithPasswordDialog,
        )
        dlg = ConfirmWithPasswordDialog(
            self._auth_manager,
            action_text=action_text,
            parent=self,
        )
        dlg.exec()
        return dlg.confirmed

    # ------------------------------------------------------------------
    # Обработчики кнопок
    # ------------------------------------------------------------------

    def _on_add_clicked(self) -> None:
        """Открыть UserForm в диалоге. При accept → auth_manager.create_user() → reload."""
        if self._auth_manager is None:
            return

        form = UserForm(self._auth_manager, parent=self)
        if form.exec() != UserForm.DialogCode.Accepted:
            return

        data = form.result_data
        if data is None:
            return

        self._set_buttons_enabled(False)
        try:
            self._auth_manager.create_user(
                username=data["username"],
                password=data["password"],
                role_name=data["role_name"],
            )
            self._load_users()
        except WeakPassword as e:
            QMessageBox.warning(
                self,
                "Слабый пароль",
                f"Пароль не соответствует требованиям безопасности:\n\n{e}",
            )
        except AuthError as e:
            QMessageBox.critical(self, "Ошибка создания пользователя", str(e))
        finally:
            self._set_buttons_enabled(True)

    def _on_delete_clicked(self) -> None:
        """ConfirmWithPasswordDialog → auth_manager.delete_user(selected) → reload."""
        if self._auth_manager is None:
            return

        username = self._get_selected_username()
        if username is None:
            QMessageBox.information(self, "Выбор пользователя", "Выберите пользователя для удаления")
            return

        confirmed = self._open_confirm_dialog(f'Удалить пользователя «{username}»')
        if not confirmed:
            return

        self._set_buttons_enabled(False)
        try:
            self._auth_manager.delete_user(username)
            self._load_users()
        except LastAdminError as e:
            QMessageBox.warning(self, "Ошибка", str(e))
        except UserNotFound as e:
            QMessageBox.warning(self, "Ошибка", str(e))
        except AuthError as e:
            QMessageBox.critical(self, "Ошибка", str(e))
        finally:
            self._set_buttons_enabled(True)

    def _on_change_role_clicked(self) -> None:
        """Диалог смены роли (QInputDialog.getItem с list_roles()) → auth_manager.update_user_role() → reload."""
        if self._auth_manager is None:
            return

        username = self._get_selected_username()
        if username is None:
            QMessageBox.information(self, "Выбор пользователя", "Выберите пользователя для смены роли")
            return

        # Получить роли, исключая hidden_in_ui=True
        try:
            all_roles = self._auth_manager.list_roles()
        except AuthError as e:
            QMessageBox.critical(self, "Ошибка загрузки ролей", str(e))
            return

        visible_roles = [r["name"] for r in all_roles if not r.get("hidden_in_ui", False)]
        if not visible_roles:
            QMessageBox.warning(self, "Нет доступных ролей", "Нет ролей для назначения")
            return

        # Найти текущую роль выбранного пользователя
        current_role = ""
        row = self._table.currentRow()
        if 0 <= row < len(self._users):
            current_role = self._users[row].get("role_name", "")

        current_index = visible_roles.index(current_role) if current_role in visible_roles else 0

        new_role, ok = QInputDialog.getItem(
            self,
            "Сменить роль",
            f"Роль для «{username}»:",
            visible_roles,
            current=current_index,
            editable=False,
        )
        if not ok or new_role == current_role:
            return

        self._set_buttons_enabled(False)
        try:
            self._auth_manager.update_user_role(username, new_role)
            self._load_users()
        except LastAdminError as e:
            QMessageBox.warning(self, "Ошибка", str(e))
        except UserNotFound as e:
            QMessageBox.warning(self, "Ошибка", str(e))
        except AuthError as e:
            QMessageBox.critical(self, "Ошибка", str(e))
        finally:
            self._set_buttons_enabled(True)

    def _on_reset_password_clicked(self) -> None:
        """ConfirmWithPasswordDialog → auth_manager.reset_password(selected)
           → QMessageBox с новым паролем + автоматически копируется в clipboard.
        """
        if self._auth_manager is None:
            return

        username = self._get_selected_username()
        if username is None:
            QMessageBox.information(self, "Выбор пользователя", "Выберите пользователя для сброса пароля")
            return

        confirmed = self._open_confirm_dialog(f'Сбросить пароль пользователя «{username}»')
        if not confirmed:
            return

        self._set_buttons_enabled(False)
        try:
            new_password = self._auth_manager.reset_password(username)

            # Копировать в буфер обмена
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(new_password)

            QMessageBox.information(
                self,
                "Новый пароль",
                f"Новый пароль для «{username}»:\n\n{new_password}\n\n"
                "(Пароль скопирован в буфер обмена. Сохраните его — он больше не отобразится.)",
            )
            self._load_users()
        except UserNotFound as e:
            QMessageBox.warning(self, "Ошибка", str(e))
        except AuthError as e:
            QMessageBox.critical(self, "Ошибка", str(e))
        finally:
            self._set_buttons_enabled(True)
