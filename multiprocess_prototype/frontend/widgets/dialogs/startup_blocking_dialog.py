# -*- coding: utf-8 -*-
"""StartupBlockingDialog — блокирующий диалог критической ошибки при запуске.

Показывается до создания MainWindow, если bootstrap не был выполнен
или хранилище пользователей повреждено. Содержит только кнопку «Выход»;
кнопка закрытия окна убрана, чтобы пользователь не мог обойти проверку.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class StartupBlockingDialog(QDialog):
    """Блокирующий диалог при отсутствии bootstrap или повреждении хранилища.

    Не даёт открыть основное окно. Содержит сообщение об ошибке и
    единственную кнопку «Выход». Кнопка закрытия в заголовке окна убрана.
    """

    def __init__(self, message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ошибка инициализации")
        # Убираем кнопку закрытия окна — пользователь обязан нажать «Выход»
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # Текст ошибки
        _message_label = QLabel(message)
        _message_label.setWordWrap(True)
        _message_label.setObjectName("StartupErrorLabel")
        layout.addWidget(_message_label)

        # Только кнопка «Выход»
        _buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        _buttons.button(QDialogButtonBox.StandardButton.Close).setText("Выход")
        _buttons.rejected.connect(self.reject)
        layout.addWidget(_buttons)
