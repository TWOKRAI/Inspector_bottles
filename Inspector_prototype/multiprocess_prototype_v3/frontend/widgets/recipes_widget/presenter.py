# multiprocess_prototype/frontend/widgets/recipes_widget/presenter.py
"""Логика панели рецептов регистров (без разметки Qt)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from multiprocess_prototype_v2.managers.recipe_manager import DEFAULT_RECIPE_SLOT_ID

from .model import RegisterRecipeModel
from .recipe_rows import build_recipe_rows, coerce_string_to_value, format_value_for_cell

if TYPE_CHECKING:
    from .view import RegisterRecipePanelViewProtocol


class RegisterRecipePresenter:
    def __init__(self, *, view: RegisterRecipePanelViewProtocol, model: RegisterRecipeModel) -> None:
        """view — панель; model — rm + recipe_manager."""
        self._view = view
        self._model = model

    def on_load_clicked(self) -> None:
        """YAML слот → регистры через recipe_manager; колбэк on_recipe_applied."""
        idx = self._view.parse_slot()
        mgr = self._model.recipe_manager
        if mgr is None:
            return
        self._apply_load_slot(idx)

    def on_save_clicked(self) -> None:
        """Регистры → YAML слот; on_recipe_saved."""
        idx = self._view.parse_slot()
        mgr = self._model.recipe_manager
        if mgr is None:
            return
        self._apply_save_slot(idx)

    def on_default_clicked(self) -> None:
        """Загрузить в регистры слот 0 (заводской пресет)."""
        mgr = self._model.recipe_manager
        if mgr is None:
            return
        self._apply_default_slot()

    def refresh_from_registers(self) -> None:
        """Перечитать отображение таблицы из текущего rm."""
        self._view.refresh_table_rows()

    def on_leaf_value_changed(
        self, group_id: str, field_id: str, column_key: str, text: str
    ) -> None:
        """Правка колонки value у листа → rm.set_field_value."""
        if column_key != "value":
            return
        row = next((r for r in self.build_rows() if r.get("field_id") == field_id), None)
        if not row:
            return
        self.apply_value_cell(row, text)

    def _apply_load_slot(self, idx: int) -> None:
        """Номер слота, load_recipe_to_registers, refresh, on_recipe_applied."""
        mgr = self._model.recipe_manager
        rm = self._model.rm
        if mgr is None:
            return
        mgr.set_current_register_recipe_number(idx)
        mgr.load_recipe_to_registers(rm, str(idx))
        self._view.refresh_table_rows()
        if self._model.on_recipe_applied:
            self._model.on_recipe_applied(idx)

    def _apply_save_slot(self, idx: int) -> None:
        """save_registers_to_recipe и on_recipe_saved."""
        mgr = self._model.recipe_manager
        rm = self._model.rm
        if mgr is None:
            return
        mgr.set_current_register_recipe_number(idx)
        mgr.save_registers_to_recipe(rm, str(idx))
        if self._model.on_recipe_saved:
            self._model.on_recipe_saved(idx)

    def _apply_default_slot(self) -> None:
        """load_recipe_to_registers слот 0 (или legacy default_value)."""
        mgr = self._model.recipe_manager
        rm = self._model.rm
        if mgr is None:
            return
        if not mgr.load_recipe_to_registers(rm, DEFAULT_RECIPE_SLOT_ID):
            mgr.load_recipe_to_registers(rm, "default_value")
        self._view.refresh_table_rows()

    def initial_slot(self) -> int:
        """Стартовый слот из менеджера или UI."""
        return self._model.compute_initial_slot()

    def build_rows(self) -> list:
        """Строки из rm; форматирование value для ячеек."""
        rows = build_recipe_rows(self._model.rm, self._model.access_ctx)
        for r in rows:
            r["value"] = format_value_for_cell(r.get("value"))
        return rows

    def current_field_value(self, register_name: str, field_name: str) -> Any:
        """Текущее значение поля регистра (model_dump или getattr)."""
        reg = self._model.rm.get_register(register_name)
        if reg is None:
            return None
        if hasattr(reg, "model_dump"):
            return reg.model_dump().get(field_name)
        return getattr(reg, field_name, None)

    def apply_value_cell(self, row: dict, text: str) -> None:
        """Парсинг строки, set_field_value, откат текста ячейки при неуспехе."""
        register_name = row.get("register_name")
        field_name = row.get("field_name")
        field_id = row.get("field_id")
        if not register_name or not field_name or not field_id:
            return
        prev = self.current_field_value(register_name, field_name)
        new_val = coerce_string_to_value(text, prev)
        ok, _err = self._model.rm.set_field_value(register_name, field_name, new_val)
        if not ok:
            self._view.set_leaf_value_text(register_name, str(field_id), format_value_for_cell(prev))
            return
        self._view.set_leaf_value_text(
            register_name,
            str(field_id),
            format_value_for_cell(self.current_field_value(register_name, field_name)),
        )
