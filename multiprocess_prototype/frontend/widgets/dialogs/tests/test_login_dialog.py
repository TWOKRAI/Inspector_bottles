# -*- coding: utf-8 -*-
"""Тесты LoginDialog — E.3 (PR2 auth-rbac).

Проверяет поведение диалога входа при:
  - успешной аутентификации
  - неверных учётных данных (InvalidCredentials)
  - заблокированном аккаунте (AccountLocked)
  - нажатии «Отмена»
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from Services.auth.exceptions import AccountLocked, InvalidCredentials
from Services.auth.interfaces import IAuthManager
from multiprocess_prototype.frontend.state.auth_state import AuthState
from multiprocess_prototype.frontend.widgets.dialogs.login_dialog import LoginDialog


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_state(qtbot):
    """AuthState (QObject, требует QApplication через qtbot)."""
    return AuthState()


@pytest.fixture
def mock_auth_manager():
    """Мок IAuthManager."""
    return MagicMock(spec=IAuthManager)


# ---------------------------------------------------------------------------
# Вспомогательные данные
# ---------------------------------------------------------------------------

_SUCCESS_RESULT = {
    "success": True,
    "username": "alice",
    "role_name": "admin",
    "permissions": ["users.view"],
    "level": 100,
    "message": "",
}


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestLoginDialogSuccess:
    """Успешный вход."""

    def test_login_success_sets_authenticated(self, qtbot, auth_state, mock_auth_manager):
        """После успешного login auth_state.is_authenticated == True."""
        mock_auth_manager.login.return_value = _SUCCESS_RESULT

        dlg = LoginDialog(mock_auth_manager, auth_state)
        qtbot.addWidget(dlg)

        dlg._username_edit.setText("alice")
        dlg._password_edit.setText("secret")
        dlg._on_ok_clicked()

        assert auth_state.is_authenticated is True

    def test_login_success_current_user_username(self, qtbot, auth_state, mock_auth_manager):
        """После успешного login auth_state.current_user['username'] == 'alice'."""
        mock_auth_manager.login.return_value = _SUCCESS_RESULT

        dlg = LoginDialog(mock_auth_manager, auth_state)
        qtbot.addWidget(dlg)

        dlg._username_edit.setText("alice")
        dlg._password_edit.setText("secret")
        dlg._on_ok_clicked()

        assert auth_state.current_user is not None
        assert auth_state.current_user["username"] == "alice"

    def test_login_success_login_result_not_none(self, qtbot, auth_state, mock_auth_manager):
        """После успешного login dlg.login_result is not None."""
        mock_auth_manager.login.return_value = _SUCCESS_RESULT

        dlg = LoginDialog(mock_auth_manager, auth_state)
        qtbot.addWidget(dlg)

        dlg._username_edit.setText("alice")
        dlg._password_edit.setText("secret")
        dlg._on_ok_clicked()

        assert dlg.login_result is not None

    def test_login_success_calls_login_with_correct_args(self, qtbot, auth_state, mock_auth_manager):
        """auth_manager.login вызван с правильными username и password."""
        mock_auth_manager.login.return_value = _SUCCESS_RESULT

        dlg = LoginDialog(mock_auth_manager, auth_state)
        qtbot.addWidget(dlg)

        dlg._username_edit.setText("alice")
        dlg._password_edit.setText("secret")
        dlg._on_ok_clicked()

        mock_auth_manager.login.assert_called_once_with("alice", "secret")


class TestLoginDialogInvalidCredentials:
    """Неверные учётные данные."""

    def test_invalid_credentials_not_authenticated(self, qtbot, auth_state, mock_auth_manager):
        """При InvalidCredentials auth_state.is_authenticated остаётся False."""
        mock_auth_manager.login.side_effect = InvalidCredentials("Неверный логин или пароль")

        dlg = LoginDialog(mock_auth_manager, auth_state)
        qtbot.addWidget(dlg)

        dlg._username_edit.setText("alice")
        dlg._password_edit.setText("wrong")
        dlg._on_ok_clicked()

        assert auth_state.is_authenticated is False

    def test_invalid_credentials_error_label_contains_text(self, qtbot, auth_state, mock_auth_manager):
        """При InvalidCredentials метка ошибки содержит «Неверный»."""
        mock_auth_manager.login.side_effect = InvalidCredentials("Неверный логин или пароль")

        dlg = LoginDialog(mock_auth_manager, auth_state)
        qtbot.addWidget(dlg)

        dlg._username_edit.setText("alice")
        dlg._password_edit.setText("wrong")
        dlg._on_ok_clicked()

        assert "Неверный" in dlg._error_label.text()

    def test_invalid_credentials_error_label_visible(self, qtbot, auth_state, mock_auth_manager):
        """При InvalidCredentials метка ошибки не скрыта (setVisible(True) вызван)."""
        mock_auth_manager.login.side_effect = InvalidCredentials("Неверный логин или пароль")

        dlg = LoginDialog(mock_auth_manager, auth_state)
        qtbot.addWidget(dlg)

        dlg._username_edit.setText("alice")
        dlg._password_edit.setText("wrong")
        dlg._on_ok_clicked()

        # isHidden() надёжнее isVisible() когда родитель не show()
        assert dlg._error_label.isHidden() is False

    def test_invalid_credentials_password_field_cleared(self, qtbot, auth_state, mock_auth_manager):
        """При InvalidCredentials поле пароля очищается."""
        mock_auth_manager.login.side_effect = InvalidCredentials("Неверный логин или пароль")

        dlg = LoginDialog(mock_auth_manager, auth_state)
        qtbot.addWidget(dlg)

        dlg._username_edit.setText("alice")
        dlg._password_edit.setText("wrong")
        dlg._on_ok_clicked()

        assert dlg._password_edit.text() == ""

    def test_invalid_credentials_dialog_not_accepted(self, qtbot, auth_state, mock_auth_manager):
        """При InvalidCredentials диалог не принят (login_result is None)."""
        mock_auth_manager.login.side_effect = InvalidCredentials("Неверный логин или пароль")

        dlg = LoginDialog(mock_auth_manager, auth_state)
        qtbot.addWidget(dlg)

        dlg._username_edit.setText("alice")
        dlg._password_edit.setText("wrong")
        dlg._on_ok_clicked()

        # Диалог не должен быть закрыт — login_result остаётся None
        assert dlg.login_result is None


class TestLoginDialogAccountLocked:
    """Аккаунт заблокирован."""

    def test_account_locked_not_authenticated(self, qtbot, auth_state, mock_auth_manager):
        """При AccountLocked auth_state.is_authenticated остаётся False."""
        mock_auth_manager.login.side_effect = AccountLocked(
            "Аккаунт заблокирован", failures=5, delay_sec=60
        )

        dlg = LoginDialog(mock_auth_manager, auth_state)
        qtbot.addWidget(dlg)

        dlg._username_edit.setText("alice")
        dlg._password_edit.setText("wrong")
        dlg._on_ok_clicked()

        assert auth_state.is_authenticated is False

    def test_account_locked_error_contains_failures(self, qtbot, auth_state, mock_auth_manager):
        """При AccountLocked сообщение об ошибке содержит число попыток (5)."""
        mock_auth_manager.login.side_effect = AccountLocked(
            "Аккаунт заблокирован", failures=5, delay_sec=60
        )

        dlg = LoginDialog(mock_auth_manager, auth_state)
        qtbot.addWidget(dlg)

        dlg._username_edit.setText("alice")
        dlg._password_edit.setText("wrong")
        dlg._on_ok_clicked()

        assert "5" in dlg._error_label.text()

    def test_account_locked_error_contains_delay(self, qtbot, auth_state, mock_auth_manager):
        """При AccountLocked сообщение об ошибке содержит время задержки (60)."""
        mock_auth_manager.login.side_effect = AccountLocked(
            "Аккаунт заблокирован", failures=5, delay_sec=60
        )

        dlg = LoginDialog(mock_auth_manager, auth_state)
        qtbot.addWidget(dlg)

        dlg._username_edit.setText("alice")
        dlg._password_edit.setText("wrong")
        dlg._on_ok_clicked()

        assert "60" in dlg._error_label.text()

    def test_account_locked_password_cleared(self, qtbot, auth_state, mock_auth_manager):
        """При AccountLocked поле пароля очищается."""
        mock_auth_manager.login.side_effect = AccountLocked(
            "Аккаунт заблокирован", failures=5, delay_sec=60
        )

        dlg = LoginDialog(mock_auth_manager, auth_state)
        qtbot.addWidget(dlg)

        dlg._username_edit.setText("alice")
        dlg._password_edit.setText("wrong")
        dlg._on_ok_clicked()

        assert dlg._password_edit.text() == ""


class TestLoginDialogCancel:
    """Отмена диалога."""

    def test_cancel_does_not_set_user(self, qtbot, auth_state, mock_auth_manager):
        """reject() не выполняет login и не меняет auth_state."""
        dlg = LoginDialog(mock_auth_manager, auth_state)
        qtbot.addWidget(dlg)

        dlg.reject()

        mock_auth_manager.login.assert_not_called()
        assert auth_state.is_authenticated is False

    def test_cancel_login_result_is_none(self, qtbot, auth_state, mock_auth_manager):
        """После reject() login_result остаётся None."""
        dlg = LoginDialog(mock_auth_manager, auth_state)
        qtbot.addWidget(dlg)

        dlg.reject()

        assert dlg.login_result is None
