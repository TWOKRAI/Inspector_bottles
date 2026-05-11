# -*- coding: utf-8 -*-
"""LoginDialog — диалог входа в систему.

Поля «Логин» и «Пароль», кнопки «Войти» / «Отмена».
После успешного входа устанавливает login_result (dict) и вызывает accept().
При ошибках показывает сообщение под формой, не закрывает диалог.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.managers.access_context import (
    AccessContext,
)
from Services.auth.exceptions import AccountLocked, AuthError, InvalidCredentials

if TYPE_CHECKING:
    from Services.auth.interfaces import IAuthManager
    from multiprocess_prototype.frontend.state.auth_state import AuthState


class LoginDialog(QDialog):
    """Диалог входа: поля «Логин» и «Пароль» + кнопки «Войти» / «Отмена».

    Результат: LoginDialog.login_result: dict | None.
    Если None — пользователь отменил или произошла ошибка.
    """

    login_result: dict | None

    def __init__(
        self,
        auth_manager: "IAuthManager",
        auth_state: "AuthState",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Вход в систему")
        self.setMinimumWidth(380)

        self._auth_manager = auth_manager
        self._auth_state = auth_state
        self.login_result = None

        # --- Основной layout ---
        _outer_layout = QVBoxLayout(self)
        _outer_layout.setSpacing(12)
        _outer_layout.setContentsMargins(20, 20, 20, 20)

        # Форма с полями
        _form_layout = QFormLayout()
        _form_layout.setSpacing(8)

        self._username_edit = QLineEdit()
        self._username_edit.setPlaceholderText("Имя пользователя")
        self._username_edit.setObjectName("LoginUsernameEdit")
        _form_layout.addRow("Логин:", self._username_edit)

        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_edit.setObjectName("LoginPasswordEdit")
        _form_layout.addRow("Пароль:", self._password_edit)

        _outer_layout.addLayout(_form_layout)

        # Метка ошибки — красный текст, скрыта по умолчанию
        self._error_label = QLabel("")
        self._error_label.setObjectName("LoginErrorLabel")
        self._error_label.setStyleSheet("color: #d32f2f;")
        self._error_label.setWordWrap(True)
        self._error_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._error_label.setVisible(False)
        _outer_layout.addWidget(self._error_label)

        # Кнопки
        _buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        _buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Войти")
        _buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        _buttons.accepted.connect(self._on_ok_clicked)
        _buttons.rejected.connect(self.reject)
        _outer_layout.addWidget(_buttons)

        # Enter в любом поле — эквивалент нажатия «Войти»
        self._username_edit.returnPressed.connect(self._on_ok_clicked)
        self._password_edit.returnPressed.connect(self._on_ok_clicked)

    def _on_ok_clicked(self) -> None:
        """Вызвать auth_manager.login(username, password).

        Успех:
            login_result = result_dict
            AccessContext.from_dict(result_dict) → auth_state.set_user(result_dict, ctx)
            self.accept()

        Ошибки (каждая — свой текст под полями):
            InvalidCredentials  → «Неверный логин или пароль»
            AccountLocked       → «Аккаунт заблокирован. Попыток: {N}. Подождите {M} сек.»
            AuthError (прочее)  → «Ошибка входа: {str(e)}»

        Поле пароля очищается при любой ошибке.
        Фокус возвращается на поле логина при InvalidCredentials,
        на поле пароля при AccountLocked.

        # TODO(PR4): обернуть в QThread если bcrypt latency > 150 мс на целевом оборудовании
        """
        username = self._username_edit.text().strip()
        password = self._password_edit.text()

        self._hide_error()

        try:
            result = self._auth_manager.login(username, password)
        except InvalidCredentials:
            self._show_error("Неверный логин или пароль")
            self._password_edit.clear()
            self._username_edit.setFocus()
            return
        except AccountLocked as exc:
            self._show_error(
                f"Аккаунт заблокирован. Попыток: {exc.failures}. "
                f"Подождите {exc.delay_sec} сек."
            )
            self._password_edit.clear()
            self._password_edit.setFocus()
            return
        except AuthError as exc:
            self._show_error(f"Ошибка входа: {exc}")
            self._password_edit.clear()
            return

        # Успешный вход
        ctx = AccessContext.from_dict(result)
        self._auth_state.set_user(result, ctx)
        self.login_result = result
        self.accept()

    def _show_error(self, text: str) -> None:
        """Показать сообщение об ошибке под формой."""
        self._error_label.setText(text)
        self._error_label.setVisible(True)

    def _hide_error(self) -> None:
        """Скрыть метку ошибки."""
        self._error_label.setVisible(False)
        self._error_label.setText("")
