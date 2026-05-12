"""PlaceholderTab — заглушка для нереализованного таба."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderTab(QWidget):
    """Заглушка для нереализованного таба.

    Отображает название, описание и подсказку о будущей фазе.
    Создаётся немедленно — лёгкий виджет без сложной логики.
    """

    def __init__(
        self,
        tab_id: str,
        title: str,
        description: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tab_id = tab_id
        self.setObjectName(f"PlaceholderTab_{tab_id}")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Метка с названием, описанием и ссылкой на будущую фазу
        label = QLabel(f"{title}\n\n{description}\n\n(Phase 10+)")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setObjectName("PlaceholderLabel")
        layout.addWidget(label)

    @property
    def tab_id(self) -> str:
        """Идентификатор таба."""
        return self._tab_id
