"""PluginCatalogWidget — каталог плагинов из PluginRegistry с фильтром по категории.

Виджет отображает зарегистрированные плагины, поддерживает фильтр по категории
и эмитит сигналы при выборе или активации плагина для добавления в plugin chain.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Роль для хранения объекта PluginEntry в QListWidgetItem
_ENTRY_ROLE = Qt.ItemDataRole.UserRole

# Категории для фильтра (отображаемое имя → значение для фильтра)
_CATEGORIES: list[tuple[str, str]] = [
    ("Все", ""),
    ("source", "source"),
    ("processing", "processing"),
    ("output", "output"),
]


def _format_ports(ports: list) -> str:
    """Форматировать список портов в строку для tooltip.

    Пример: "frame (image/bgr) | mask (image/gray)"

    Args:
        ports: Список объектов Port с атрибутами name и dtype.

    Returns:
        Строка с портами через ' | ' или '—' если портов нет.
    """
    if not ports:
        return "—"
    return " | ".join(f"{p.name} ({p.dtype})" for p in ports)


def _build_tooltip(entry) -> str:
    """Собрать tooltip для PluginEntry.

    Args:
        entry: Объект PluginEntry из PluginRegistry.

    Returns:
        Многострочный tooltip с описанием и портами.
    """
    in_str = _format_ports(entry.inputs)
    out_str = _format_ports(entry.outputs)
    lines = [
        entry.description or "(без описания)",
        f"In: {in_str}",
        f"Out: {out_str}",
    ]
    return "\n".join(lines)


class PluginCatalogWidget(QWidget):
    """Каталог плагинов из PluginRegistry с фильтром по категории.

    Сигналы:
        plugin_selected(str): Эмитируется при двойном клике — передаёт имя плагина.
        plugin_activated(dict): Эмитируется при нажатии "Добавить" — минимальный dict
            для add_plugin с ключами plugin_class, plugin_name, category.
    """

    plugin_selected = Signal(str)   # имя плагина при двойном клике
    plugin_activated = Signal(dict) # dict для add_plugin при нажатии "Добавить"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._connect_signals()
        # Инициальная загрузка — все плагины
        self.refresh()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Инициализировать компоновку и дочерние виджеты."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Заголовок
        title = QLabel("Каталог плагинов")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        # Фильтр по категории
        self._combo_category = QComboBox()
        for display_name, _ in _CATEGORIES:
            self._combo_category.addItem(display_name)
        self._combo_category.setToolTip("Фильтровать плагины по категории")
        layout.addWidget(self._combo_category)

        # Список плагинов
        self._list_widget = QListWidget()
        self._list_widget.setAlternatingRowColors(True)
        self._list_widget.setToolTipDuration(5000)
        layout.addWidget(self._list_widget, stretch=1)

        # Кнопка добавления
        self._btn_add = QPushButton("Добавить")
        self._btn_add.setEnabled(False)
        self._btn_add.setToolTip("Добавить выбранный плагин в цепочку обработки")
        layout.addWidget(self._btn_add)

    def _connect_signals(self) -> None:
        """Подключить внутренние сигналы виджета."""
        # Изменение фильтра категории → обновить список
        self._combo_category.currentIndexChanged.connect(self._on_category_changed)

        # Двойной клик по плагину → эмитировать plugin_selected
        self._list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)

        # Изменение выбора → управлять кнопкой "Добавить"
        self._list_widget.currentItemChanged.connect(self._on_selection_changed)

        # Кнопка "Добавить" → эмитировать plugin_activated
        self._btn_add.clicked.connect(self._on_add_clicked)

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------

    def refresh(self, category_filter: str = "") -> None:
        """Обновить список плагинов из PluginRegistry.

        Args:
            category_filter: Категория для фильтрации. Пустая строка → все плагины.
        """
        self._list_widget.clear()
        self._btn_add.setEnabled(False)

        # Получаем записи из реестра; оборачиваем в try-except — реестр может
        # быть недоступен (импорт не сработал или модуль не установлен)
        try:
            from multiprocess_framework.modules.process_module.plugins.registry import (
                PluginRegistry,
            )

            if category_filter:
                entries = PluginRegistry.filter(category_filter)
            else:
                entries = PluginRegistry.list()
        except Exception:
            entries = []

        if not entries:
            self._add_empty_placeholder()
            return

        for entry in entries:
            item = QListWidgetItem(entry.name)
            item.setData(_ENTRY_ROLE, entry)
            item.setToolTip(_build_tooltip(entry))
            self._list_widget.addItem(item)

    def filter_compatible(self, port) -> None:
        """Отфильтровать плагины, совместимые с указанным портом.

        Args:
            port: Объект Port — фильтрует по входам плагина через
                  PluginRegistry.compatible_with(port).
        """
        self._list_widget.clear()
        self._btn_add.setEnabled(False)

        try:
            from multiprocess_framework.modules.process_module.plugins.registry import (
                PluginRegistry,
            )

            entries = PluginRegistry.compatible_with(port)
        except Exception:
            entries = []

        if not entries:
            self._add_empty_placeholder()
            return

        for entry in entries:
            item = QListWidgetItem(entry.name)
            item.setData(_ENTRY_ROLE, entry)
            item.setToolTip(_build_tooltip(entry))
            self._list_widget.addItem(item)

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _add_empty_placeholder(self) -> None:
        """Добавить disabled-заглушку когда плагинов нет."""
        placeholder = QListWidgetItem("Нет доступных плагинов")
        placeholder.setFlags(Qt.ItemFlag.NoItemFlags)  # нельзя выбрать
        self._list_widget.addItem(placeholder)

    def _current_entry(self):
        """Получить PluginEntry текущего выбранного item или None."""
        item = self._list_widget.currentItem()
        if item is None:
            return None
        return item.data(_ENTRY_ROLE)

    # ------------------------------------------------------------------
    # Слоты
    # ------------------------------------------------------------------

    def _on_category_changed(self, index: int) -> None:
        """Слот изменения фильтра категории в ComboBox."""
        _, category_value = _CATEGORIES[index]
        self.refresh(category_value)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        """Слот двойного клика — эмитировать plugin_selected с именем плагина."""
        entry = item.data(_ENTRY_ROLE)
        if entry is None:
            return  # placeholder — не реагируем
        self.plugin_selected.emit(entry.name)

    def _on_selection_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,  # noqa: ARG002
    ) -> None:
        """Слот изменения выбора — управляет доступностью кнопки 'Добавить'."""
        has_entry = current is not None and current.data(_ENTRY_ROLE) is not None
        self._btn_add.setEnabled(has_entry)

    def _on_add_clicked(self) -> None:
        """Слот кнопки 'Добавить' — эмитировать plugin_activated."""
        entry = self._current_entry()
        if entry is None:
            return
        payload: dict = {
            "plugin_class": entry.class_path,
            "plugin_name": entry.name,
            "category": entry.category,
        }
        self.plugin_activated.emit(payload)
