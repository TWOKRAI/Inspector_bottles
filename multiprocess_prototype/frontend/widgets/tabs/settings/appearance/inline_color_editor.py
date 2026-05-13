# -*- coding: utf-8 -*-
"""InlineColorEditor -- виджет inline-редактора цвета для таблицы переменных.

Управляет вставкой/удалением строки с QColorDialog в QTableWidget.
Не содержит бизнес-логики -- только UI-механику открытия/закрытия color picker.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QTableWidget, QWidget

# Регулярка для проверки hex-цвета (#rrggbb)
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class InlineColorEditor(QWidget):
    """Inline color editor -- вставляет QColorDialog в строку таблицы.

    API:
        open(table, row, color)  -- вставить строку с QColorDialog под row
        close()                  -- убрать вставленную строку
        is_open                  -- активен ли editor

    Signals:
        color_changed(str)       -- hex-цвет при live-изменении (#rrggbb)
    """

    color_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Строка с inline color editor (-1 = не показан)
        self._editor_row: int = -1
        # Целевая строка (строка переменной, к которой привязан editor)
        self._target_row: int = -1
        # Имя переменной, для которой открыт editor
        self._var_name: str = ""
        # Ссылка на таблицу (устанавливается при open)
        self._table: QTableWidget | None = None
        # QColorDialog (создаётся при open, уничтожается при close/removeRow)
        self._color_dialog: QColorDialog | None = None

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        """Активен ли inline color editor."""
        return self._editor_row >= 0

    @property
    def target_row(self) -> int:
        """Строка переменной, к которой привязан editor (-1 если закрыт)."""
        return self._target_row

    @property
    def var_name(self) -> str:
        """Имя переменной, для которой открыт editor."""
        return self._var_name

    @property
    def editor_row(self) -> int:
        """Строка в таблице, в которой вставлен QColorDialog (-1 если закрыт)."""
        return self._editor_row

    def open(
        self,
        table: QTableWidget,
        row: int,
        var_name: str,
        color: str,
    ) -> None:
        """Вставить строку с QColorDialog под row.

        Args:
            table: таблица переменных
            row: строка переменной (color editor вставится в row+1)
            var_name: имя переменной
            color: текущий hex-цвет (#rrggbb)
        """
        # Закрыть предыдущий, если был
        self.close()

        if not _HEX_RE.match(color):
            return

        self._table = table
        self._target_row = row
        self._var_name = var_name

        # Вставить новую строку под целевой
        editor_row = row + 1
        table.blockSignals(True)
        table.insertRow(editor_row)
        self._editor_row = editor_row

        # Создать новый QColorDialog (setCellWidget передаёт ownership)
        dialog = QColorDialog(self)
        dialog.setOption(QColorDialog.ColorDialogOption.NoButtons, True)
        dialog.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
        dialog.currentColorChanged.connect(self._on_color_live_changed)
        dialog.setCurrentColor(QColor(color))
        self._color_dialog = dialog

        # Установить QColorDialog как cellWidget, заняв все колонки через span
        col_count = table.columnCount()
        table.setSpan(editor_row, 0, 1, col_count)
        table.setCellWidget(editor_row, 0, dialog)
        # Высота строки под диалог
        table.setRowHeight(editor_row, dialog.sizeHint().height())
        table.blockSignals(False)

    def close(self) -> None:
        """Закрыть inline color editor (убрать вставленную строку)."""
        if self._editor_row < 0 or self._table is None:
            return

        row = self._editor_row
        table = self._table

        self._editor_row = -1
        self._target_row = -1
        self._var_name = ""

        table.blockSignals(True)
        # Qt удалит QColorDialog при removeRow -- обнуляем ссылку
        self._color_dialog = None
        table.setSpan(row, 0, 1, 1)  # Сбросить span
        table.removeRow(row)
        table.blockSignals(False)

        self._table = None

    # ------------------------------------------------------------------
    # Внутренние обработчики
    # ------------------------------------------------------------------

    def _on_color_live_changed(self, color: QColor) -> None:
        """Live-обновление: эмитить hex при изменении цвета в QColorDialog."""
        if self._editor_row < 0:
            return
        self.color_changed.emit(color.name())
