# -*- coding: utf-8 -*-
"""UserForm — диалог создания нового пользователя.

Используется в UsersPanel._on_add_clicked().
После exec():
    .result_data: dict | None — заполненные поля или None при отмене.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from Services.auth.interfaces import IAuthManager


class UserForm(QDialog):
    """Диалог создания нового пользователя.

    Поля:
      - «Логин»   QLineEdit  (username, обязательное)
      - «Пароль»  QLineEdit  (echoMode=Password, обязательное)
      - «Роль»    QComboBox  (role_name, список из list_roles(), скрыть hidden_in_ui=True)
      - «Активен» QCheckBox  (is_active, по умолчанию True)

    Результат:
      .result_data: dict | None — dict с полями username/password/role_name/is_active
                                    или None при отмене.
    """

    result_data: dict | None

    def __init__(
        self,
        auth_manager: "IAuthManager",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Создать пользователя")
        self.setMinimumWidth(380)

        self._auth_manager = auth_manager
        self.result_data = None

        # Загрузить роли заранее (скрыть hidden_in_ui=True)
        all_roles = auth_manager.list_roles()
        self._visible_roles: list[dict] = [
            r for r in all_roles if not r.get("hidden_in_ui", False)
        ]

        # --- Главный layout ---
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(8)

        # --- Форма ---
        form = QFormLayout()
        form.setSpacing(8)

        # Логин
        self._username_edit = QLineEdit()
        self._username_edit.setPlaceholderText("Введите логин")
        form.addRow("Логин:", self._username_edit)

        # Пароль
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_edit.setPlaceholderText("Введите пароль")
        form.addRow("Пароль:", self._password_edit)

        # Метка ошибки пароля (скрыта по умолчанию)
        self._password_error_label = QLabel("")
        self._password_error_label.setStyleSheet("color: #d32f2f; font-size: 11px;")
        self._password_error_label.setVisible(False)
        self._password_error_label.setWordWrap(True)
        form.addRow("", self._password_error_label)

        # Роль
        self._role_combo = QComboBox()
        for role in self._visible_roles:
            self._role_combo.addItem(role["name"], userData=role["name"])
        form.addRow("Роль:", self._role_combo)

        # Активен
        self._active_check = QCheckBox()
        self._active_check.setChecked(True)
        form.addRow("Активен:", self._active_check)

        main_layout.addLayout(form)

        # --- Кнопки ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Создать")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self._on_ok_clicked)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def show_password_error(self, message: str) -> None:
        """Показать сообщение об ошибке пароля под полем.

        Вызывается из UsersPanel при получении WeakPassword от backend.
        """
        self._password_error_label.setText(message)
        self._password_error_label.setVisible(True)
        self._password_edit.setStyleSheet("border: 1px solid #d32f2f;")
        self._password_edit.setFocus()

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _validate(self) -> bool:
        """Проверить обязательные поля — логин и пароль непустые.

        Подсвечивает незаполненные поля красным.
        Возвращает True если всё заполнено, False иначе.
        """
        valid = True

        username = self._username_edit.text().strip()
        if not username:
            self._username_edit.setStyleSheet("border: 1px solid #d32f2f;")
            valid = False
        else:
            self._username_edit.setStyleSheet("")

        password = self._password_edit.text()
        if not password:
            self._password_edit.setStyleSheet("border: 1px solid #d32f2f;")
            self._password_error_label.setText("Пароль не может быть пустым")
            self._password_error_label.setVisible(True)
            valid = False
        else:
            # Не сбрасываем стиль сразу — он может быть установлен show_password_error
            if not self._password_error_label.isVisible():
                self._password_edit.setStyleSheet("")

        return valid

    def _on_ok_clicked(self) -> None:
        """Собрать result_data и закрыть диалог с accept()."""
        # Сбросить предыдущую ошибку пароля перед новой валидацией
        self._password_error_label.setVisible(False)
        self._password_edit.setStyleSheet("")

        if not self._validate():
            return

        role_name: str = self._role_combo.currentData() or self._role_combo.currentText()

        self.result_data = {
            "username": self._username_edit.text().strip(),
            "password": self._password_edit.text(),
            "role_name": role_name,
            "is_active": self._active_check.isChecked(),
        }
        self.accept()
