"""RecipesTab — таб управления рецептами.

Layout: новый шаблон ``StandardTabLayout``.
  • Action-колонка (слева, фикс. 120px):
      top: ViewModeToggle (Cards/Table), Загрузить, Сохранить, Удалить
      bottom: Назад / Вперёд (Undo/Redo) — через ActionBus
  • Sub-nav (200px): динамический список рецептов (external-content режим)
  • Контент (в QScrollArea): QStackedWidget {Cards-форма, Table-всех}.

Legacy-атрибуты ``_btn_*``, ``_nav_list``, ``_name_edit``, ``_selected_slot``,
``_on_slot_selected``, ``_sync_slots`` сохранены для совместимости тестов.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode, ViewModeToggle
from multiprocess_prototype.frontend.widgets.primitives import StandardTabLayout

from .presenter import RecipesPresenter

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext

# Колонки таблицы
_TABLE_COLUMNS = ["Имя", "Описание", "Создан", "Изменён"]


class RecipesTab(QWidget):
    """Таб рецептов — на основе ``StandardTabLayout``."""

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
        # Заголовок отдельно над шаблоном (компактнее, чем класть в action-col).
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QLabel("Рецепты")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)

        # Основной шаблон вкладки.
        self._tab_layout = StandardTabLayout(show_sub_nav=True)

        # ── Левая колонка действий ────────────────────────────────────
        # Тумблер Cards / Table — добавляем как виджет в top-actions.
        self._toggle = ViewModeToggle(initial_mode=ViewMode.CARDS)
        self._toggle.mode_changed.connect(self._on_view_mode_changed)
        self._tab_layout.add_top_widget(self._toggle)

        self._btn_load = self._tab_layout.add_top_action("load", "Загрузить")
        self._btn_load.setEnabled(False)
        self._btn_save = self._tab_layout.add_top_action("save", "Сохранить")
        self._btn_delete = self._tab_layout.add_top_action("delete", "Удалить")
        self._btn_delete.setEnabled(False)

        self._tab_layout.action_triggered.connect(self._on_action)

        # Undo/Redo внизу.
        bus = self._ctx.action_bus() if hasattr(self._ctx, "action_bus") else None
        self._tab_layout.enable_undo_redo(bus)

        # ── Sub-nav (external-content режим) ─────────────────────────
        self._tab_layout.section_changed.connect(self._on_sub_nav_selected)

        # ── Контент: QStackedWidget {Cards, Table} ────────────────────
        self._center_stack = QStackedWidget()
        self._cards_widget = self._build_cards_page()
        self._center_stack.addWidget(self._cards_widget)
        self._table_widget = self._build_table_page()
        self._center_stack.addWidget(self._table_widget)
        self._tab_layout.set_content_widget(self._center_stack)

        layout.addWidget(self._tab_layout, stretch=1)

        # PR3: permission-aware proxy на setEnabled — наслаивается прозрачно
        # на selection-aware логику.
        from multiprocess_prototype.frontend.widgets.access import (
            install_permission_aware_enable,
        )
        _auth = self._ctx.auth
        auth_state = _auth.state if _auth is not None else None
        for btn in (self._btn_load, self._btn_save, self._btn_delete):
            install_permission_aware_enable(btn, "tabs.recipes.edit", auth_state)

        # Legacy alias: тесты обращаются к _nav_list напрямую.
        self._nav_list = self._tab_layout.sub_nav_list

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

        self._recipes_table.currentCellChanged.connect(self._on_table_row_changed)
        return self._recipes_table

    # ------------------------------------------------------------------
    # View mode
    # ------------------------------------------------------------------

    def _on_view_mode_changed(self, mode_str: str) -> None:
        mode = ViewMode(mode_str)
        if mode == ViewMode.CARDS:
            self._center_stack.setCurrentIndex(0)
        else:
            self._refresh_table()
            self._center_stack.setCurrentIndex(1)

    def _refresh_table(self) -> None:
        recipes = self._presenter.get_all_recipes()
        self._recipes_table.setRowCount(len(recipes))
        for row, info in enumerate(recipes):
            self._recipes_table.setItem(row, 0, QTableWidgetItem(info.name))
            self._recipes_table.setItem(row, 1, QTableWidgetItem(info.description))
            self._recipes_table.setItem(row, 2, QTableWidgetItem(info.created or "—"))
            self._recipes_table.setItem(row, 3, QTableWidgetItem(info.modified or "—"))

    def _on_table_row_changed(self, row: int, _col: int, _prev_row: int, _prev_col: int) -> None:
        recipes = self._presenter.get_all_recipes()
        if 0 <= row < len(recipes):
            self._selected_slot = recipes[row].slot
            self._btn_load.setEnabled(True)
            self._btn_delete.setEnabled(True)

    # ------------------------------------------------------------------
    # Sub-nav (список рецептов)
    # ------------------------------------------------------------------

    def _sync_nav(self) -> None:
        """Перестроить список рецептов из presenter."""
        self._tab_layout.clear_sub_nav()
        recipes = self._presenter.get_all_recipes()
        for info in recipes:
            self._tab_layout.add_sub_nav_section(
                key=str(info.slot), title=info.name, widget=None,
            )
        # Элемент «+ Новый рецепт» — ключ "-1".
        self._tab_layout.add_sub_nav_section(
            key="-1", title="+ Новый рецепт", widget=None,
        )

    def _on_sub_nav_selected(self, key: str) -> None:
        """Sub-nav сменилась → обновить форму."""
        try:
            slot = int(key)
        except (TypeError, ValueError):
            return

        if slot == -1:
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
    # Действия (callback от StandardTabLayout.action_triggered)
    # ------------------------------------------------------------------

    def _on_action(self, action_id: str) -> None:
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
        """Выбрать элемент sub-nav по slot ID."""
        self._tab_layout.set_current_section(str(slot))

    def _clear_form(self) -> None:
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
        """Legacy API: выбрать рецепт по slot напрямую."""
        self._selected_slot = slot
        self._show_recipe(slot)

    def _sync_slots(self) -> None:
        """Legacy API: алиас для _sync_nav."""
        self._sync_nav()
