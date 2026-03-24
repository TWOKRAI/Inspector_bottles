# multiprocess_prototype/frontend/widgets/tabs_setting/recipes_tab/recipe_slot_table_panel.py
"""
Базовая панель «слот + таблица» для рецептов и два режима: регистры / app-схемы.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Union

from frontend_module.widgets.tables.structured_table import StructuredTableWidget
from frontend_module.core.qt_imports import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)
from frontend_module.core.schema_config import coerce_schema_config
from frontend_module.interfaces import IRegistersManagerGui

from multiprocess_prototype.managers.access_context import AccessContext

from .recipe_rows import coerce_string_to_value, format_value_for_cell
from .schemas import RecipesTabConfig


class RecipeSlotTablePanel(QWidget):
    """Слот, кнопки Загрузить/Сохранить/По умолчанию, таблица; хуки для конкретного типа рецепта."""

    load_requested = pyqtSignal(int)
    save_requested = pyqtSignal(int)
    default_requested = pyqtSignal()

    _VALUE_COL = 1

    def __init__(
        self,
        *,
        ui: Union[RecipesTabConfig, dict],
        group_title: str,
        table_title: str,
        recipe_manager: Optional[Any] = None,
        recipe_access: Optional[Union[AccessContext, dict]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._ui = coerce_schema_config(ui, RecipesTabConfig)
        self._recipe_manager = recipe_manager
        self._access_ctx = (
            recipe_access
            if isinstance(recipe_access, AccessContext)
            else AccessContext.from_dict(recipe_access if isinstance(recipe_access, dict) else None)
        )
        self._block_table = False
        self._slot: Optional[QLineEdit] = None
        self._table: Optional[StructuredTableWidget] = None
        self._group_title = group_title
        self._table_title = table_title
        self._build_ui()
        self._connect_buttons()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        u = self._ui

        box = QGroupBox(self._group_title)
        ctrl = QHBoxLayout(box)
        ctrl.addWidget(QLabel(u.label_slot))
        self._slot = QLineEdit()
        self._slot.setFixedWidth(56)
        self._slot.setText(str(self._initial_slot()))
        ctrl.addWidget(self._slot)
        self._btn_load = QPushButton(u.btn_load)
        self._btn_save = QPushButton(u.btn_save)
        self._btn_default = QPushButton(u.btn_default)
        ctrl.addWidget(self._btn_load)
        ctrl.addWidget(self._btn_save)
        ctrl.addWidget(self._btn_default)
        ctrl.addStretch()
        layout.addWidget(box)

        layout.addWidget(QLabel(self._table_title))
        columns = [
            {"key": "param", "label": u.col_param, "type": "text", "editable": False},
            {"key": "value", "label": u.col_value, "type": "text", "editable": True},
            {"key": "info", "label": u.col_info, "type": "text", "editable": False},
        ]
        self._table = StructuredTableWidget(columns=columns)
        self._table.set_row_key("field_id")
        self._refresh_rows()
        self._table.itemChanged.connect(self._on_table_item_changed)
        layout.addWidget(self._table, 1)

    def _connect_buttons(self) -> None:
        if self._recipe_manager is not None:
            self._wire_recipe_manager()
        else:
            self._btn_load.clicked.connect(self._emit_load_stub)
            self._btn_save.clicked.connect(self._emit_save_stub)
            self._btn_default.clicked.connect(self._emit_default_stub)

    def _emit_load_stub(self) -> None:
        self.load_requested.emit(self._parse_slot())

    def _emit_save_stub(self) -> None:
        self.save_requested.emit(self._parse_slot())

    def _emit_default_stub(self) -> None:
        self.default_requested.emit()

    def _parse_slot(self) -> int:
        u = self._ui
        if self._slot is None:
            return u.recipe_index_min
        try:
            v = int(self._slot.text().strip())
        except (TypeError, ValueError):
            v = u.recipe_index_min
        return max(u.recipe_index_min, min(u.recipe_index_max, v))

    def _wire_recipe_manager(self) -> None:
        self._btn_load.clicked.connect(self._on_load_clicked)
        self._btn_save.clicked.connect(self._on_save_clicked)
        self._btn_default.clicked.connect(self._on_default_clicked)

    def _on_load_clicked(self) -> None:
        idx = self._parse_slot()
        self._apply_load_slot(idx)
        self.load_requested.emit(idx)

    def _on_save_clicked(self) -> None:
        idx = self._parse_slot()
        self._apply_save_slot(idx)
        self.save_requested.emit(idx)

    def _on_default_clicked(self) -> None:
        self._apply_default_slot()
        self.default_requested.emit()

    def _initial_slot(self) -> int:
        raise NotImplementedError

    def _refresh_rows(self) -> None:
        raise NotImplementedError

    def _apply_load_slot(self, idx: int) -> None:
        raise NotImplementedError

    def _apply_save_slot(self, idx: int) -> None:
        raise NotImplementedError

    def _apply_default_slot(self) -> None:
        raise NotImplementedError

    def _apply_value_cell(self, row: dict, text: str, item) -> None:
        """Применить значение к модели; при ошибке восстановить текст ячейки."""
        raise NotImplementedError

    def _on_table_item_changed(self, item) -> None:
        if self._block_table or self._table is None:
            return
        if item.column() != self._VALUE_COL:
            return
        row_idx = item.row()
        row = self._table.get_row_data(row_idx)
        if not row:
            return
        self._block_table = True
        self._table.blockSignals(True)
        self._apply_value_cell(row, item.text(), item)
        self._table.blockSignals(False)
        self._block_table = False


class RegisterRecipePanel(RecipeSlotTablePanel):
    """Рецепты регистров: строки из RegistersManager, запись через set_field_value."""

    def __init__(
        self,
        *,
        rm: IRegistersManagerGui,
        ui: Union[RecipesTabConfig, dict],
        recipe_manager: Optional[Any] = None,
        recipe_access: Optional[Union[AccessContext, dict]] = None,
        on_recipe_applied: Optional[Callable[[int], None]] = None,
        on_recipe_saved: Optional[Callable[[int], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        u = coerce_schema_config(ui, RecipesTabConfig)
        self._rm = rm
        self._on_recipe_applied = on_recipe_applied
        self._on_recipe_saved = on_recipe_saved
        super().__init__(
            ui=u,
            group_title=u.group_register_box,
            table_title=u.table_group_title,
            recipe_manager=recipe_manager,
            recipe_access=recipe_access,
            parent=parent,
        )

    def _initial_slot(self) -> int:
        rm = self._recipe_manager
        if rm is not None and hasattr(rm, "get_current_register_recipe_number"):
            try:
                return int(rm.get_current_register_recipe_number())
            except (TypeError, ValueError):
                pass
        if rm is not None and hasattr(rm, "get_current_recipe_number"):
            try:
                return int(rm.get_current_recipe_number())
            except (TypeError, ValueError):
                pass
        u = self._ui
        return max(u.recipe_index_min, min(u.recipe_index_max, u.recipe_index_min))

    def _refresh_rows(self) -> None:
        if self._table is None:
            return
        from .recipe_rows import build_recipe_rows

        self._block_table = True
        self._table.blockSignals(True)
        rows = build_recipe_rows(self._rm, self._access_ctx)
        for r in rows:
            r["value"] = format_value_for_cell(r.get("value"))
        self._table.set_data(rows)
        self._table.blockSignals(False)
        self._block_table = False

    def refresh_from_registers(self) -> None:
        self._refresh_rows()

    def _apply_load_slot(self, idx: int) -> None:
        mgr = self._recipe_manager
        if mgr is None:
            return
        if hasattr(mgr, "set_current_register_recipe_number"):
            mgr.set_current_register_recipe_number(idx)
        elif hasattr(mgr, "set_current_recipe_number"):
            mgr.set_current_recipe_number(idx)
        if hasattr(mgr, "load_recipe_to_registers"):
            mgr.load_recipe_to_registers(self._rm, str(idx))
        self._refresh_rows()
        if self._on_recipe_applied:
            self._on_recipe_applied(idx)

    def _apply_save_slot(self, idx: int) -> None:
        mgr = self._recipe_manager
        if mgr is None:
            return
        if hasattr(mgr, "set_current_register_recipe_number"):
            mgr.set_current_register_recipe_number(idx)
        elif hasattr(mgr, "set_current_recipe_number"):
            mgr.set_current_recipe_number(idx)
        if hasattr(mgr, "save_registers_to_recipe"):
            mgr.save_registers_to_recipe(self._rm, str(idx))
        if self._on_recipe_saved:
            self._on_recipe_saved(idx)

    def _apply_default_slot(self) -> None:
        mgr = self._recipe_manager
        if mgr is None:
            return
        if hasattr(mgr, "load_recipe_to_registers"):
            mgr.load_recipe_to_registers(self._rm, "default_value")
        self._refresh_rows()

    def _current_field_value(self, register_name: str, field_name: str) -> Any:
        reg = self._rm.get_register(register_name)
        if reg is None:
            return None
        if hasattr(reg, "model_dump"):
            return reg.model_dump().get(field_name)
        return getattr(reg, field_name, None)

    def _apply_value_cell(self, row: dict, text: str, item) -> None:
        register_name = row.get("register_name")
        field_name = row.get("field_name")
        if not register_name or not field_name:
            return
        prev = self._current_field_value(register_name, field_name)
        new_val = coerce_string_to_value(text, prev)
        ok, _err = self._rm.set_field_value(register_name, field_name, new_val)
        if not ok:
            item.setText(format_value_for_cell(prev))
            return
        item.setText(format_value_for_cell(self._current_field_value(register_name, field_name)))


class AppRecipePanel(RecipeSlotTablePanel):
    """Рецепты приложения (UI-схемы): агрегат SchemaBase, без слайдеров."""

    def __init__(
        self,
        *,
        ui: Union[RecipesTabConfig, dict],
        recipes_tab_dict: Dict[str, Any],
        processing_tab_ui_dict: Optional[Dict[str, Any]] = None,
        recipe_manager: Optional[Any] = None,
        recipe_access: Optional[Union[AccessContext, dict]] = None,
        parent: Optional[QWidget] = None,
    ):
        from multiprocess_prototype.managers.app_recipe_aggregate import build_default_app_aggregate

        u = coerce_schema_config(ui, RecipesTabConfig)
        self._app_aggregate: Dict[str, Any] = build_default_app_aggregate(
            recipes_tab_dict=recipes_tab_dict,
            processing_tab_ui_dict=processing_tab_ui_dict or {},
        )
        super().__init__(
            ui=u,
            group_title=u.group_app_box,
            table_title=u.table_app_group_title,
            recipe_manager=recipe_manager,
            recipe_access=recipe_access,
            parent=parent,
        )

    def _initial_slot(self) -> int:
        rm = self._recipe_manager
        if rm is not None and hasattr(rm, "get_current_app_recipe_number"):
            try:
                return int(rm.get_current_app_recipe_number())
            except (TypeError, ValueError):
                pass
        u = self._ui
        return max(u.recipe_index_min, min(u.recipe_index_max, u.recipe_index_min))

    def _refresh_rows(self) -> None:
        if self._table is None:
            return
        from .app_recipe_rows import build_app_recipe_rows

        self._block_table = True
        self._table.blockSignals(True)
        rows = build_app_recipe_rows(self._app_aggregate, self._access_ctx)
        for r in rows:
            r["value"] = format_value_for_cell(r.get("value"))
        self._table.set_data(rows)
        self._table.blockSignals(False)
        self._block_table = False

    def _apply_load_slot(self, idx: int) -> None:
        from multiprocess_prototype.managers.app_recipe_aggregate import merge_aggregate_with_defaults

        mgr = self._recipe_manager
        if mgr is None:
            return
        if hasattr(mgr, "set_current_app_recipe_number"):
            mgr.set_current_app_recipe_number(idx)
        raw = mgr.load_app_recipe_snapshot(str(idx)) if hasattr(mgr, "load_app_recipe_snapshot") else None
        if raw:
            self._app_aggregate = merge_aggregate_with_defaults(raw)
        self._refresh_rows()

    def _apply_save_slot(self, idx: int) -> None:
        from multiprocess_prototype.managers.app_recipe_aggregate import aggregate_to_snapshot

        mgr = self._recipe_manager
        if mgr is None:
            return
        if hasattr(mgr, "set_current_app_recipe_number"):
            mgr.set_current_app_recipe_number(idx)
        if hasattr(mgr, "save_app_recipe_snapshot"):
            mgr.save_app_recipe_snapshot(str(idx), aggregate_to_snapshot(self._app_aggregate))

    def _apply_default_slot(self) -> None:
        from multiprocess_prototype.managers.app_recipe_aggregate import (
            build_default_app_aggregate,
            merge_aggregate_with_defaults,
        )

        mgr = self._recipe_manager
        if mgr is None:
            return
        raw = mgr.load_app_recipe_snapshot("default_value") if hasattr(mgr, "load_app_recipe_snapshot") else None
        if raw:
            self._app_aggregate = merge_aggregate_with_defaults(raw)
        else:
            self._app_aggregate = build_default_app_aggregate(recipes_tab_dict=self._ui.model_dump())
        self._refresh_rows()

    def _current_app_field_value(self, schema_name: str, field_name: str) -> Any:
        schema = self._app_aggregate.get(schema_name)
        if schema is None or not hasattr(schema, "model_dump"):
            return None
        return schema.model_dump().get(field_name)

    def _apply_value_cell(self, row: dict, text: str, item) -> None:
        schema_name = row.get("schema_name")
        field_name = row.get("field_name")
        if not schema_name or not field_name:
            return
        schema = self._app_aggregate.get(schema_name)
        if schema is None:
            return
        prev = self._current_app_field_value(schema_name, field_name)
        new_val = coerce_string_to_value(text, prev)

        if self._access_ctx.bypass_readonly:
            try:
                new_schema = schema.model_copy(update={field_name: new_val})
            except Exception:
                item.setText(format_value_for_cell(prev))
                return
            self._app_aggregate[schema_name] = new_schema
        else:
            ok, _err = schema.update_field(field_name, new_val, self._access_ctx.level)
            if not ok:
                item.setText(format_value_for_cell(prev))
                return

        item.setText(format_value_for_cell(self._current_app_field_value(schema_name, field_name)))
