# multiprocess_prototype/frontend/widgets/settings_recipe_widget/presenter.py
"""Логика панели app-рецептов (UI-схемы)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from multiprocess_prototype.managers.app_recipe_aggregate import (
    aggregate_to_snapshot,
    build_default_app_aggregate,
    merge_aggregate_with_defaults,
)

from ..recipes_widget.recipe_rows import coerce_string_to_value, format_value_for_cell
from .app_recipe_rows import build_app_recipe_rows, group_rows_by_schema
from .model import AppRecipeModel

if TYPE_CHECKING:
    from .view import AppRecipePanelViewProtocol


class AppRecipePresenter:
    def __init__(self, *, view: AppRecipePanelViewProtocol, model: AppRecipeModel) -> None:
        """view — панель (parse_slot, таблица); model — агрегат схем и recipe_manager."""
        self._view = view
        self._model = model

    @property
    def app_aggregate(self) -> Dict[str, Any]:
        """Текущий словарь schema_name → SchemaBase (редактируемая копия в модели)."""
        return self._model.app_aggregate

    def on_load_clicked(self) -> None:
        """Загрузить снимок app-рецепта для слота из recipe_manager в модель."""
        idx = self._view.parse_slot()
        mgr = self._model.recipe_manager
        if mgr is None:
            return
        self._apply_load_slot(idx)

    def on_save_clicked(self) -> None:
        """Сохранить текущий агрегат в YAML-слот через recipe_manager."""
        idx = self._view.parse_slot()
        mgr = self._model.recipe_manager
        if mgr is None:
            return
        self._apply_save_slot(idx)

    def on_default_clicked(self) -> None:
        """Подставить слот default_value или встроенные дефолты схем."""
        mgr = self._model.recipe_manager
        if mgr is None:
            return
        self._apply_default_slot()

    def on_leaf_value_changed(
        self, group_id: str, field_id: str, column_key: str, text: str
    ) -> None:
        """Применить текст ячейки value к полю схемы в агрегате."""
        if column_key != "value":
            return
        row = next((r for r in self.build_rows() if r.get("field_id") == field_id), None)
        if not row:
            return
        self._apply_value_cell(row, text)

    def _apply_load_slot(self, idx: int) -> None:
        """Внутренняя загрузка: set_current_app_recipe_number, load_app_recipe_snapshot, refresh таблицы."""
        mgr = self._model.recipe_manager
        if mgr is None:
            return
        if hasattr(mgr, "set_current_app_recipe_number"):
            mgr.set_current_app_recipe_number(idx)
        raw = mgr.load_app_recipe_snapshot(str(idx)) if hasattr(mgr, "load_app_recipe_snapshot") else None
        if raw:
            self._model.app_aggregate.clear()
            self._model.app_aggregate.update(merge_aggregate_with_defaults(raw))
        self._view.refresh_table_rows()

    def _apply_save_slot(self, idx: int) -> None:
        """Сериализовать агрегат и записать в слот idx."""
        mgr = self._model.recipe_manager
        if mgr is None:
            return
        if hasattr(mgr, "set_current_app_recipe_number"):
            mgr.set_current_app_recipe_number(idx)
        if hasattr(mgr, "save_app_recipe_snapshot"):
            mgr.save_app_recipe_snapshot(str(idx), aggregate_to_snapshot(self._model.app_aggregate))

    def _apply_default_slot(self) -> None:
        """Загрузить default_value или build_default_app_aggregate при отсутствии файла."""
        mgr = self._model.recipe_manager
        if mgr is None:
            return
        raw = mgr.load_app_recipe_snapshot("default_value") if hasattr(mgr, "load_app_recipe_snapshot") else None
        if raw:
            self._model.app_aggregate.clear()
            self._model.app_aggregate.update(merge_aggregate_with_defaults(raw))
        else:
            self._model.app_aggregate.clear()
            self._model.app_aggregate.update(
                build_default_app_aggregate(recipes_tab_dict=self._model.ui.model_dump())
            )
        self._view.refresh_table_rows()

    def initial_slot(self) -> int:
        """Начальный номер слота из менеджера или границ UI."""
        return self._model.compute_initial_slot()

    def build_rows(self) -> list:
        """Строки для дерева; значения прогоняются через format_value_for_cell."""
        rows = build_app_recipe_rows(self._model.app_aggregate, self._model.access_ctx)
        for r in rows:
            r["value"] = format_value_for_cell(r.get("value"))
        return rows

    def build_tree_groups(self) -> list:
        """Данные для StructuredTwoLevelTreeWidget."""
        return group_rows_by_schema(self.build_rows())

    def _current_app_field_value(self, schema_name: str, field_name: str) -> Any:
        """Значение поля из model_dump схемы в агрегате."""
        schema = self._model.app_aggregate.get(schema_name)
        if schema is None or not hasattr(schema, "model_dump"):
            return None
        return schema.model_dump().get(field_name)

    def _apply_value_cell(self, row: dict, text: str) -> None:
        """coerce_string_to_value + update_field / model_copy; синхронизация текста ячейки."""
        schema_name = row.get("schema_name")
        field_name = row.get("field_name")
        field_id = row.get("field_id")
        if not schema_name or not field_name or not field_id:
            return
        schema = self._model.app_aggregate.get(schema_name)
        if schema is None:
            return
        prev = self._current_app_field_value(schema_name, field_name)
        new_val = coerce_string_to_value(text, prev)
        ctx = self._model.access_ctx

        if ctx.bypass_readonly:
            try:
                new_schema = schema.model_copy(update={field_name: new_val})
            except Exception:
                self._view.set_leaf_value_text(schema_name, str(field_id), format_value_for_cell(prev))
                return
            self._model.app_aggregate[schema_name] = new_schema
        else:
            ok, _err = schema.update_field(field_name, new_val, ctx.level)
            if not ok:
                self._view.set_leaf_value_text(schema_name, str(field_id), format_value_for_cell(prev))
                return

        self._view.set_leaf_value_text(
            schema_name,
            str(field_id),
            format_value_for_cell(self._current_app_field_value(schema_name, field_name)),
        )
