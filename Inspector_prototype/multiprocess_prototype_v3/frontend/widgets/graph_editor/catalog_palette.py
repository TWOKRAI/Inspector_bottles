"""CatalogPalette — панель каталога операций с поддержкой drag-drop на canvas."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import QMimeData, Qt
from PyQt5.QtGui import QDrag
from PyQt5.QtWidgets import (
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Единый MIME-тип для перетаскивания операции на canvas
MIME_TYPE = "application/x-inspector-operation"


class _DragListWidget(QListWidget):
    """QListWidget с кастомным startDrag для передачи type_key через MIME."""

    def startDrag(self, supported_actions) -> None:  # noqa: N802
        """Инициировать drag с type_key выбранного элемента."""
        item = self.currentItem()
        if item is None:
            return

        # Берём type_key, сохранённый в UserRole
        type_key: str = item.data(Qt.UserRole)

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_TYPE, type_key.encode("utf-8"))
        drag.setMimeData(mime)

        drag.exec_(Qt.CopyAction)


class CatalogPalette(QWidget):
    """Панель каталога операций.

    Отображает список доступных операций из каталога,
    поддерживает текстовую фильтрацию и drag-drop на GraphView.

    Использование:
        palette = CatalogPalette()
        palette.load_catalog(catalog_dict)   # dict[type_key, ProcessingOperationDef]
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # Фиксированная ширина ~200px согласно spec
        self.setFixedWidth(200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Заголовок
        title = QLabel("Операции")
        title.setStyleSheet("font-weight: bold; font-size: 12px; color: #EEEEEE;")
        layout.addWidget(title)

        # Поле поиска
        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск операций...")
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)

        # Список операций с поддержкой drag
        self._list = _DragListWidget()
        self._list.setDragEnabled(True)
        self._list.setSelectionMode(QListWidget.SingleSelection)
        layout.addWidget(self._list)

        # Внутренние данные каталога: type_key → op_def
        self._catalog: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def load_catalog(self, catalog: dict[str, Any]) -> None:
        """Заполнить список операциями из каталога.

        Args:
            catalog: словарь type_key → ProcessingOperationDef.
        """
        self._catalog = catalog
        self._list.clear()

        if not catalog:
            # Placeholder при пустом каталоге
            placeholder = QListWidgetItem("Нет доступных операций")
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemIsEnabled)
            placeholder.setForeground(Qt.gray)
            self._list.addItem(placeholder)
            return

        for type_key, op_def in catalog.items():
            item = QListWidgetItem(op_def.name)
            item.setData(Qt.UserRole, type_key)
            item.setToolTip(op_def.description or type_key)
            self._list.addItem(item)

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _filter(self, text: str) -> None:
        """Фильтрация списка по введённому тексту (case-insensitive)."""
        lowered = text.lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            # Не скрываем disabled-placeholder
            if not (item.flags() & Qt.ItemIsEnabled):
                continue
            item.setHidden(lowered not in item.text().lower())
