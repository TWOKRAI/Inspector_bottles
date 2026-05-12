# -*- coding: utf-8 -*-
"""Тесты UsersPanel — E.5 (PR2 auth-rbac).

Проверяет поведение панели управления пользователями:
  - загрузка списка пользователей (test_load_users)
  - добавление пользователя через UserForm (test_add_user)
  - удаление с подтверждением пароля (test_delete_user_calls_confirm)
  - сброс пароля с показом QMessageBox (test_reset_password_shows_alert)
  - ошибка LastAdminError при удалении (test_last_admin_error_shows_warning)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QDialog

from Services.auth.exceptions import LastAdminError
from Services.auth.interfaces import IAuthManager
from multiprocess_prototype.frontend.widgets.tabs.settings.administration.users_panel import (
    UsersPanel,
)


# ---------------------------------------------------------------------------
# Тестовые данные
# ---------------------------------------------------------------------------

_USER_ALICE = {
    "username": "alice",
    "role_name": "admin",
    "is_active": True,
    "created_at": "2026-01-01T00:00:00",
    "last_login_at": None,
    "login_count": 0,
}

_USER_BOB = {
    "username": "bob",
    "role_name": "operator",
    "is_active": True,
    "created_at": "2026-02-01T00:00:00",
    "last_login_at": "2026-05-01T10:00:00",
    "login_count": 3,
}

_ROLE_ADMIN = {"name": "admin", "hidden_in_ui": False, "level": 9, "permissions": []}
_ROLE_OPERATOR = {"name": "operator", "hidden_in_ui": False, "level": 3, "permissions": []}


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_auth_manager():
    """Мок IAuthManager с дефолтным поведением (пустой список пользователей)."""
    mgr = MagicMock(spec=IAuthManager)
    mgr.list_users.return_value = []
    mgr.list_roles.return_value = [_ROLE_ADMIN, _ROLE_OPERATOR]
    return mgr


@pytest.fixture
def mock_ctx(mock_auth_manager):
    """Мок AuthContext: manager = mock_auth_manager, state = None."""
    ctx = MagicMock()
    ctx.manager = mock_auth_manager
    ctx.state = None
    return ctx


# ---------------------------------------------------------------------------
# E.5.1 — Загрузка пользователей
# ---------------------------------------------------------------------------


class TestUsersPanelLoadUsers:
    """Таблица заполняется из list_users()."""

    def test_load_users_two_rows(self, qtbot, mock_ctx, mock_auth_manager):
        """При list_users() с 2 пользователями таблица содержит 2 строки."""
        mock_auth_manager.list_users.return_value = [_USER_ALICE, _USER_BOB]

        panel = UsersPanel(mock_ctx)
        qtbot.addWidget(panel)

        assert panel._table.rowCount() == 2

    def test_load_users_empty(self, qtbot, mock_ctx, mock_auth_manager):
        """При list_users() == [] таблица содержит 0 строк."""
        mock_auth_manager.list_users.return_value = []

        panel = UsersPanel(mock_ctx)
        qtbot.addWidget(panel)

        assert panel._table.rowCount() == 0

    def test_load_users_first_cell_username(self, qtbot, mock_ctx, mock_auth_manager):
        """Первая ячейка первой строки — username первого пользователя."""
        mock_auth_manager.list_users.return_value = [_USER_ALICE, _USER_BOB]

        panel = UsersPanel(mock_ctx)
        qtbot.addWidget(panel)

        item = panel._table.item(0, 0)
        assert item is not None
        assert item.text() == "alice"


# ---------------------------------------------------------------------------
# E.5.2 — Добавление пользователя
# ---------------------------------------------------------------------------


class TestUsersPanelAddUser:
    """Добавление пользователя через UserForm."""

    def test_add_user_calls_create_user(self, qtbot, mock_ctx, mock_auth_manager, monkeypatch):
        """_on_add_clicked() → create_user вызван с правильными аргументами."""
        mock_auth_manager.list_users.return_value = []
        mock_auth_manager.list_roles.return_value = [_ROLE_ADMIN]

        # Подмена UserForm: возвращает Accepted с result_data
        result_data = {
            "username": "new_user",
            "password": "Pass123!",
            "role_name": "admin",
            "is_active": True,
        }

        class FakeUserForm:
            DialogCode = QDialog.DialogCode

            def __init__(self, auth_manager, parent=None):
                self.result_data = result_data

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(
            "multiprocess_prototype.frontend.widgets.tabs.settings.administration.users_panel.UserForm",
            FakeUserForm,
        )

        panel = UsersPanel(mock_ctx)
        qtbot.addWidget(panel)

        panel._on_add_clicked()

        mock_auth_manager.create_user.assert_called_once_with(
            username="new_user",
            password="Pass123!",
            role_name="admin",
        )

    def test_add_user_reloads_list(self, qtbot, mock_ctx, mock_auth_manager, monkeypatch):
        """После create_user list_users вызывается повторно (reload)."""
        mock_auth_manager.list_users.return_value = []
        mock_auth_manager.list_roles.return_value = [_ROLE_ADMIN]

        result_data = {
            "username": "new_user",
            "password": "Pass123!",
            "role_name": "admin",
            "is_active": True,
        }

        class FakeUserForm:
            DialogCode = QDialog.DialogCode

            def __init__(self, auth_manager, parent=None):
                self.result_data = result_data

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(
            "multiprocess_prototype.frontend.widgets.tabs.settings.administration.users_panel.UserForm",
            FakeUserForm,
        )

        panel = UsersPanel(mock_ctx)
        qtbot.addWidget(panel)

        # Сбросить счётчик после __init__
        mock_auth_manager.list_users.reset_mock()

        panel._on_add_clicked()

        # list_users должен быть вызван для reload
        mock_auth_manager.list_users.assert_called()

    def test_add_user_cancel_no_create(self, qtbot, mock_ctx, mock_auth_manager, monkeypatch):
        """Если форма отменена — create_user не вызывается."""
        mock_auth_manager.list_users.return_value = []
        mock_auth_manager.list_roles.return_value = [_ROLE_ADMIN]

        class FakeUserFormCancelled:
            DialogCode = QDialog.DialogCode

            def __init__(self, auth_manager, parent=None):
                self.result_data = None

            def exec(self):
                return QDialog.DialogCode.Rejected

        monkeypatch.setattr(
            "multiprocess_prototype.frontend.widgets.tabs.settings.administration.users_panel.UserForm",
            FakeUserFormCancelled,
        )

        panel = UsersPanel(mock_ctx)
        qtbot.addWidget(panel)

        panel._on_add_clicked()

        mock_auth_manager.create_user.assert_not_called()


# ---------------------------------------------------------------------------
# E.5.3 — Удаление пользователя с подтверждением
# ---------------------------------------------------------------------------


class TestUsersPanelDeleteUser:
    """Удаление пользователя через ConfirmWithPasswordDialog."""

    def test_delete_user_calls_confirm(self, qtbot, mock_ctx, mock_auth_manager):
        """_on_delete_clicked() инстанцирует ConfirmWithPasswordDialog."""
        mock_auth_manager.list_users.return_value = [_USER_ALICE]

        confirm_instances = []

        class FakeConfirm:
            def __init__(self, auth_manager, action_text, parent=None):
                self.confirmed = True
                confirm_instances.append(self)

            def exec(self):
                return QDialog.DialogCode.Accepted

        # ConfirmWithPasswordDialog импортируется внутри _open_confirm_dialog через
        # локальный from ... import — патчим точку импорта в модуле confirm_with_password
        with patch(
            "multiprocess_prototype.frontend.widgets.dialogs.confirm_with_password.ConfirmWithPasswordDialog",
            FakeConfirm,
        ):
            panel = UsersPanel(mock_ctx)
            qtbot.addWidget(panel)
            panel._table.selectRow(0)
            panel._on_delete_clicked()

        assert len(confirm_instances) == 1

    def test_delete_user_calls_delete_method(self, qtbot, mock_ctx, mock_auth_manager):
        """После подтверждения вызывается delete_user с правильным username."""
        mock_auth_manager.list_users.return_value = [_USER_ALICE]

        class FakeConfirm:
            def __init__(self, auth_manager, action_text, parent=None):
                self.confirmed = True

            def exec(self):
                return QDialog.DialogCode.Accepted

        # Патчим локальный импорт внутри _open_confirm_dialog
        with patch(
            "multiprocess_prototype.frontend.widgets.dialogs.confirm_with_password.ConfirmWithPasswordDialog",
            FakeConfirm,
        ):
            panel = UsersPanel(mock_ctx)
            qtbot.addWidget(panel)
            panel._table.selectRow(0)
            panel._on_delete_clicked()

        mock_auth_manager.delete_user.assert_called_once_with("alice")


# ---------------------------------------------------------------------------
# E.5.4 — Сброс пароля с показом QMessageBox
# ---------------------------------------------------------------------------


class TestUsersPanelResetPassword:
    """Сброс пароля: QMessageBox.information вызывается с новым паролем."""

    def test_reset_password_shows_alert(self, qtbot, mock_ctx, mock_auth_manager, monkeypatch):
        """_on_reset_password_clicked() показывает QMessageBox с новым паролем."""
        mock_auth_manager.list_users.return_value = [_USER_ALICE]
        mock_auth_manager.reset_password.return_value = "NEW_PASS_42"

        # Мок ConfirmWithPasswordDialog — подтверждаем
        class FakeConfirm:
            def __init__(self, auth_manager, action_text, parent=None):
                self.confirmed = True

            def exec(self):
                return QDialog.DialogCode.Accepted

        msgbox_calls: list[tuple] = []

        def fake_information(parent, title, text):
            msgbox_calls.append((title, text))

        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.information",
            fake_information,
        )

        # Патчим локальный импорт ConfirmWithPasswordDialog внутри _open_confirm_dialog
        with patch(
            "multiprocess_prototype.frontend.widgets.dialogs.confirm_with_password.ConfirmWithPasswordDialog",
            FakeConfirm,
        ):
            panel = UsersPanel(mock_ctx)
            qtbot.addWidget(panel)
            panel._table.selectRow(0)
            panel._on_reset_password_clicked()

        assert len(msgbox_calls) >= 1
        # Текст хотя бы одного вызова содержит новый пароль
        combined_text = " ".join(text for _, text in msgbox_calls)
        assert "NEW_PASS_42" in combined_text

    def test_reset_password_calls_reset_method(self, qtbot, mock_ctx, mock_auth_manager, monkeypatch):
        """reset_password(username) вызван для выбранного пользователя."""
        mock_auth_manager.list_users.return_value = [_USER_ALICE]
        mock_auth_manager.reset_password.return_value = "NEW_PASS_42"

        class FakeConfirm:
            def __init__(self, auth_manager, action_text, parent=None):
                self.confirmed = True

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.information",
            lambda *a: None,
        )

        # Патчим локальный импорт ConfirmWithPasswordDialog внутри _open_confirm_dialog
        with patch(
            "multiprocess_prototype.frontend.widgets.dialogs.confirm_with_password.ConfirmWithPasswordDialog",
            FakeConfirm,
        ):
            panel = UsersPanel(mock_ctx)
            qtbot.addWidget(panel)
            panel._table.selectRow(0)
            panel._on_reset_password_clicked()

        mock_auth_manager.reset_password.assert_called_once_with("alice")


# ---------------------------------------------------------------------------
# E.5.5 — LastAdminError при удалении
# ---------------------------------------------------------------------------


class TestUsersPanelLastAdminError:
    """Попытка удалить последнего администратора — показывается предупреждение."""

    def test_last_admin_error_shows_warning(self, qtbot, mock_ctx, mock_auth_manager, monkeypatch):
        """QMessageBox.warning вызван при LastAdminError."""
        mock_auth_manager.list_users.return_value = [_USER_ALICE]
        mock_auth_manager.delete_user.side_effect = LastAdminError(
            "Нельзя удалить последнего admin"
        )

        class FakeConfirm:
            def __init__(self, auth_manager, action_text, parent=None):
                self.confirmed = True

            def exec(self):
                return QDialog.DialogCode.Accepted

        warning_calls: list[tuple] = []

        def fake_warning(parent, title, text):
            warning_calls.append((title, text))

        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.warning",
            fake_warning,
        )

        # Патчим локальный импорт ConfirmWithPasswordDialog внутри _open_confirm_dialog
        with patch(
            "multiprocess_prototype.frontend.widgets.dialogs.confirm_with_password.ConfirmWithPasswordDialog",
            FakeConfirm,
        ):
            panel = UsersPanel(mock_ctx)
            qtbot.addWidget(panel)
            panel._table.selectRow(0)
            panel._on_delete_clicked()

        assert len(warning_calls) >= 1

    def test_last_admin_error_warning_text_contains_admin(
        self, qtbot, mock_ctx, mock_auth_manager, monkeypatch
    ):
        """Текст предупреждения содержит 'admin' или сообщение исключения."""
        mock_auth_manager.list_users.return_value = [_USER_ALICE]
        mock_auth_manager.delete_user.side_effect = LastAdminError(
            "Нельзя удалить последнего admin"
        )

        class FakeConfirm:
            def __init__(self, auth_manager, action_text, parent=None):
                self.confirmed = True

            def exec(self):
                return QDialog.DialogCode.Accepted

        warning_calls: list[tuple] = []

        def fake_warning(parent, title, text):
            warning_calls.append((title, text))

        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.warning",
            fake_warning,
        )

        with patch(
            "multiprocess_prototype.frontend.widgets.dialogs.confirm_with_password.ConfirmWithPasswordDialog",
            FakeConfirm,
        ):
            panel = UsersPanel(mock_ctx)
            qtbot.addWidget(panel)
            panel._table.selectRow(0)
            panel._on_delete_clicked()

        combined_text = " ".join(text for _, text in warning_calls)
        assert "admin" in combined_text.lower() or "последнего" in combined_text

    def test_last_admin_error_user_not_deleted(
        self, qtbot, mock_ctx, mock_auth_manager, monkeypatch
    ):
        """При LastAdminError пользователь остаётся в таблице (reload произошёл, список не пуст)."""
        mock_auth_manager.list_users.return_value = [_USER_ALICE]
        mock_auth_manager.delete_user.side_effect = LastAdminError(
            "Нельзя удалить последнего admin"
        )

        class FakeConfirm:
            def __init__(self, auth_manager, action_text, parent=None):
                self.confirmed = True

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.warning",
            lambda *a: None,
        )

        with patch(
            "multiprocess_prototype.frontend.widgets.dialogs.confirm_with_password.ConfirmWithPasswordDialog",
            FakeConfirm,
        ):
            panel = UsersPanel(mock_ctx)
            qtbot.addWidget(panel)
            panel._table.selectRow(0)
            panel._on_delete_clicked()

        # list_users по-прежнему возвращает [_USER_ALICE] — пользователь не был удалён
        assert panel._table.rowCount() == 1


# ---------------------------------------------------------------------------
# Permissions (PR3)
# ---------------------------------------------------------------------------


class _StubAuthState:
    """Минимальный AuthState для тестов permissions."""

    def __init__(self, permissions: set[str]) -> None:
        from PySide6.QtCore import QObject, Signal
        from multiprocess_framework.modules.frontend_module.managers.access_context import (
            AccessContext,
        )

        # Создаём QObject динамически, чтобы Signal работал
        class _Stub(QObject):
            access_context_changed = Signal(AccessContext)

            def __init__(self) -> None:
                super().__init__()
                self.access_context = AccessContext(permissions=frozenset(permissions))

            def set_context(self, ctx: AccessContext) -> None:
                self.access_context = ctx
                self.access_context_changed.emit(ctx)

        self._impl = _Stub()

    def __getattr__(self, name):
        return getattr(self._impl, name)


class TestUsersPanelPermissions:
    """CRUD-кнопки enabled только при наличии соответствующих users.* permissions."""

    def _ctx_with_state(self, mock_auth_manager, permissions: set[str]):
        ctx = MagicMock()
        ctx.manager = mock_auth_manager
        ctx.state = _StubAuthState(permissions)._impl
        return ctx

    def test_no_permissions_all_buttons_disabled(self, qtbot, mock_auth_manager):
        ctx = self._ctx_with_state(mock_auth_manager, permissions=set())
        panel = UsersPanel(ctx)
        qtbot.addWidget(panel)

        assert panel._btn_add.isEnabled() is False
        assert panel._btn_delete.isEnabled() is False
        assert panel._btn_change_role.isEnabled() is False
        assert panel._btn_reset_pwd.isEnabled() is False

    def test_admin_all_buttons_enabled(self, qtbot, mock_auth_manager):
        admin_perms = {
            "users.create",
            "users.delete",
            "users.edit",
            "users.reset_password",
        }
        ctx = self._ctx_with_state(mock_auth_manager, permissions=admin_perms)
        panel = UsersPanel(ctx)
        qtbot.addWidget(panel)

        assert panel._btn_add.isEnabled() is True
        assert panel._btn_delete.isEnabled() is True
        assert panel._btn_change_role.isEnabled() is True
        assert panel._btn_reset_pwd.isEnabled() is True

    def test_partial_permission_grants_subset(self, qtbot, mock_auth_manager):
        ctx = self._ctx_with_state(
            mock_auth_manager, permissions={"users.create"}
        )
        panel = UsersPanel(ctx)
        qtbot.addWidget(panel)

        assert panel._btn_add.isEnabled() is True
        assert panel._btn_delete.isEnabled() is False
        assert panel._btn_change_role.isEnabled() is False
        assert panel._btn_reset_pwd.isEnabled() is False

    def test_transient_lock_overrides_permission(self, qtbot, mock_auth_manager):
        """_set_buttons_enabled(False) отключает кнопки даже при наличии прав."""
        ctx = self._ctx_with_state(
            mock_auth_manager,
            permissions={"users.create", "users.delete", "users.edit", "users.reset_password"},
        )
        panel = UsersPanel(ctx)
        qtbot.addWidget(panel)
        assert panel._btn_add.isEnabled() is True

        panel._set_buttons_enabled(False)
        assert panel._btn_add.isEnabled() is False

        # После возвращения True — permission-driven восстановление
        panel._set_buttons_enabled(True)
        assert panel._btn_add.isEnabled() is True
