# -*- coding: utf-8 -*-
"""
CheckboxView — QLabel + QCheckBox с настраиваемой позицией.
"""
from __future__ import annotations

from typing import Callable, Literal, Optional

from frontend_module.components.controls.v2.base.infrastructure.signal_utils import (
    block_signals,
)
from frontend_module.core.qt_imports import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
    Qt,
)

CHECKBOX_FIXED_WIDTH_PX = 44
CHECKBOX_FIXED_HEIGHT_PX = 44
LAYOUT_CONTENT_MARGINS_PX = 4
LAYOUT_SPACING_PX = 4

Position = Literal["left", "right", "top", "bottom"]


class CheckboxView(QWidget):
    """QLabel + QCheckBox с настраиваемой позицией."""

    def __init__(
        self,
        position: Position = "left",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._position = position
        self._label = QLabel()
        self._checkbox = QCheckBox()
        self._checkbox.setFixedSize(CHECKBOX_FIXED_WIDTH_PX, CHECKBOX_FIXED_HEIGHT_PX)
        self._build_layout()

    def _build_layout(self) -> None:
        if self._position in ("top", "bottom"):
            layout: QHBoxLayout | QVBoxLayout = QVBoxLayout()
            items: tuple = (
                (self._label, self._checkbox)
                if self._position == "top"
                else (self._checkbox, self._label)
            )
        else:
            layout = QHBoxLayout()
            items = (
                (self._label, self._checkbox)
                if self._position == "left"
                else (self._checkbox, self._label)
            )

        layout.setContentsMargins(
            LAYOUT_CONTENT_MARGINS_PX,
            LAYOUT_CONTENT_MARGINS_PX,
            LAYOUT_CONTENT_MARGINS_PX,
            LAYOUT_CONTENT_MARGINS_PX,
        )
        layout.setSpacing(LAYOUT_SPACING_PX)
        for w in items:
            layout.addWidget(w)
        self.setLayout(layout)

    def setup(self, label: str, tooltip: str, enabled: bool) -> None:
        self._label.setText(label)
        self._label.setToolTip(tooltip)
        self.set_enabled(enabled)

    def set_value(self, value: bool) -> None:
        self._checkbox.setChecked(value)

    def set_value_silent(self, value: bool) -> None:
        with block_signals(self._checkbox):
            self._checkbox.setChecked(value)

    def get_value(self) -> bool:
        return self._checkbox.isChecked()

    def set_enabled(self, enabled: bool) -> None:
        self._checkbox.setEnabled(enabled)

    def on_changed(self, callback: Callable[[bool], None]) -> None:
        self._checkbox.stateChanged.connect(
            lambda state: callback(state == Qt.Checked)
        )

    def on_finished(self, callback: Callable[[bool], None]) -> None:
        """Для чекбокса — no-op (immediate write через on_changed)."""
        pass

    def show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Ошибка валидации", message)
