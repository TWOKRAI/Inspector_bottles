# -*- coding: utf-8 -*-
"""LoginButton — кнопка «Войти» / «<имя> ▾» в AppHeaderWidget.

Presenter-логика встроена в виджет (View+Presenter в одном классе),
так как кнопка простая и не требует отдельного presenter-класса.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMenu, QPushButton, QWidget

if TYPE_CHECKING:
    from Services.auth.interfaces import IAuthManager
    from multiprocess_prototype.frontend.state.auth_state import AuthState


class LoginButton(QPushButton):
    """Кнопка «Войти» / «<имя> ▾» в header.

    Состояния:
    - Не авторизован: текст «Войти», клик → LoginDialog.
    - Авторизован: текст «<username> ▾», клик → popup-меню (Выйти, Сменить пароль*).
      * «Сменить пароль» — disabled в PR2, задел для PR4.

    Presenter-логика встроена (View+Presenter в одном классе, т.к. виджет простой).
    Подписывается на auth_state.current_user_changed через Qt соединение.
    """

    def __init__(
        self,
        auth_state: "AuthState",
        auth_manager: "IAuthManager",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Войти", parent)
        self.setObjectName("LoginButton")

        self._auth_state = auth_state
        self._auth_manager = auth_manager

        # Подписка на смену пользователя
        auth_state.current_user_changed.connect(self._on_user_changed)

        # Начальное состояние — кнопка «Войти»
        self.clicked.connect(self._on_login_clicked)

    def _on_user_changed(self, user_dict: dict | None) -> None:
        """Обновить текст и поведение кнопки при смене пользователя."""
        # Отключаем старый обработчик clicked перед переключением режима
        try:
            self.clicked.disconnect()
        except RuntimeError:
            # Нет подключённых слотов — игнорируем
            pass

        if user_dict is not None:
            username = user_dict.get("username", "")
            self.setText(f"{username} ▾")
            self.clicked.connect(self._show_user_menu)
        else:
            self.setText("Войти")
            self.clicked.connect(self._on_login_clicked)

    def _on_login_clicked(self) -> None:
        """Открыть LoginDialog."""
        # Импорт здесь во избежание циклических зависимостей при загрузке модуля
        from multiprocess_prototype.frontend.widgets.dialogs.login_dialog import (
            LoginDialog,
        )

        dlg = LoginDialog(self._auth_manager, self._auth_state, parent=self)
        dlg.exec()

    def _show_user_menu(self) -> None:
        """Показать popup-меню авторизованного пользователя."""
        menu = QMenu(self)

        # Действие «Выйти»
        logout_action = menu.addAction("Выйти")
        logout_action.triggered.connect(self._on_logout_clicked)

        # Действие «Сменить пароль» — заготовка для PR4, disabled
        change_pwd_action = menu.addAction("Сменить пароль")
        change_pwd_action.setEnabled(False)

        # Показать меню под кнопкой
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _on_logout_clicked(self) -> None:
        """Вызвать auth_manager.logout(), затем auth_state.clear()."""
        self._auth_manager.logout()
        self._auth_state.clear()
