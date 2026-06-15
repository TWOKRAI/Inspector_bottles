"""AppHeaderWidget — верхняя панель главного окна (бренд + статус)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QGraphicsDropShadowEffect

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.widgets.chrome.login_button import LoginButton


class AppHeaderWidget(QWidget):
    """Заголовок приложения: логотип слева, статус справа.

    objectName="AppHeader" — для стилизации через QSS.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AppHeader")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)

        # Бренд-лейбл (логотип ИННОТЕХ, шрифт Bank Gothic — задаётся в QSS)
        self._brand_label = QLabel("ИННОТЕХ")
        self._brand_label.setObjectName("BrandLabel")
        # Тень под логотипом (QSS не умеет text-shadow — делаем эффектом)
        shadow = QGraphicsDropShadowEffect(self._brand_label)
        shadow.setBlurRadius(8)
        shadow.setOffset(4, 4)
        shadow.setColor(QColor(0, 0, 0, 130))
        self._brand_label.setGraphicsEffect(shadow)
        layout.addWidget(self._brand_label)

        # Растяжка между брендом и статусом
        layout.addStretch(1)

        # Статус-лейбл (fps, backend status и т.д.)
        self._status_label = QLabel("")
        self._status_label.setObjectName("StatusLabel")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._status_label)

    # -- Публичное API --

    def update_status(self, text: str) -> None:
        """Обновить текст статуса в правой части header."""
        self._status_label.setText(text)

    def set_login_button(self, button: "LoginButton") -> None:
        """Вставить LoginButton справа от _status_label.

        Итоговый порядок элементов в layout:
            [BrandLabel] [stretch] [StatusLabel] [LoginButton]
        """
        self.layout().addWidget(button)
