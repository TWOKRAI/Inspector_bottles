# multiprocess_prototype_v3/frontend/widgets/tabs_setting/recipes_tab/widget.py
"""
RecipesTabWidget — вкладка рецептов.

Левая полоса — кнопки сортов (визуальный выбор) + Сохранить / Применить /
Копировать / Вставить.
Справа — основная таблица регистров.

Поведение:
- Клик по кнопке слота: register_panel.enter_preview(slot_id) — таблица
  показывает snapshot YAML слота. Регистры не трогаются.
- Редактирование в таблице: пишет в snapshot (presenter.apply_value_cell в
  preview-режиме). Auto-save отключён — нужно явное «Сохранить».
- Сохранить: confirm-диалог → recipe_manager.save_slot.
- Применить: confirm-диалог → save_slot + load_recipe_to_registers; после
  apply подсветка applied переезжает на этот слот, preview сбрасывается.
- Копировать: snapshot текущего слота → JSON → системный clipboard.
- Вставить: clipboard JSON → recipe_manager.save_slot(selected) → перечитать
  preview.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    Signal,
)
from multiprocess_framework.modules.frontend_module.core.schema_config import coerce_schema_config
from multiprocess_framework.modules.frontend_module.interfaces import IRegistersManagerGui
from multiprocess_framework.modules.frontend_module.widgets.tabs import (
    BaseTab,
    RegisterBindingContext,
    create_registers_placeholder,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox

from multiprocess_prototype_v3.frontend.managers.access_context import AccessContext
from multiprocess_prototype_v3.frontend.managers.recipe_manager_protocol import (
    RecipeManagerProtocol,
)
from multiprocess_prototype_v3.frontend.touch_keyboard_bind import merge_touch_keyboard_dicts

from ...recipes_slot_buttons import RecipesSlotButtonsPanel
from ...recipes_widget import RegisterRecipePanelWidget as RegisterRecipePanel
from ...search_filter_bar import SearchFilterBar
from ...settings_recipe_widget.schemas import RecipesTabConfig

_SLOT_PANEL_WIDTH = 170


class RecipesTabWidget(BaseTab):
    """Вкладка «Рецепты»: слот-кнопки + таблица параметров (preview слота)."""

    recipe_load_requested = Signal(int)
    recipe_save_requested = Signal(int)
    recipe_default_requested = Signal()

    def __init__(
        self,
        *,
        registers_manager: IRegistersManagerGui | None = None,
        ui: RecipesTabConfig | dict | None = None,
        recipe_manager: RecipeManagerProtocol | None = None,
        recipe_access: AccessContext | dict | None = None,
        on_recipe_applied: Callable[[int], None] | None = None,
        on_recipe_saved: Callable[[int], None] | None = None,
        touch_keyboard: Any | None = None,
        action_bus: Any | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._action_bus = action_bus
        self._ui = coerce_schema_config(ui, RecipesTabConfig)
        self._recipe_manager = recipe_manager
        self._access_ctx = (
            recipe_access
            if isinstance(recipe_access, AccessContext)
            else AccessContext.from_dict(recipe_access if isinstance(recipe_access, dict) else None)
        )
        self._on_recipe_applied = on_recipe_applied
        self._on_recipe_saved = on_recipe_saved
        self._touch_keyboard = merge_touch_keyboard_dicts(
            touch_keyboard, getattr(self._ui, "touch_keyboard", None)
        )
        self._register_panel: RegisterRecipePanel | None = None
        self._slot_panel: RecipesSlotButtonsPanel | None = None
        self._init_ui()

    @property
    def registers_manager(self) -> IRegistersManagerGui | None:
        return self._registers_manager

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        binding = RegisterBindingContext(rm=self._registers_manager)

        if not binding.can_bind:
            layout.addWidget(create_registers_placeholder("Рецепты"))
            layout.addStretch()
            return

        rm = binding.rm
        assert rm is not None

        self._search_bar = SearchFilterBar()
        self._search_bar.filter_changed.connect(self._on_filter_changed)
        self._search_bar.sort_changed.connect(self._on_sort_changed)
        layout.addWidget(self._search_bar)

        self._register_panel = RegisterRecipePanel(
            rm=rm,
            ui=self._ui,
            recipe_manager=self._recipe_manager,
            recipe_access=self._access_ctx,
            touch_keyboard=self._touch_keyboard,
            action_bus=self._action_bus,
            on_recipe_applied=self._on_recipe_applied,
            on_recipe_saved=self._on_recipe_saved,
        )
        self._register_panel.load_requested.connect(self.recipe_load_requested.emit)
        self._register_panel.save_requested.connect(self.recipe_save_requested.emit)
        self._register_panel.default_requested.connect(self.recipe_default_requested.emit)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        scroll.setWidget(inner)
        v = QVBoxLayout(inner)
        v.addWidget(self._register_panel, 1)

        self._slot_panel = RecipesSlotButtonsPanel(
            slot_min=self._ui.recipe_index_min,
            slot_max=self._ui.recipe_index_max,
        )
        self._slot_panel.setFixedWidth(_SLOT_PANEL_WIDTH)
        self._slot_panel.slot_selected.connect(self._on_slot_selected)
        self._slot_panel.slot_apply_requested.connect(self._on_slot_apply)
        self._slot_panel.slot_save_requested.connect(self._on_slot_save)
        self._slot_panel.slot_copy_requested.connect(self._on_slot_copy)
        self._slot_panel.slot_paste_requested.connect(self._on_slot_paste)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)
        body.addWidget(self._slot_panel)
        body.addWidget(scroll, 1)
        layout.addLayout(body, 1)

        # Подсветить applied + сразу зайти в preview этого слота
        rm_obj = self._recipe_manager
        if rm_obj is not None and hasattr(rm_obj, "get_current_register_recipe_number"):
            try:
                applied = int(rm_obj.get_current_register_recipe_number())
                self._slot_panel.set_applied_slot(applied)
                self._slot_panel.set_selected_slot(applied)
                self._register_panel.enter_preview(applied)
            except (TypeError, ValueError):
                pass

        self._filter_text = ""
        self._filter_category = ""
        self._sort_field = ""
        self._sort_asc = True

    # --------------------------------------------------------------
    # Slot panel handlers
    # --------------------------------------------------------------

    def _on_slot_selected(self, slot_id: int) -> None:
        """Клик по слоту → таблица показывает snapshot слота (preview)."""
        if self._register_panel is not None:
            self._register_panel.enter_preview(slot_id)

    def _on_slot_apply(self, slot_id: int) -> None:
        """Применить slot к registers (с подтверждением)."""
        if self._register_panel is None:
            return
        # Гарантируем preview активен (если пользователь не кликал по слоту — войдём)
        if self._register_panel.preview_slot_id() != slot_id:
            self._register_panel.enter_preview(slot_id)
        if not self._confirm(
            "Применить рецепт",
            f"Применить параметры слота #{slot_id} к текущим регистрам?\n"
            "Это перезапишет YAML файл слота отредактированным snapshot.",
        ):
            return
        ok = self._register_panel.apply_preview_to_registers()
        if not ok:
            self._warn(f"Не удалось применить слот #{slot_id}.")
            return
        if self._slot_panel is not None:
            self._slot_panel.set_applied_slot(slot_id)
            # После apply мы вышли из preview — снова войдём, чтобы таблица
            # показывала ту же картину (registers == snapshot).
            self._register_panel.enter_preview(slot_id)
        self.recipe_load_requested.emit(slot_id)

    def _on_slot_save(self, slot_id: int) -> None:
        """Сохранить отредактированный snapshot в YAML (с подтверждением)."""
        if self._register_panel is None:
            return
        if self._register_panel.preview_slot_id() != slot_id:
            self._register_panel.enter_preview(slot_id)
        if not self._confirm(
            "Сохранить рецепт",
            f"Сохранить отредактированные параметры в YAML слота #{slot_id}?",
        ):
            return
        ok = self._register_panel.save_preview_to_yaml()
        if not ok:
            self._warn(f"Не удалось сохранить слот #{slot_id}.")
            return
        self.recipe_save_requested.emit(slot_id)

    def _on_slot_copy(self, slot_id: int) -> None:
        snapshot = self._read_snapshot(slot_id)
        if snapshot is None:
            self._warn(f"Слот #{slot_id} пуст — нечего копировать.")
            return
        text = json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

    def _on_slot_paste(self, slot_id: int) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            return
        text = clipboard.text()
        if not text:
            self._warn("Буфер обмена пуст.")
            return
        try:
            data = json.loads(text)
        except (TypeError, ValueError) as exc:
            self._warn(f"Буфер не содержит валидный JSON-снапшот:\n{exc}")
            return
        if not isinstance(data, dict):
            self._warn("Снапшот должен быть объектом (dict).")
            return
        rm_obj = self._recipe_manager
        if rm_obj is None or not hasattr(rm_obj, "save_slot"):
            self._warn("recipe_manager не поддерживает save_slot.")
            return
        if not rm_obj.save_slot(str(slot_id), data):
            self._warn(f"Не удалось сохранить слот #{slot_id}.")
            return
        # Перечитать preview после вставки
        if self._register_panel is not None:
            self._register_panel.enter_preview(slot_id)

    # --------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------

    def _read_snapshot(self, slot_id: int) -> dict[str, Any] | None:
        rm_obj = self._recipe_manager
        if rm_obj is None or not hasattr(rm_obj, "get_slot"):
            return None
        try:
            return rm_obj.get_slot(str(slot_id))
        except Exception:  # noqa: BLE001
            return None

    def _confirm(self, title: str, text: str) -> bool:
        reply = QMessageBox.question(
            self,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, "Рецепты", text)

    # --------------------------------------------------------------
    # Filter
    # --------------------------------------------------------------

    def _on_filter_changed(self, text: str, category: str) -> None:
        self._filter_text = text
        self._filter_category = category
        if self._register_panel is not None:
            tree = getattr(self._register_panel, "_tree", None)
            if tree is not None:
                self._apply_tree_filter(tree, text, category)

    def _on_sort_changed(self, sort_field: str, asc: bool) -> None:
        self._sort_field = sort_field
        self._sort_asc = asc

    def _apply_tree_filter(self, tree: QWidget, text: str, category: str) -> None:
        root = tree.invisibleRootItem()
        text_lower = text.lower()

        for gi in range(root.childCount()):
            group_item = root.child(gi)
            group_name = group_item.text(0)

            if category and group_name != category:
                group_item.setHidden(True)
                continue

            visible_children = 0
            for ci in range(group_item.childCount()):
                child = group_item.child(ci)
                if not text:
                    child.setHidden(False)
                    visible_children += 1
                    continue

                col0 = child.text(0).lower()
                col2 = child.text(2).lower() if child.columnCount() > 2 else ""
                matches = text_lower in col0 or text_lower in col2
                child.setHidden(not matches)
                if matches:
                    visible_children += 1

            group_item.setHidden(visible_children == 0)

    def refresh_from_registers(self) -> None:
        if self._register_panel is not None:
            self._register_panel.refresh_from_registers()
