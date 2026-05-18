"""RecipesTab --- таб управления рецептами (BaseListNavTab pilot).

Action: ViewModeToggle, Загрузить/Сохранить/Удалить, Undo/Redo.
Table-вид создаётся лениво. См. Phase 6c.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.widgets.tabs import (
    BaseListNavTab,
    StandardTabLayout,
)
from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode, ViewModeToggle

from .presenter import RecipesPresenter
from .recipe_form import RecipeFormWidget

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext

_TABLE_COLS = ["Имя", "Описание", "Создан", "Изменён"]


class RecipesTab(BaseListNavTab):
    """Таб рецептов --- pilot consumer ``BaseListNavTab``."""

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        self._presenter = RecipesPresenter(ctx)
        self._forms: dict[str, RecipeFormWidget] = {}
        self._selected_slot: int = -1
        super().__init__(
            title="Рецепты",
            ctx=ctx,
            layout_factory=lambda: StandardTabLayout(show_sub_nav=False),
            parent=parent,
        )
        self._setup_actions()
        self._sync_nav()

    @classmethod
    def create(cls, ctx: "AppContext") -> "RecipesTab":
        return cls(ctx)

    def _create_item_widget(self, key: str) -> QWidget:
        form = RecipeFormWidget()
        self._forms[key] = form
        return form

    def _on_nav_changed(self, key: str) -> None:
        super()._on_nav_changed(key)
        try:
            slot = int(key)
        except (TypeError, ValueError):
            return
        self._selected_slot = slot
        form = self._forms.get(key)
        if form is None:
            return
        if slot < 0:
            form.clear()
            self._btn_load.setEnabled(False)
            self._btn_delete.setEnabled(False)
            return
        info = self._presenter.get_recipe_info(slot)
        if info:
            form.populate(info.name, info.description, info.created or "—", info.modified or "—")
            self._btn_load.setEnabled(True)
            self._btn_delete.setEnabled(True)
        else:
            form.clear()
            self._btn_load.setEnabled(False)
            self._btn_delete.setEnabled(False)

    def _setup_actions(self) -> None:
        lay = self._tab_layout
        self._toggle = ViewModeToggle(initial_mode=ViewMode.CARDS)
        self._toggle.mode_changed.connect(self._on_view_mode_changed)
        lay.add_top_widget(self._toggle)  # type: ignore[attr-defined]
        self._btn_load = lay.add_top_action("load", "Загрузить")  # type: ignore[attr-defined]
        self._btn_load.setEnabled(False)
        self._btn_save = lay.add_top_action("save", "Сохранить")  # type: ignore[attr-defined]
        self._btn_delete = lay.add_top_action("delete", "Удалить")  # type: ignore[attr-defined]
        self._btn_delete.setEnabled(False)
        lay.action_triggered.connect(self._on_action)  # type: ignore[attr-defined]
        bus = self._ctx.action_bus() if hasattr(self._ctx, "action_bus") else None
        lay.enable_undo_redo(bus)
        from multiprocess_prototype.frontend.widgets.access import install_permission_aware_enable

        auth_state = getattr(getattr(self._ctx, "auth", None), "state", None)
        for btn in (self._btn_load, self._btn_save, self._btn_delete):
            install_permission_aware_enable(btn, "tabs.recipes.edit", auth_state)

    def _on_action(self, action_id: str) -> None:
        if action_id == "save":
            # Читаем из текущей формы ДО переназначения slot
            cur_key = str(self._selected_slot)
            form = self._forms.get(cur_key)
            slot = self._selected_slot if self._selected_slot >= 0 else self._presenter.next_free_slot()
            self._selected_slot = slot
            name = (form.name_edit.text().strip() if form else "") or f"Recipe {slot}"
            desc = form.desc_edit.toPlainText().strip() if form else ""
            self._presenter.save_to_slot(slot, name, desc)
            self._sync_nav()
            self.select_item(str(slot))
        elif action_id == "load" and self._selected_slot >= 0:
            result = self._presenter.apply_recipe(self._selected_slot)
            if result and self._ctx.get("action_bus") is not None:
                from multiprocess_prototype.frontend.actions.builder import V2ActionBuilder

                self._ctx.get("action_bus").record(
                    V2ActionBuilder.recipe_apply(
                        result.get("recipe_name", ""),
                        result["previous"],
                        result["current"],
                    )
                )
        elif action_id == "delete" and self._selected_slot >= 0:
            self._presenter.delete_from_slot(self._selected_slot)
            self._sync_nav()

    def _on_view_mode_changed(self, mode_str: str) -> None:
        if ViewMode(mode_str) == ViewMode.CARDS:
            key = str(self._selected_slot)
            if key in self._key_to_index:
                self._content_stack.setCurrentIndex(self._key_to_index[key])
        else:
            self._show_table()

    def _show_table(self) -> None:
        if not hasattr(self, "_recipes_table"):
            tbl = QTableWidget(0, len(_TABLE_COLS))
            tbl.setHorizontalHeaderLabels(_TABLE_COLS)
            tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            h = tbl.horizontalHeader()
            if h:
                h.setStretchLastSection(True)
                h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            tbl.currentCellChanged.connect(self._on_table_row_changed)
            self._recipes_table = tbl
            self.register_content_widget("__table__", tbl)
        recipes = self._presenter.get_all_recipes()
        self._recipes_table.setRowCount(len(recipes))
        for row, info in enumerate(recipes):
            self._recipes_table.setItem(row, 0, QTableWidgetItem(info.name))
            self._recipes_table.setItem(row, 1, QTableWidgetItem(info.description))
            self._recipes_table.setItem(row, 2, QTableWidgetItem(info.created or "—"))
            self._recipes_table.setItem(row, 3, QTableWidgetItem(info.modified or "—"))
        self._content_stack.setCurrentIndex(self._key_to_index["__table__"])

    def _on_table_row_changed(self, row: int, _c: int, _pr: int, _pc: int) -> None:
        recipes = self._presenter.get_all_recipes()
        if 0 <= row < len(recipes):
            self._selected_slot = recipes[row].slot
            self._btn_load.setEnabled(True)
            self._btn_delete.setEnabled(True)

    def _sync_nav(self) -> None:
        assert self._nav_widget is not None
        self._nav_widget.blockSignals(True)
        self._nav_widget.clear()
        tbl = getattr(self, "_recipes_table", None)
        while self._content_stack.count() > 0:
            w = self._content_stack.widget(0)
            self._content_stack.removeWidget(w)
            if w is not None and w is not tbl:
                w.deleteLater()
        self._key_to_item.clear()
        self._key_to_index.clear()
        self._forms.clear()
        self._nav_widget.blockSignals(False)
        if tbl is not None:
            self.register_content_widget("__table__", tbl)
        for info in self._presenter.get_all_recipes():
            self.add_item(str(info.slot), info.name)
        self.add_item("-1", "+ Новый рецепт")
