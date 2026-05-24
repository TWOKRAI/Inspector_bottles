# multiprocess_framework/modules/frontend_module/widgets/chrome/side_panels/collapsible.py
"""
CollapsibleSidePanel — узкая боковая панель с раскрытием по кнопке-полоске.

Layout (left):  [content (hidden when collapsed)] [toggle_strip]
Layout (right): [toggle_strip] [content]

Анимация — QPropertyAnimation на maximumWidth.

Каркас без логики наполнения: контент задаётся через `set_content(widget)`.
"""

from __future__ import annotations

from typing import Literal

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPropertyAnimation,
    QPushButton,
    QVBoxLayout,
    QWidget,
    Signal,
)

_COLLAPSED_WIDTH = 24
_DEFAULT_EXPANDED_WIDTH = 220
_ANIMATION_MS = 160


class CollapsibleSidePanel(QFrame):
    """Сворачиваемая панель: узкая полоска свёрнуто / strip + content развёрнуто."""

    expanded_changed = Signal(bool)

    def __init__(
        self,
        *,
        side: Literal["left", "right"] = "left",
        title: str = "",
        expanded_width: int = _DEFAULT_EXPANDED_WIDTH,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._side = side
        self._title = title
        self._expanded_width = expanded_width
        self._is_expanded = False

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMaximumWidth(_COLLAPSED_WIDTH)
        self.setMinimumWidth(_COLLAPSED_WIDTH)

        self._content_holder = QWidget()
        self._content_holder.setVisible(False)
        self._content_layout = QVBoxLayout(self._content_holder)
        self._content_layout.setContentsMargins(4, 4, 4, 4)
        self._content_layout.setSpacing(4)
        if title:
            self._content_layout.addWidget(QLabel(title))

        self._toggle_strip = QPushButton(self._strip_text())
        self._toggle_strip.setFixedWidth(_COLLAPSED_WIDTH)
        self._toggle_strip.setToolTip("Развернуть / свернуть панель")
        self._toggle_strip.clicked.connect(self.toggle)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if side == "left":
            layout.addWidget(self._content_holder, 1)
            layout.addWidget(self._toggle_strip)
        else:
            layout.addWidget(self._toggle_strip)
            layout.addWidget(self._content_holder, 1)

        self._anim = QPropertyAnimation(self, b"maximumWidth")
        self._anim.setDuration(_ANIMATION_MS)
        self._anim.finished.connect(self._on_anim_finished)

    def _strip_text(self) -> str:
        if self._is_expanded:
            return "<" if self._side == "left" else ">"
        return ">" if self._side == "left" else "<"

    def is_expanded(self) -> bool:
        return self._is_expanded

    def toggle(self) -> None:
        if self._is_expanded:
            self.collapse()
        else:
            self.expand()

    def expand(self) -> None:
        if self._is_expanded:
            return
        self._is_expanded = True
        self._content_holder.setVisible(True)
        self.setMinimumWidth(self._expanded_width)
        self._animate_to(self._expanded_width)
        self._toggle_strip.setText(self._strip_text())
        self.expanded_changed.emit(True)

    def collapse(self) -> None:
        if not self._is_expanded:
            return
        self._is_expanded = False
        self._animate_to(_COLLAPSED_WIDTH)
        self._toggle_strip.setText(self._strip_text())
        self.expanded_changed.emit(False)

    def _animate_to(self, target: int) -> None:
        self._anim.stop()
        self._anim.setStartValue(self.maximumWidth())
        self._anim.setEndValue(target)
        self._anim.start()

    def _on_anim_finished(self) -> None:
        if not self._is_expanded:
            self._content_holder.setVisible(False)
            self.setMinimumWidth(_COLLAPSED_WIDTH)

    def set_content(self, widget: QWidget) -> None:
        """Заменить контент панели (всё кроме заголовка и stretch)."""
        # Удалить все, кроме первого виджета (заголовка) если он есть
        skip = 1 if self._title else 0
        while self._content_layout.count() > skip:
            item = self._content_layout.takeAt(skip)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._content_layout.addWidget(widget)
        self._content_layout.addStretch()
