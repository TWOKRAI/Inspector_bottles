"""AppHeaderWidget — верхняя панель главного окна (бренд + статус)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel


class AppHeaderWidget(QWidget):
    """Заголовок приложения: логотип слева, статус справа.

    objectName="AppHeader" — для стилизации через QSS.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AppHeader")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)

        # Бренд-лейбл
        self._brand_label = QLabel("INNOTECH")
        self._brand_label.setObjectName("BrandLabel")
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
