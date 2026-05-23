"""Master-Detail раскладка: список слева, детали справа.

Виджет не знает об AppContext — принимает чистые данные,
не импортирует ничего из multiprocess_prototype.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


__all__ = ["MasterDetailLayout"]


class MasterDetailLayout(QSplitter):
    """Master-detail раскладка: список слева, детали справа.

    Левая панель: поиск + фильтр по категории + список элементов.
    Правая панель: QStackedWidget с виджетами деталей.
    """

    # Сигнал: ключ выбранного элемента
    selection_changed = Signal(str)

    def __init__(
        self,
        search_placeholder: str = "Поиск...",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)

        # Маппинг key → индекс в QStackedWidget
        self._key_to_index: dict[str, int] = {}
        # Хранить категорию и display_text для каждого ключа — для фильтрации
        self._items: list[tuple[str, str, str]] = []  # [(key, display_text, category)]

        # --- Левая панель ---
        self._left_panel = QWidget()
        left_layout = QVBoxLayout(self._left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Поиск
        self._search = QLineEdit()
        self._search.setPlaceholderText(search_placeholder)
        left_layout.addWidget(self._search)

        # Фильтр по категории
        self._category_filter = QComboBox()
        self._category_filter.addItem("Все")
        left_layout.addWidget(self._category_filter)

        # Список элементов
        self._item_list = QListWidget()
        left_layout.addWidget(self._item_list)

        # --- Правая панель ---
        self._stack = QStackedWidget()

        # Добавить обе панели в сплиттер
        self.addWidget(self._left_panel)
        self.addWidget(self._stack)

        # Пропорции 1:2
        self.setStretchFactor(0, 1)
        self.setStretchFactor(1, 2)

        # Подключить сигналы
        self._search.textChanged.connect(self._apply_filter)
        self._category_filter.currentTextChanged.connect(self._apply_filter)
        self._item_list.currentItemChanged.connect(self._on_item_selected)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_items(self, items: list[tuple[str, str, str]]) -> None:
        """Заполнить список элементов.

        Args:
            items: список кортежей (key, display_text, category).
                   Каждый item хранит key в Qt.UserRole.
        """
        self._items = list(items)
        self._item_list.clear()
        for key, display_text, category in self._items:
            list_item = QListWidgetItem(display_text)
            list_item.setData(Qt.ItemDataRole.UserRole, key)
            list_item.setData(Qt.ItemDataRole.UserRole + 1, category)
            self._item_list.addItem(list_item)
        # Применить текущий фильтр к новым данным
        self._apply_filter()

    def set_categories(self, categories: list[str]) -> None:
        """Заполнить комбобокс категорий.

        Первый элемент «Все» — фильтр отключён.

        Args:
            categories: список названий категорий.
        """
        self._category_filter.blockSignals(True)
        self._category_filter.clear()
        self._category_filter.addItem("Все")
        for cat in categories:
            self._category_filter.addItem(cat)
        self._category_filter.blockSignals(False)
        self._apply_filter()

    def set_detail_widget(self, key: str, widget: QWidget) -> None:
        """Добавить виджет деталей для заданного ключа.

        Если этот key — текущий выбранный, стек сразу переключается на новый
        виджет. Без этого первый клик на новый элемент списка показывал
        предыдущую страницу: _on_item_selected переключал стек ДО того,
        как слушатель selection_changed успевал создать и зарегистрировать
        виджет.

        Args:
            key:    ключ элемента из set_items.
            widget: виджет, который показывать при выборе этого ключа.
        """
        index = self._stack.addWidget(widget)
        self._key_to_index[key] = index
        if key == self.selected_key():
            self._stack.setCurrentIndex(index)

    def selected_key(self) -> str | None:
        """Вернуть ключ текущего выбранного элемента или None."""
        item = self._item_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def filter_text(self) -> str:
        """Вернуть текущий текст поиска."""
        return self._search.text()

    # ------------------------------------------------------------------
    # Внутренняя логика
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        """Скрыть/показать элементы по поиску и категории."""
        search_text = self._search.text().lower()
        selected_category = self._category_filter.currentText()

        for i in range(self._item_list.count()):
            item = self._item_list.item(i)
            display_text: str = item.text()
            category: str = item.data(Qt.ItemDataRole.UserRole + 1) or ""

            # Проверка поиска
            matches_search = search_text in display_text.lower()

            # Проверка категории
            if selected_category == "Все":
                matches_category = True
            else:
                matches_category = category == selected_category

            item.setHidden(not (matches_search and matches_category))

    def _on_item_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        """Обработчик выбора элемента в списке."""
        if current is None:
            return

        key: str = current.data(Qt.ItemDataRole.UserRole)

        # Переключить стек, если для этого ключа есть виджет
        if key in self._key_to_index:
            self._stack.setCurrentIndex(self._key_to_index[key])

        self.selection_changed.emit(key)
