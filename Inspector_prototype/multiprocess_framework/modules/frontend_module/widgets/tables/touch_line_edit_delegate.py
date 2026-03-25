# -*- coding: utf-8 -*-
"""
Делегат для QTableWidget / QTreeWidget: при открытии редактора QLineEdit — touch-клавиатура.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from frontend_module.core.qt_imports import QLineEdit, QStyledItemDelegate, QWidget


class TouchLineEditItemDelegate(QStyledItemDelegate):
    """Подключает ``install_touch_keyboard_on_line_edit`` к редактору ячейки."""

    def __init__(
        self,
        host: QWidget,
        keyboard_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(host)
        self._host = host
        self._keyboard_factory = keyboard_factory

    def createEditor(self, parent: QWidget, option, index):  # type: ignore[no-untyped-def]
        editor = super().createEditor(parent, option, index)
        if not isinstance(editor, QLineEdit):
            return editor
        cfg = None
        if hasattr(self._host, "_keyboard_config_for_column"):
            cfg = self._host._keyboard_config_for_column(index.column())  # type: ignore[attr-defined]
        if cfg is None and self._keyboard_factory is None:
            return editor
        from frontend_module.widgets.keyboard.touch_keyboard import (
            install_touch_keyboard_on_line_edit,
        )

        install_touch_keyboard_on_line_edit(
            self._host,
            editor,
            cfg,
            lambda: editor.clearFocus(),
            keyboard_factory=self._keyboard_factory,
        )
        return editor
