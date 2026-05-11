# -*- coding: utf-8 -*-
"""ConfirmWithPasswordDialog — диалог подтверждения деструктивного действия с паролем.

Используется при удалении пользователя, сбросе пароля и других операциях,
требующих явного подтверждения пароля администратора.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from Services.auth.interfaces import IAuthManager


class ConfirmWithPasswordDialog(QDialog):
    """Диалог подтверждения деструктивного действия с вводом пароля.

    Используется при: удалении пользователя, сбросе пароля.

    Параметры конструктора:
        auth_manager  — для verify_admin_password()
        action_text   — описание действия (например, «Удалить пользователя "alice"»)
        parent        — родительский виджет

    После exec():
        .confirmed: bool — True если пользователь ввёл верный пароль и нажал OK.
    """

    confirmed: bool

    def __init__(
        self,
        auth_manager: "IAuthManager",
        action_text: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Подтверждение действия")
        self.setMinimumWidth(380)

        self._auth_manager = auth_manager
        self.confirmed = False

        # --- Layout ---
        _layout = QVBoxLayout(self)
        _layout.setSpacing(12)
        _layout.setContentsMargins(20, 20, 20, 20)

        # Текст описания действия — жирный
        _action_label = QLabel(action_text)
        _action_label.setObjectName("ConfirmActionLabel")
        _action_label.setWordWrap(True)
        _action_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        # Жирный шрифт для акцента на описании действия
        _font = _action_label.font()
        _font.setBold(True)
        _action_label.setFont(_font)
        _layout.addWidget(_action_label)

        # Метка поля пароля
        _password_label = QLabel("Пароль администратора:")
        _layout.addWidget(_password_label)

        # Поле ввода пароля
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_edit.setObjectName("ConfirmPasswordEdit")
        _layout.addWidget(self._password_edit)

        # Метка ошибки — скрыта по умолчанию
        self._error_label = QLabel("Неверный пароль")
        self._error_label.setObjectName("ConfirmErrorLabel")
        self._error_label.setStyleSheet("color: #d32f2f;")
        self._error_label.setVisible(False)
        _layout.addWidget(self._error_label)

        # Кнопки
        _buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        _buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Подтвердить")
        _buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        _buttons.accepted.connect(self._on_ok_clicked)
        _buttons.rejected.connect(self.reject)
        _layout.addWidget(_buttons)

        # Enter в поле пароля — эквивалент «Подтвердить»
        self._password_edit.returnPressed.connect(self._on_ok_clicked)

    def _on_ok_clicked(self) -> None:
        """auth_manager.verify_admin_password(password) → accept() или показать ошибку."""
        password = self._password_edit.text()
        self._error_label.setVisible(False)

        if self._auth_manager.verify_admin_password(password):
            self.confirmed = True
            self.accept()
        else:
            # Неверный пароль — показываем ошибку, очищаем поле
            self._error_label.setVisible(True)
            self._password_edit.clear()
            self._password_edit.setFocus()
