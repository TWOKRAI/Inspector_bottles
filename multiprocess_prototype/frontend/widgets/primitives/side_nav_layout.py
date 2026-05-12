"""SideNavLayout — универсальная боковая навигация.

Левая панель (QListWidget) со списком секций + опциональная панель действий
+ правая панель (QStackedWidget) с контентом выбранной секции.

Используется в любом табе, где нужна навигация по подразделам.
Без поиска/фильтра — чистая навигация (в отличие от MasterDetailLayout).

Layout:
    QHBoxLayout
      +-- QVBoxLayout (левая колонка, фикс. ширина nav_width)
      |     +-- QListWidget (навигация)
      |     +-- QStackedWidget (action panel, по одному виджету на секцию)
      +-- QStackedWidget (контент, stretch=1)
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Signal, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class SideNavLayout(QWidget):
    """Боковая навигация: список секций слева + контент справа.

    Опционально: панель действий (кнопки) под навигацией, меняется
    при переключении секции.
    """

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

        self._nav_width = nav_width
        self._key_to_index: dict[str, int] = {}
        self._keys: list[str] = []

        # --- Левая колонка: навигация + action panel ---
        self._nav_list = QListWidget()
        self._nav_list.setObjectName("SideNavList")
        self._nav_list.setFixedWidth(nav_width)
        self._nav_list.setSpacing(self._ITEM_SPACING)
        # Не растягивать вертикально — иначе забирает всё место у action panel
        self._nav_list.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred,
        )
        self._nav_list.currentRowChanged.connect(self._on_row_changed)

        # Action panel — стек виджетов с кнопками (по одному на секцию)
        self._action_stack = QStackedWidget()
        self._action_stack.setFixedWidth(nav_width)
        self._action_stack.hide()  # скрыт пока нет action-виджетов
        self._has_actions = False

        left_column = QVBoxLayout()
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.setSpacing(4)
        left_column.addWidget(self._nav_list)
        left_column.addWidget(self._action_stack)
        left_column.addStretch(1)  # оставшееся место — вниз

        # --- Правая панель: стек контента ---
        self._stack = QStackedWidget()

        # --- Layout ---
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(left_column)
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
        item = QListWidgetItem(title)
        item.setSizeHint(QSize(0, self._ITEM_HEIGHT))
        item.setData(Qt.ItemDataRole.UserRole, key)
        self._nav_list.addItem(item)

        idx = self._stack.addWidget(widget)
        self._key_to_index[key] = idx
        self._keys.append(key)

        # Пустой placeholder в action_stack (заменяется через set_actions)
        placeholder = QWidget()
        self._action_stack.addWidget(placeholder)

    def set_actions(self, key: str, buttons: list[QPushButton]) -> None:
        """Установить кнопки действий для секции.

        Args:
            key: ключ секции (должен быть предварительно добавлен через add_section).
            buttons: список QPushButton для отображения в action panel.
        """
        idx = self._key_to_index.get(key)
        if idx is None:
            return

        # Заменяем placeholder на виджет с кнопками
        old_widget = self._action_stack.widget(idx)

        action_widget = QWidget()
        action_layout = QVBoxLayout(action_widget)
        action_layout.setContentsMargins(0, 8, 0, 0)
        action_layout.setSpacing(4)
        for btn in buttons:
            action_layout.addWidget(btn)
        action_layout.addStretch()

        self._action_stack.insertWidget(idx, action_widget)
        self._action_stack.removeWidget(old_widget)
        old_widget.deleteLater()

        if not self._has_actions:
            self._has_actions = True
            self._action_stack.show()

        # Синхронизировать с текущей секцией
        current_idx = self._key_to_index.get(self.current_key(), -1)
        if current_idx >= 0:
            self._action_stack.setCurrentIndex(current_idx)

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

    def section_count(self) -> int:
        """Вернуть количество секций."""
        return len(self._keys)

    # ------------------------------------------------------------------
    # Внутренние
    # ------------------------------------------------------------------

    def _on_row_changed(self, row: int) -> None:
        """Обработчик смены строки в списке."""
        if row < 0 or row >= len(self._keys):
            return
        key = self._keys[row]
        idx = self._key_to_index[key]
        self._stack.setCurrentIndex(idx)
        if self._has_actions:
            self._action_stack.setCurrentIndex(idx)
        self.section_changed.emit(key)
