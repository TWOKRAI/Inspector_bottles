# multiprocess_prototype_v3/frontend/widgets/base/navigation_panel_base.py
"""Базовый класс для левых навигационных панелей (QListWidget + общие стили)."""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QListWidget,
    QVBoxLayout,
    QWidget,
    Signal,
)
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QListWidgetItem


class NavigationPanelBase(QWidget):
    """Базовая левая навигационная панель — QListWidget с общими стилями."""

    selection_changed = Signal(int)  # row index

    _DEFAULT_WIDTH = 200
    _STYLE = (
        "QListWidget { font-size: 15px; }"
        "QListWidget::item { padding: 10px 12px; }"
    )

    def __init__(self, *, width: int = _DEFAULT_WIDTH, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._list = QListWidget()
        self._list.setFixedWidth(width)
        self._list.setStyleSheet(self._STYLE)
        self._list.setSpacing(4)
        # Подключаем базовый обработчик — подкласс может переопределить _on_row_changed
        self._list.currentRowChanged.connect(self._on_row_changed)

        layout.addWidget(self._list, 1)

    # ------------------------------------------------------------------
    # Защищённые вспомогательные методы — для использования подклассами
    # ------------------------------------------------------------------

    def _add_item(self, text: str, size_hint_height: int = 40) -> QListWidgetItem:
        """Создать элемент с sizeHint и добавить в список."""
        item = QListWidgetItem(text)
        item.setSizeHint(QSize(0, size_hint_height))
        self._list.addItem(item)
        return item

    def _clear_items(self) -> None:
        """Очистить список без генерации сигналов."""
        self._list.blockSignals(True)
        self._list.clear()
        self._list.blockSignals(False)

    def _set_current_row(self, row: int, *, emit: bool = False) -> None:
        """Установить активную строку, опционально подавляя сигналы."""
        if not emit:
            self._list.blockSignals(True)
        self._list.setCurrentRow(row)
        if not emit:
            self._list.blockSignals(False)

    def _on_row_changed(self, row: int) -> None:
        """Виртуальный обработчик смены строки — подкласс может переопределить."""
        self.selection_changed.emit(row)

    # ------------------------------------------------------------------
    # Свойства
    # ------------------------------------------------------------------

    @property
    def _item_count(self) -> int:
        """Количество элементов в списке."""
        return self._list.count()
