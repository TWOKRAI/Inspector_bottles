# -*- coding: utf-8 -*-
"""Тесты ConfirmWithPasswordDialog — E.4 (PR2 auth-rbac).

Проверяет поведение диалога подтверждения с паролем при:
  - верном пароле (confirmed == True, диалог закрыт)
  - неверном пароле (confirmed == False, ошибка, диалог не закрыт)
  - отмене без ввода пароля
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QDialog

from Services.auth.interfaces import IAuthManager
from multiprocess_prototype.frontend.widgets.dialogs.confirm_with_password import (
    ConfirmWithPasswordDialog,
)


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_auth_manager():
    """Мок IAuthManager."""
    return MagicMock(spec=IAuthManager)


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


class TestConfirmWithPasswordCorrect:
    """Верный пароль — диалог подтверждён."""

    def test_correct_password_confirmed_true(self, qtbot, mock_auth_manager):
        """При верном пароле dlg.confirmed == True."""
        mock_auth_manager.verify_admin_password.return_value = True

        dlg = ConfirmWithPasswordDialog(mock_auth_manager, "Удалить пользователя alice")
        qtbot.addWidget(dlg)

        dlg._password_edit.setText("admin_pass")
        dlg._on_ok_clicked()

        assert dlg.confirmed is True

    def test_correct_password_dialog_accepted(self, qtbot, mock_auth_manager):
        """При верном пароле диалог закрывается с результатом Accepted."""
        mock_auth_manager.verify_admin_password.return_value = True

        dlg = ConfirmWithPasswordDialog(mock_auth_manager, "Удалить пользователя alice")
        qtbot.addWidget(dlg)

        dlg._password_edit.setText("admin_pass")
        dlg._on_ok_clicked()

        assert dlg.result() == QDialog.DialogCode.Accepted

    def test_correct_password_verify_called_with_password(self, qtbot, mock_auth_manager):
        """verify_admin_password вызван с переданным паролем."""
        mock_auth_manager.verify_admin_password.return_value = True

        dlg = ConfirmWithPasswordDialog(mock_auth_manager, "Удалить пользователя alice")
        qtbot.addWidget(dlg)

        dlg._password_edit.setText("admin_pass")
        dlg._on_ok_clicked()

        mock_auth_manager.verify_admin_password.assert_called_once_with("admin_pass")


class TestConfirmWithPasswordWrong:
    """Неверный пароль — диалог не принят."""

    def test_wrong_password_confirmed_false(self, qtbot, mock_auth_manager):
        """При неверном пароле dlg.confirmed == False."""
        mock_auth_manager.verify_admin_password.return_value = False

        dlg = ConfirmWithPasswordDialog(mock_auth_manager, "Удалить пользователя alice")
        qtbot.addWidget(dlg)

        dlg._password_edit.setText("wrong_pass")
        dlg._on_ok_clicked()

        assert dlg.confirmed is False

    def test_wrong_password_error_label_visible(self, qtbot, mock_auth_manager):
        """При неверном пароле метка ошибки не скрыта (setVisible(True) вызван)."""
        mock_auth_manager.verify_admin_password.return_value = False

        dlg = ConfirmWithPasswordDialog(mock_auth_manager, "Удалить пользователя alice")
        qtbot.addWidget(dlg)

        dlg._password_edit.setText("wrong_pass")
        dlg._on_ok_clicked()

        # isHidden() надёжнее isVisible() когда родитель не show()
        assert dlg._error_label.isHidden() is False

    def test_wrong_password_field_cleared(self, qtbot, mock_auth_manager):
        """При неверном пароле поле пароля очищается."""
        mock_auth_manager.verify_admin_password.return_value = False

        dlg = ConfirmWithPasswordDialog(mock_auth_manager, "Удалить пользователя alice")
        qtbot.addWidget(dlg)

        dlg._password_edit.setText("wrong_pass")
        dlg._on_ok_clicked()

        assert dlg._password_edit.text() == ""

    def test_wrong_password_dialog_not_accepted(self, qtbot, mock_auth_manager):
        """При неверном пароле диалог не переходит в состояние Accepted."""
        mock_auth_manager.verify_admin_password.return_value = False

        dlg = ConfirmWithPasswordDialog(mock_auth_manager, "Удалить пользователя alice")
        qtbot.addWidget(dlg)

        dlg._password_edit.setText("wrong_pass")
        dlg._on_ok_clicked()

        assert dlg.result() != QDialog.DialogCode.Accepted


class TestConfirmWithPasswordCancel:
    """Отмена диалога."""

    def test_cancel_not_confirmed(self, qtbot, mock_auth_manager):
        """После reject() confirmed == False."""
        dlg = ConfirmWithPasswordDialog(mock_auth_manager, "Удалить пользователя alice")
        qtbot.addWidget(dlg)

        dlg.reject()

        assert dlg.confirmed is False

    def test_cancel_verify_not_called(self, qtbot, mock_auth_manager):
        """После reject() verify_admin_password не вызывался."""
        dlg = ConfirmWithPasswordDialog(mock_auth_manager, "Удалить пользователя alice")
        qtbot.addWidget(dlg)

        dlg.reject()

        mock_auth_manager.verify_admin_password.assert_not_called()
