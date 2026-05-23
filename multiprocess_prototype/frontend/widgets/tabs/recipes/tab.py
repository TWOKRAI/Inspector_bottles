# -*- coding: utf-8 -*-
"""RecipesTab --- таб управления рецептами.

Шаблон визуально идентичен Settings: 3 колонки (actions / nav / content) +
мастер-скролл + QGroupBox с заголовком, через ``DiffScrollTabLayout``.
Вторая колонка (nav) — динамический список рецептов через ``BaseListNavTab``.

Pilot перехода Recipes на единый columnar-шаблон; см. ``plans/columnar-tab-unify/plan.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.widgets.tabs import BaseListNavTab
from multiprocess_prototype.frontend.forms.view_mode_toggle import ViewMode, ViewModeToggle
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import DiffScrollTabLayout

from .presenter import RecipesPresenter
from .recipe_form import RecipeFormWidget

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext

_TABLE_COLS = ["Имя", "Описание", "Создан", "Изменён"]


def _layout_factory() -> DiffScrollTabLayout:
    # Размеры колонок согласованы с SettingsTab — визуальная унификация.
    return DiffScrollTabLayout(title="Рецепты", action_width=160, nav_width=230)


class RecipesTab(BaseListNavTab):
    """Таб рецептов на шаблоне ``DiffScrollTabLayout`` (как Settings)."""

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        self._presenter = RecipesPresenter(ctx)
        self._forms: dict[str, RecipeFormWidget] = {}
        self._selected_slot: int = -1
        super().__init__(
            title="Рецепты",
            ctx=ctx,
            layout_factory=_layout_factory,
            parent=parent,
        )
        self._setup_actions()
        # Авто-refresh scroll area при смене активного рецепта в стеке.
        self._tab_layout.connect_stack(self._content_stack, "content")
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

        # Единый action-виджет в первой колонке: toggle + кнопки.
        # DiffScrollTabLayout принимает один виджет на колонку через set_action_widget.
        action_widget = QWidget()
        action_layout = QVBoxLayout(action_widget)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(6)

        self._toggle = ViewModeToggle(initial_mode=ViewMode.CARDS)
        self._toggle.mode_changed.connect(self._on_view_mode_changed)
        action_layout.addWidget(self._toggle)

        self._btn_load = self._make_action_button("load", "Загрузить")
        self._btn_load.setEnabled(False)
        action_layout.addWidget(self._btn_load)

        self._btn_save = self._make_action_button("save", "Сохранить")
        action_layout.addWidget(self._btn_save)

        self._btn_delete = self._make_action_button("delete", "Удалить")
        self._btn_delete.setEnabled(False)
        action_layout.addWidget(self._btn_delete)

        action_layout.addStretch(1)
        lay.set_action_widget(action_widget)

        # Undo/Redo живут в статичной зоне DiffScrollTabLayout (не скроллятся).
        bus = self._ctx.action_bus() if hasattr(self._ctx, "action_bus") else None
        lay.enable_undo_redo(bus)

        from multiprocess_prototype.frontend.widgets.access import install_permission_aware_enable

        auth_state = getattr(getattr(self._ctx, "auth", None), "state", None)
        for btn in (self._btn_load, self._btn_save, self._btn_delete):
            install_permission_aware_enable(btn, "tabs.recipes.edit", auth_state)

    def _make_action_button(self, action_id: str, label: str) -> QPushButton:
        btn = QPushButton(label)
        btn.clicked.connect(lambda _checked=False, aid=action_id: self._on_action(aid))
        return btn

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
