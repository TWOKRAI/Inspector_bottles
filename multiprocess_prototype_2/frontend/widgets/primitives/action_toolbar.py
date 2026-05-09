"""ActionToolbar — горизонтальный ряд кнопок действий.

Универсальный виджет: не привязан к конкретным действиям.
Каждая кнопка эмитит action_triggered(action_id).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QWidget


class ActionToolbar(QWidget):
    """Тулбар действий — горизонтальный ряд кнопок с сигналом."""

    action_triggered = Signal(str)  # action_id

    def __init__(
        self,
        actions: list[tuple[str, str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._buttons: dict[str, QPushButton] = {}

        for action_id, label in actions or []:
            self.add_action(action_id, label)

    # ------------------------------------------------------------------ #
    #  Публичный API                                                       #
    # ------------------------------------------------------------------ #

    def add_action(self, action_id: str, label: str) -> QPushButton:
        """Добавить кнопку действия. Возвращает QPushButton."""
        btn = QPushButton(label)
        btn.clicked.connect(
            lambda checked=False, aid=action_id: self.action_triggered.emit(aid)
        )
        self._buttons[action_id] = btn
        self._layout.addWidget(btn)
        return btn

    def set_enabled(self, action_id: str, enabled: bool) -> None:
        """Включить/отключить кнопку по action_id."""
        btn = self._buttons.get(action_id)
        if btn is not None:
            btn.setEnabled(enabled)

    def add_stretch(self) -> None:
        """Добавить растяжку между кнопками."""
        self._layout.addStretch()

    def add_separator(self) -> None:
        """Добавить вертикальный разделитель."""
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setFixedWidth(2)
        self._layout.addWidget(sep)
