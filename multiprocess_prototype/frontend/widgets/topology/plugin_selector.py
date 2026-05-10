"""PluginSelectorDialog — диалог выбора плагина из PluginRegistry."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


class PluginSelectorDialog(QDialog):
    """Диалог выбора плагина из каталога PluginRegistry.

    Показывает список плагинов, сгруппированных по category.
    Пользователь вводит имя плагина в экземпляре (plugin_name).
    При подтверждении возвращает dict с ключами plugin_class, plugin_name, category.
    """

    def __init__(self, plugins: list, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Выбор плагина")
        self.resize(480, 400)
        self._plugins = plugins
        self._selected_entry = None
        self._build_ui()
        self._populate(plugins)

    def _build_ui(self) -> None:
        """Построить UI диалога."""
        layout = QVBoxLayout(self)

        # Список плагинов
        layout.addWidget(QLabel("Доступные плагины:"))
        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_plugin_clicked)
        layout.addWidget(self._list)

        # Поле ввода имени экземпляра плагина
        layout.addWidget(QLabel("Имя плагина в процессе (plugin_name):"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("например: camera_0")
        layout.addWidget(self._name_edit)

        # Кнопки OK / Cancel
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def _populate(self, plugins: list) -> None:
        """Заполнить список плагинов с группировкой по category."""
        # Собрать категории
        categories: dict[str, list] = {}
        for entry in plugins:
            cat = getattr(entry, "category", "") or "other"
            categories.setdefault(cat, []).append(entry)

        for category in sorted(categories):
            # Заголовок категории (не кликабельный)
            header_item = QListWidgetItem(f"── {category.upper()} ──")
            header_item.setFlags(Qt.ItemFlag.NoItemFlags)
            header_item.setForeground(self._list.palette().mid())
            self._list.addItem(header_item)

            for entry in categories[category]:
                desc = getattr(entry, "description", "") or ""
                label = f"  {entry.name}"
                if desc:
                    label += f"  — {desc}"
                item = QListWidgetItem(label)
                # Сохранить ссылку на entry в UserRole
                item.setData(Qt.ItemDataRole.UserRole, entry)
                self._list.addItem(item)

        if not plugins:
            empty_item = QListWidgetItem("(нет зарегистрированных плагинов)")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(empty_item)

    def _on_plugin_clicked(self, item: QListWidgetItem) -> None:
        """Слот: пользователь кликнул по плагину."""
        entry = item.data(Qt.ItemDataRole.UserRole)
        if entry is None:
            return
        self._selected_entry = entry
        # Автозаполнить имя если поле пустое
        if not self._name_edit.text().strip():
            self._name_edit.setText(entry.name)

    def result_dict(self) -> dict | None:
        """Получить выбранный плагин как dict или None если ничего не выбрано."""
        if self._selected_entry is None:
            return None
        plugin_name = self._name_edit.text().strip()
        if not plugin_name:
            return None
        return {
            "plugin_class": getattr(self._selected_entry, "class_path", ""),
            "plugin_name": plugin_name,
            "category": getattr(self._selected_entry, "category", ""),
        }

    # ------------------------------------------------------------------ #
    #  Статический метод-фасад                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_plugin(parent: QWidget | None, plugins: list) -> dict | None:
        """Открыть диалог и вернуть dict плагина или None при отмене.

        Args:
            parent: Родительский виджет (может быть None).
            plugins: Список PluginEntry из PluginRegistry.list().

        Returns:
            dict с ключами plugin_class, plugin_name, category — или None.
        """
        dialog = PluginSelectorDialog(plugins, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.result_dict()
        return None
