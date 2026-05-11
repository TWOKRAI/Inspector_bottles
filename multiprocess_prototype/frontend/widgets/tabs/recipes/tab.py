"""RecipesTab — таб управления рецептами.

3-колоночный layout с переключением Cards / Table:
  Левая панель (QListWidget): динамический список рецептов
  Центр: Cards (форма одного рецепта) или Table (все рецепты в таблице)
  Правая панель: тумблер Cards/Table + вертикальные кнопки действий

Layout:
    QVBoxLayout
      +-- QLabel "Рецепты" (header)
      +-- QHBoxLayout (stretch=1)
            +-- QListWidget (nav, 200px)
            +-- QStackedWidget (cards / table)
            +-- QVBoxLayout (toggle + кнопки)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode, ViewModeToggle

from .presenter import RecipesPresenter

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext

_NAV_WIDTH = 200
_ITEM_HEIGHT = 40
_ITEM_SPACING = 4
_BTN_WIDTH = 100

# Колонки таблицы
_TABLE_COLUMNS = ["Имя", "Описание", "Создан", "Изменён"]


class RecipesTab(QWidget):
    """Таб рецептов — динамический список + Cards/Table + вертикальные кнопки."""

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._presenter = RecipesPresenter(ctx)
        self._selected_slot: int = -1

        self._init_ui()
        self._sync_nav()

    @classmethod
    def create(cls, ctx: "AppContext") -> "RecipesTab":
        return cls(ctx)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Заголовок
        header = QLabel("Рецепты")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)

        # 3-колоночный layout
        columns = QHBoxLayout()
        columns.setSpacing(8)

        # --- Левая панель: список рецептов ---
        self._nav_list = QListWidget()
        self._nav_list.setObjectName("SideNavList")
        self._nav_list.setFixedWidth(_NAV_WIDTH)
        self._nav_list.setSpacing(_ITEM_SPACING)
        self._nav_list.currentRowChanged.connect(self._on_nav_row_changed)
        columns.addWidget(self._nav_list)

        # --- Центр: стек Cards / Table ---
        self._center_stack = QStackedWidget()

        # Page 0: Cards (форма одного рецепта)
        self._cards_widget = self._build_cards_page()
        self._center_stack.addWidget(self._cards_widget)

        # Page 1: Table (все рецепты)
        self._table_widget = self._build_table_page()
        self._center_stack.addWidget(self._table_widget)

        columns.addWidget(self._center_stack, stretch=1)

        # --- Правая панель: тумблер + вертикальные кнопки ---
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(8)

        # Тумблер Cards/Table
        self._toggle = ViewModeToggle(initial_mode=ViewMode.CARDS)
        self._toggle.mode_changed.connect(self._on_view_mode_changed)
        btn_layout.addWidget(self._toggle)

        self._btn_load = QPushButton("Загрузить")
        self._btn_load.setFixedWidth(_BTN_WIDTH)
        self._btn_load.setEnabled(False)
        self._btn_load.clicked.connect(lambda: self._on_action("load"))
        btn_layout.addWidget(self._btn_load)

        self._btn_save = QPushButton("Сохранить")
        self._btn_save.setFixedWidth(_BTN_WIDTH)
        self._btn_save.clicked.connect(lambda: self._on_action("save"))
        btn_layout.addWidget(self._btn_save)

        self._btn_delete = QPushButton("Удалить")
        self._btn_delete.setFixedWidth(_BTN_WIDTH)
        self._btn_delete.setEnabled(False)
        self._btn_delete.clicked.connect(lambda: self._on_action("delete"))
        btn_layout.addWidget(self._btn_delete)

        btn_layout.addStretch()
        columns.addLayout(btn_layout)

        # PR3: permission-aware proxy на setEnabled — наслаивается прозрачно
        # на selection-aware логику. Без tabs.recipes.edit все три кнопки
        # принудительно disabled, существующие setEnabled-вызовы игнорируются.
        from multiprocess_prototype.frontend.widgets.access import (
            install_permission_aware_enable,
        )
        auth_state = self._ctx.auth_state()
        for btn in (self._btn_load, self._btn_save, self._btn_delete):
            install_permission_aware_enable(btn, "tabs.recipes.edit", auth_state)

        layout.addLayout(columns, stretch=1)

    def _build_cards_page(self) -> QWidget:
        """Карточный вид — форма одного рецепта."""
        info_group = QGroupBox("Информация о рецепте")
        info_layout = QFormLayout(info_group)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Имя рецепта")
        info_layout.addRow("Имя:", self._name_edit)

        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setPlaceholderText("Описание")
        self._desc_edit.setMaximumHeight(80)
        info_layout.addRow("Описание:", self._desc_edit)

        self._created_label = QLabel("—")
        info_layout.addRow("Создан:", self._created_label)

        self._modified_label = QLabel("—")
        info_layout.addRow("Изменён:", self._modified_label)

        return info_group

    def _build_table_page(self) -> QWidget:
        """Табличный вид — все рецепты в таблице."""
        self._recipes_table = QTableWidget(0, len(_TABLE_COLUMNS))
        self._recipes_table.setHorizontalHeaderLabels(_TABLE_COLUMNS)
        self._recipes_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._recipes_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        h = self._recipes_table.horizontalHeader()
        if h:
            h.setStretchLastSection(True)
            h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        # Клик по строке таблицы → выбрать рецепт
        self._recipes_table.currentCellChanged.connect(self._on_table_row_changed)
        return self._recipes_table

    # ------------------------------------------------------------------
    # View mode
    # ------------------------------------------------------------------

    def _on_view_mode_changed(self, mode_str: str) -> None:
        """Переключить Cards / Table."""
        mode = ViewMode(mode_str)
        if mode == ViewMode.CARDS:
            self._center_stack.setCurrentIndex(0)
        else:
            self._refresh_table()
            self._center_stack.setCurrentIndex(1)

    def _refresh_table(self) -> None:
        """Перестроить табличное представление из данных presenter."""
        recipes = self._presenter.get_all_recipes()
        self._recipes_table.setRowCount(len(recipes))
        for row, info in enumerate(recipes):
            self._recipes_table.setItem(row, 0, QTableWidgetItem(info.name))
            self._recipes_table.setItem(row, 1, QTableWidgetItem(info.description))
            self._recipes_table.setItem(row, 2, QTableWidgetItem(info.created or "—"))
            self._recipes_table.setItem(row, 3, QTableWidgetItem(info.modified or "—"))

    def _on_table_row_changed(self, row: int, _col: int, _prev_row: int, _prev_col: int) -> None:
        """Обработать выбор строки в таблице."""
        recipes = self._presenter.get_all_recipes()
        if 0 <= row < len(recipes):
            self._selected_slot = recipes[row].slot
            self._btn_load.setEnabled(True)
            self._btn_delete.setEnabled(True)

    # ------------------------------------------------------------------
    # Навигация (левая панель)
    # ------------------------------------------------------------------

    def _sync_nav(self) -> None:
        """Перестроить список рецептов из presenter."""
        self._nav_list.blockSignals(True)
        self._nav_list.clear()

        recipes = self._presenter.get_all_recipes()
        for info in recipes:
            item = QListWidgetItem(info.name)
            item.setSizeHint(QSize(0, _ITEM_HEIGHT))
            item.setData(Qt.ItemDataRole.UserRole, info.slot)
            self._nav_list.addItem(item)

        # Элемент «+ Новый рецепт»
        new_item = QListWidgetItem("+ Новый рецепт")
        new_item.setSizeHint(QSize(0, _ITEM_HEIGHT))
        new_item.setData(Qt.ItemDataRole.UserRole, -1)
        self._nav_list.addItem(new_item)

        self._nav_list.blockSignals(False)

    def _on_nav_row_changed(self, row: int) -> None:
        """Обработать выбор элемента в списке."""
        if row < 0:
            return

        item = self._nav_list.item(row)
        if item is None:
            return

        slot = item.data(Qt.ItemDataRole.UserRole)

        if slot == -1:
            # «+ Новый рецепт»
            self._selected_slot = self._presenter.next_free_slot()
            self._name_edit.setText("")
            self._desc_edit.setPlainText("")
            self._created_label.setText("—")
            self._modified_label.setText("—")
            self._btn_load.setEnabled(False)
            self._btn_delete.setEnabled(False)
        else:
            self._selected_slot = slot
            self._show_recipe(slot)

    def _show_recipe(self, slot: int) -> None:
        """Показать данные рецепта в форме."""
        info = self._presenter.get_recipe_info(slot)
        if info:
            self._name_edit.setText(info.name)
            self._desc_edit.setPlainText(info.description)
            self._created_label.setText(info.created or "—")
            self._modified_label.setText(info.modified or "—")
            self._btn_load.setEnabled(True)
            self._btn_delete.setEnabled(True)
        else:
            self._name_edit.setText("")
            self._desc_edit.setPlainText("")
            self._created_label.setText("—")
            self._modified_label.setText("—")
            self._btn_load.setEnabled(False)
            self._btn_delete.setEnabled(False)

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------

    def _on_action(self, action_id: str) -> None:
        """Обработать нажатие кнопки."""
        if self._selected_slot < 0:
            return

        if action_id == "save":
            name = self._name_edit.text().strip() or f"Recipe {self._selected_slot}"
            desc = self._desc_edit.toPlainText().strip()
            self._presenter.save_to_slot(self._selected_slot, name, desc)
            self._sync_nav()
            self._select_slot_in_nav(self._selected_slot)

        elif action_id == "load":
            result = self._presenter.apply_recipe(self._selected_slot)
            if result:
                recipe_name = result.get("recipe_name", "")
                # Записать в ActionBus (если доступен)
                bus = self._ctx.get("action_bus")
                if bus is not None:
                    from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder
                    action = V2ActionBuilder.recipe_apply(
                        recipe_name, result["previous"], result["current"],
                    )
                    bus.record(action)

        elif action_id == "delete":
            self._presenter.delete_from_slot(self._selected_slot)
            self._sync_nav()
            self._clear_form()

    def _select_slot_in_nav(self, slot: int) -> None:
        """Выбрать элемент списка по slot ID."""
        for i in range(self._nav_list.count()):
            item = self._nav_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == slot:
                self._nav_list.setCurrentRow(i)
                return

    def _clear_form(self) -> None:
        """Очистить форму."""
        self._selected_slot = -1
        self._name_edit.setText("")
        self._desc_edit.setPlainText("")
        self._created_label.setText("—")
        self._modified_label.setText("—")
        self._btn_load.setEnabled(False)
        self._btn_delete.setEnabled(False)

    # ------------------------------------------------------------------
    # Обратная совместимость (используется в тестах)
    # ------------------------------------------------------------------

    def _on_slot_selected(self, slot: int) -> None:
        """Legacy: совместимость с тестами, выбрать рецепт по slot."""
        self._selected_slot = slot
        self._show_recipe(slot)

    def _sync_slots(self) -> None:
        """Legacy: совместимость с тестами."""
        self._sync_nav()
