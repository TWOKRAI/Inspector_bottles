"""SideNavLayout — универсальная боковая навигация.

Левая панель (QListWidget) со списком секций + правая панель (QStackedWidget)
с контентом выбранной секции. Переключение по клику в списке.

Используется в любом табе, где нужна навигация по подразделам.
Без поиска/фильтра — чистая навигация (в отличие от MasterDetailLayout).

Layout:
    QHBoxLayout
      +-- QListWidget (фикс. ширина nav_width)
      +-- QStackedWidget (stretch=1)
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Signal, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QWidget,
)


class SideNavLayout(QWidget):
    """Боковая навигация: список секций слева + контент справа."""

    # Ключ выбранной секции
    section_changed = Signal(str)

    _DEFAULT_NAV_WIDTH = 200
    _ITEM_HEIGHT = 40
    _ITEM_SPACING = 4

    def __init__(
        self,
        nav_width: int = _DEFAULT_NAV_WIDTH,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._key_to_index: dict[str, int] = {}
        self._keys: list[str] = []

        # --- Левая панель: список секций ---
        self._nav_list = QListWidget()
        self._nav_list.setObjectName("SideNavList")
        self._nav_list.setFixedWidth(nav_width)
        self._nav_list.setSpacing(self._ITEM_SPACING)
        self._nav_list.currentRowChanged.connect(self._on_row_changed)

        # --- Правая панель: стек контента ---
        self._stack = QStackedWidget()

        # --- Layout ---
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._nav_list)
        layout.addWidget(self._stack, 1)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def add_section(self, key: str, title: str, widget: QWidget) -> None:
        """Добавить секцию в навигацию.

        Args:
            key: уникальный строковый идентификатор секции.
            title: отображаемое название в списке слева.
            widget: виджет контента для этой секции.
        """
        # Элемент списка
        item = QListWidgetItem(title)
        item.setSizeHint(QSize(0, self._ITEM_HEIGHT))
        item.setData(Qt.ItemDataRole.UserRole, key)
        self._nav_list.addItem(item)

        # Виджет в стек
        idx = self._stack.addWidget(widget)
        self._key_to_index[key] = idx
        self._keys.append(key)

    def set_current(self, key: str) -> None:
        """Переключить на секцию по ключу."""
        idx = self._key_to_index.get(key)
        if idx is not None:
            self._nav_list.setCurrentRow(idx)

    def current_key(self) -> str:
        """Ключ текущей выбранной секции (пустая строка если нет секций)."""
        row = self._nav_list.currentRow()
        if row < 0 or row >= len(self._keys):
            return ""
        return self._keys[row]

    # ------------------------------------------------------------------
    # Внутренние
    # ------------------------------------------------------------------

    def _on_row_changed(self, row: int) -> None:
        """Обработчик смены строки в списке."""
        if row < 0 or row >= len(self._keys):
            return
        key = self._keys[row]
        self._stack.setCurrentIndex(self._key_to_index[key])
        self.section_changed.emit(key)
