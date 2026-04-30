# multiprocess_prototype/frontend/widgets/recipes_widget/presenter.py
"""Логика панели рецептов регистров (без разметки Qt)."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from multiprocess_prototype.frontend.managers.recipe_manager import DEFAULT_RECIPE_SLOT_ID

from .model import RegisterRecipeModel
from .recipe_rows import (
    build_recipe_rows,
    build_recipe_rows_from_snapshot,
    coerce_string_to_value,
    format_value_for_cell,
)

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.actions.bus import ActionBus

    from .view import RegisterRecipePanelViewProtocol


class RegisterRecipePresenter:
    def __init__(
        self,
        *,
        view: RegisterRecipePanelViewProtocol,
        model: RegisterRecipeModel,
        action_bus: ActionBus | None = None,
    ) -> None:
        """view — панель; model — rm + recipe_manager."""
        self._view = view
        self._model = model
        self._action_bus = action_bus
        # Preview-режим: snapshot YAML слота, отображается в таблице вместо rm.
        # Редактирование в таблице пишет в snapshot. Apply копирует в rm,
        # Save — в YAML через recipe_manager.save_slot.
        self._preview_snapshot: dict[str, Any] | None = None
        self._preview_slot_id: int | None = None

    # ------------------------------------------------------------------
    # Preview API
    # ------------------------------------------------------------------

    def is_preview_mode(self) -> bool:
        return self._preview_snapshot is not None

    def preview_slot_id(self) -> int | None:
        return self._preview_slot_id

    def enter_preview(self, slot_id: int) -> bool:
        """Загрузить snapshot слота из YAML и показать в таблице (без записи в rm)."""
        mgr = self._model.recipe_manager
        if mgr is None or not hasattr(mgr, "get_slot"):
            return False
        try:
            snapshot = mgr.get_slot(str(slot_id))
        except Exception:  # noqa: BLE001
            snapshot = None
        if snapshot is None:
            # Слот пуст — отображаем пустую таблицу с пометкой
            self._preview_snapshot = {}
            self._preview_slot_id = slot_id
            self._view.refresh_table_rows()
            return False
        self._preview_snapshot = copy.deepcopy(snapshot)
        self._preview_slot_id = slot_id
        self._view.refresh_table_rows()
        return True

    def exit_preview(self) -> None:
        """Сбросить preview-режим — таблица снова показывает rm."""
        self._preview_snapshot = None
        self._preview_slot_id = None
        self._view.refresh_table_rows()

    def apply_preview_to_registers(self) -> bool:
        """Записать текущий preview-snapshot в registers (как load_recipe_to_registers)."""
        if self._preview_snapshot is None or self._preview_slot_id is None:
            return False
        mgr = self._model.recipe_manager
        rm = self._model.rm
        if mgr is None or rm is None:
            return False

        # Сохраняем preview в YAML временно через save_slot, потом load_recipe_to_registers
        # (используем существующий механизм load_recipe_to_registers, чтобы получить
        # снимок до/после и запись в ActionBus).
        # NB: write to YAML — это побочный эффект apply. Если пользователь хочет
        # apply без save — нужен отдельный путь без save_slot. Сейчас Apply подразумевает
        # «текущий snapshot становится истиной» — это согласовано с расширенной save-семантикой.
        if hasattr(mgr, "save_slot"):
            mgr.save_slot(str(self._preview_slot_id), self._preview_snapshot)

        snapshot_before = rm.model_dump_all() if rm else {}
        mgr.set_current_register_recipe_number(self._preview_slot_id)
        ok = mgr.load_recipe_to_registers(rm, str(self._preview_slot_id))
        if not ok:
            return False

        if self._action_bus is not None and rm is not None:
            from multiprocess_prototype.frontend.actions.builder import ActionBuilder

            snapshot_after = rm.model_dump_all()
            action = ActionBuilder.recipe_switch(
                str(self._preview_slot_id), snapshot_before, snapshot_after
            )
            self._action_bus.record(action)

        applied_slot = self._preview_slot_id
        # Выходим из preview — теперь registers и snapshot совпадают
        self._preview_snapshot = None
        self._preview_slot_id = None
        self._view.refresh_table_rows()
        if self._model.on_recipe_applied:
            self._model.on_recipe_applied(applied_slot)
        return True

    def save_preview_to_yaml(self) -> bool:
        """Сохранить текущий preview-snapshot в YAML (recipe_manager.save_slot)."""
        if self._preview_snapshot is None or self._preview_slot_id is None:
            return False
        mgr = self._model.recipe_manager
        if mgr is None or not hasattr(mgr, "save_slot"):
            return False
        ok = bool(mgr.save_slot(str(self._preview_slot_id), self._preview_snapshot))
        if ok and self._model.on_recipe_saved:
            self._model.on_recipe_saved(self._preview_slot_id)
        return ok

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

        # Снимок до загрузки (для undo)
        snapshot_before = rm.model_dump_all() if rm else {}

        mgr.set_current_register_recipe_number(idx)
        mgr.load_recipe_to_registers(rm, str(idx))

        # Запись в ActionBus (record — без повторного apply, load уже выполнен)
        if self._action_bus is not None and rm is not None:
            from multiprocess_prototype.frontend.actions.builder import ActionBuilder

            snapshot_after = rm.model_dump_all()
            action = ActionBuilder.recipe_switch(str(idx), snapshot_before, snapshot_after)
            self._action_bus.record(action)

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

        # Снимок до загрузки (для undo)
        snapshot_before = rm.model_dump_all() if rm else {}

        if not mgr.load_recipe_to_registers(rm, DEFAULT_RECIPE_SLOT_ID):
            mgr.load_recipe_to_registers(rm, "default_value")

        # Запись в ActionBus (record — без повторного apply, load уже выполнен)
        if self._action_bus is not None and rm is not None:
            from multiprocess_prototype.frontend.actions.builder import ActionBuilder

            snapshot_after = rm.model_dump_all()
            action = ActionBuilder.recipe_switch(
                DEFAULT_RECIPE_SLOT_ID,
                snapshot_before,
                snapshot_after,
            )
            self._action_bus.record(action)

        self._view.refresh_table_rows()

    def initial_slot(self) -> int:
        """Стартовый слот из менеджера или UI."""
        return self._model.compute_initial_slot()

    def build_rows(self) -> list:
        """Строки из preview-snapshot если активен, иначе из rm. Форматирование value."""
        if self._preview_snapshot is not None:
            rows = build_recipe_rows_from_snapshot(
                self._model.rm, self._preview_snapshot, self._model.access_ctx
            )
        else:
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
        """Парсинг строки → set_field_value (rm) или запись в preview-snapshot."""
        register_name = row.get("register_name")
        field_name = row.get("field_name")
        field_id = row.get("field_id")
        if not register_name or not field_name or not field_id:
            return

        if self._preview_snapshot is not None:
            # В preview-режиме редактирование пишет в snapshot, не в rm
            prev = self._preview_field_value(register_name, field_name)
            new_val = coerce_string_to_value(text, prev)
            self._preview_snapshot.setdefault(register_name, {})[field_name] = new_val
            self._view.set_leaf_value_text(
                register_name, str(field_id), format_value_for_cell(new_val)
            )
            return

        prev = self.current_field_value(register_name, field_name)
        new_val = coerce_string_to_value(text, prev)
        ok, _err = self._model.rm.set_field_value(register_name, field_name, new_val)
        if not ok:
            self._view.set_leaf_value_text(
                register_name, str(field_id), format_value_for_cell(prev)
            )
            return
        self._view.set_leaf_value_text(
            register_name,
            str(field_id),
            format_value_for_cell(self.current_field_value(register_name, field_name)),
        )

    def _preview_field_value(self, register_name: str, field_name: str) -> Any:
        """Текущее значение поля в preview-snapshot (либо None если ещё не задано)."""
        if self._preview_snapshot is None:
            return None
        reg_data = self._preview_snapshot.get(register_name)
        if not isinstance(reg_data, dict):
            return None
        return reg_data.get(field_name)
