# multiprocess_prototype_v3/frontend/widgets/tabs_setting/recipes_tab/widget.py
"""
RecipesTabWidget — вкладка рецептов.

Layout:
  Слева  — RecipesSlotButtonsPanel (навигация по слотам)
  Справа — GroupBox «Рецепт регистров»:
             Row: Название + QLineEdit + кнопки действий + ViewModeToggle
             RecipeContentSection (SearchFilterBar + Cards/Table)

Поведение:
- Клик по слоту в левой панели → preview из YAML (или live для #0).
- Название редактируется в QLineEdit → обновляет label в левой панели.
- Сохранить: confirm → recipe_manager.save_slot.
- Применить: confirm → save + load_recipe_to_registers.
- Копировать/Вставить: clipboard JSON.

Reparenting-хак удалён. Вместо него — _BareRegisterRecipePanel,
который переопределяет _arrange_default_layout() и не строит
QGroupBox. Виджеты доступны через self._tree, self._btn_save и т.д.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    Signal,
)
from multiprocess_framework.modules.frontend_module.core.schema_config import (
    coerce_schema_config,
)
from multiprocess_framework.modules.frontend_module.interfaces import (
    IRegistersManagerGui,
)
from multiprocess_framework.modules.frontend_module.widgets.tabs import (
    BaseTab,
    RegisterBindingContext,
    create_registers_placeholder,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox

from multiprocess_prototype_v3.frontend.managers.access_context import (
    AccessContext,
)
from multiprocess_prototype_v3.frontend.managers.recipe_manager_protocol import (
    RecipeManagerProtocol,
)
from multiprocess_prototype_v3.frontend.touch_keyboard_bind import (
    merge_touch_keyboard_dicts,
)

from ...recipes.recipes_slot_buttons import RecipesSlotButtonsPanel
from ...recipes.recipes_widget import RegisterRecipePanelWidget as RegisterRecipePanel
from ...recipes.settings_recipe_widget.schemas import RecipesTabConfig
from ...settings.settings_tab.prefs_store import (
    KEY_RECIPES_MODE,
    get_view_mode,
    set_view_mode,
)
from ...chrome.view_mode_toggle import ViewModeToggle
from .recipe_content_section import RecipeContentSection

_SLOT_PANEL_WIDTH = 200


class _BareRegisterRecipePanel(RegisterRecipePanel):
    """Режим без auto-layout — виджеты создаются, но layout
    строит RecipesTabWidget. Все виджеты доступны как self._tree,
    self._btn_save, self._btn_load, self._btn_default, self._slot_combo.
    """

    def _arrange_default_layout(self) -> None:
        # Не строим QGroupBox — пустой layout
        QVBoxLayout(self)


class RecipesTabWidget(BaseTab):
    """Вкладка «Рецепты»: список слотов + GroupBox с таблицей и кнопками."""

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
            else AccessContext.from_dict(
                recipe_access
                if isinstance(recipe_access, dict)
                else None,
            )
        )
        self._on_recipe_applied = on_recipe_applied
        self._on_recipe_saved = on_recipe_saved
        self._touch_keyboard = merge_touch_keyboard_dicts(
            touch_keyboard,
            getattr(self._ui, "touch_keyboard", None),
        )
        self._register_panel: _BareRegisterRecipePanel | None = None
        self._slot_panel: RecipesSlotButtonsPanel | None = None
        self._content_section: RecipeContentSection | None = None
        self._init_ui()

    @property
    def registers_manager(self) -> IRegistersManagerGui | None:
        return self._registers_manager

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        binding = RegisterBindingContext(rm=self._registers_manager)

        if not binding.can_bind:
            layout.addWidget(
                create_registers_placeholder("Рецепты"),
            )
            layout.addStretch()
            return

        rm = binding.rm
        assert rm is not None

        # --- Создаём _BareRegisterRecipePanel (виджеты без auto-layout) ---
        self._register_panel = _BareRegisterRecipePanel(
            rm=rm,
            ui=self._ui,
            recipe_manager=self._recipe_manager,
            recipe_access=self._access_ctx,
            touch_keyboard=self._touch_keyboard,
            action_bus=self._action_bus,
            on_recipe_applied=self._on_recipe_applied,
            on_recipe_saved=self._on_recipe_saved,
        )
        self._register_panel.load_requested.connect(
            self.recipe_load_requested.emit,
        )
        self._register_panel.save_requested.connect(
            self.recipe_save_requested.emit,
        )
        self._register_panel.default_requested.connect(
            self.recipe_default_requested.emit,
        )

        # Скрываем элементы, нужные только presenter'у
        self._register_panel._btn_load.hide()
        self._register_panel._slot_combo.hide()

        # --- Строим GroupBox «Рецепт регистров» ---
        box = QGroupBox("Рецепт регистров")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(8, 12, 8, 8)
        box_layout.setSpacing(6)

        # Row 1: Название + QLineEdit + кнопки действий + ViewModeToggle
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(QLabel("Название:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Название рецепта")
        self._name_edit.setMinimumWidth(140)
        self._name_edit.textChanged.connect(self._on_name_changed)
        row1.addWidget(self._name_edit, 1)
        row1.addSpacing(12)

        # Кнопки действий
        self._btn_apply = QPushButton("Применить")
        self._btn_apply.setToolTip(
            "Применить параметры к текущим регистрам",
        )
        self._btn_apply.clicked.connect(self._on_apply_clicked)
        row1.addWidget(self._btn_apply)

        btn_save = self._register_panel._btn_save
        btn_save.setText("Сохранить")
        row1.addWidget(btn_save)

        row1.addWidget(self._register_panel._btn_default)

        self._btn_copy = QPushButton("Копир.")
        self._btn_copy.setToolTip("Копировать параметры в буфер")
        self._btn_copy.clicked.connect(self._on_copy_clicked)
        row1.addWidget(self._btn_copy)

        self._btn_paste = QPushButton("Вставить")
        self._btn_paste.setToolTip("Вставить параметры из буфера")
        self._btn_paste.clicked.connect(self._on_paste_clicked)
        row1.addWidget(self._btn_paste)

        # ViewModeToggle — справа в toolbar
        initial_mode = get_view_mode(KEY_RECIPES_MODE, default=1)
        self._view_toggle = ViewModeToggle()
        self._view_toggle.set_mode(initial_mode)
        self._view_toggle.mode_changed.connect(self._on_mode_changed)
        row1.addWidget(self._view_toggle)

        box_layout.addLayout(row1)

        # RecipeContentSection (SearchFilterBar + Cards/Table)
        self._content_section = RecipeContentSection(
            register_panel=self._register_panel,
            initial_mode=initial_mode,
        )
        box_layout.addWidget(self._content_section, 1)

        # Скрытые виджеты в layout панели (чтобы presenter работал)
        panel_layout = self._register_panel.layout()
        if panel_layout is not None:
            panel_layout.addWidget(box)
            panel_layout.addWidget(self._register_panel._slot_combo)
            panel_layout.addWidget(self._register_panel._btn_load)

        # --- Левая панель: список слотов ---
        self._slot_panel = RecipesSlotButtonsPanel(
            slot_min=self._ui.recipe_index_min,
            slot_max=self._ui.recipe_index_max,
        )
        self._slot_panel.setFixedWidth(_SLOT_PANEL_WIDTH)
        self._slot_panel.slot_selected.connect(self._on_slot_selected)

        # --- Общий layout: слева список, справа scroll с панелью ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        scroll.setWidget(inner)
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._register_panel, 1)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)
        body.addWidget(self._slot_panel)
        body.addWidget(scroll, 1)
        layout.addLayout(body, 1)

        # --- Начальное состояние ---
        rm_obj = self._recipe_manager
        if rm_obj is not None and hasattr(
            rm_obj, "get_current_register_recipe_number",
        ):
            try:
                applied = int(
                    rm_obj.get_current_register_recipe_number(),
                )
                self._slot_panel.set_applied_slot(applied)
                self._slot_panel.set_selected_slot(applied)
                self._sync_combo_to_slot(applied)
                if applied == 0:
                    self._register_panel.refresh_from_registers()
                else:
                    self._register_panel.enter_preview(applied)
                self._update_name_edit(applied)
            except (TypeError, ValueError):
                pass

    # --------------------------------------------------------------
    # ViewModeToggle
    # --------------------------------------------------------------

    def _on_mode_changed(self, mode: int) -> None:
        """Переключение cards/table через ViewModeToggle."""
        set_view_mode(KEY_RECIPES_MODE, mode)
        if self._content_section is not None:
            self._content_section.set_mode(mode)

    # --------------------------------------------------------------
    # Slot panel handlers
    # --------------------------------------------------------------

    def _on_slot_selected(self, slot_id: int) -> None:
        """Клик по слоту → показать параметры.
        #0 — живые регистры, остальные — preview из YAML."""
        if self._register_panel is not None:
            self._sync_combo_to_slot(slot_id)
            if slot_id == 0:
                self._register_panel.exit_preview()
                self._register_panel.refresh_from_registers()
            else:
                self._register_panel.enter_preview(slot_id)
        self._update_name_edit(slot_id)

    def _sync_combo_to_slot(self, slot_id: int) -> None:
        """Синхронизировать скрытый ComboBox с выбранным слотом
        (для presenter)."""
        if self._register_panel is not None:
            self._register_panel.set_slot_index(slot_id)

    def _update_name_edit(self, slot_id: int) -> None:
        """Обновить QLineEdit «Название» при смене слота."""
        if not hasattr(self, "_name_edit") or self._slot_panel is None:
            return
        name = self._slot_panel.get_slot_name(slot_id)
        self._name_edit.blockSignals(True)
        self._name_edit.setText(name)
        self._name_edit.blockSignals(False)

    def _on_name_changed(self, text: str) -> None:
        """Пользователь редактирует название → обновить левую панель."""
        if self._slot_panel is None:
            return
        slot_id = self._slot_panel.selected_slot()
        if slot_id is not None:
            self._slot_panel.set_slot_name(slot_id, text)

    # --------------------------------------------------------------
    # Action button handlers
    # --------------------------------------------------------------

    def _on_apply_clicked(self) -> None:
        """Применить выбранный рецепт к регистрам."""
        if self._slot_panel is None or self._register_panel is None:
            return
        slot_id = self._slot_panel.selected_slot()
        if slot_id is None:
            return
        if slot_id == 0:
            return  # #0 уже отражает текущие регистры
        if self._register_panel.preview_slot_id() != slot_id:
            self._register_panel.enter_preview(slot_id)
        if not self._confirm(
            "Применить рецепт",
            f"Применить параметры слота #{slot_id} к текущим "
            "регистрам?\nЭто перезапишет YAML файл слота "
            "отредактированным snapshot.",
        ):
            return
        ok = self._register_panel.apply_preview_to_registers()
        if not ok:
            self._warn(
                f"Не удалось применить слот #{slot_id}.",
            )
            return
        self._slot_panel.set_applied_slot(slot_id)
        self._register_panel.enter_preview(slot_id)
        self.recipe_load_requested.emit(slot_id)

    def _on_copy_clicked(self) -> None:
        if self._slot_panel is None:
            return
        slot_id = self._slot_panel.selected_slot()
        if slot_id is None:
            return
        snapshot = self._read_snapshot(slot_id)
        if snapshot is None:
            self._warn(
                f"Слот #{slot_id} пуст — нечего копировать.",
            )
            return
        text = json.dumps(
            snapshot, ensure_ascii=False, indent=2, default=str,
        )
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

    def _on_paste_clicked(self) -> None:
        if self._slot_panel is None:
            return
        slot_id = self._slot_panel.selected_slot()
        if slot_id is None:
            return
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
            self._warn(
                f"Буфер не содержит валидный JSON-снапшот:\n{exc}",
            )
            return
        if not isinstance(data, dict):
            self._warn("Снапшот должен быть объектом (dict).")
            return
        rm_obj = self._recipe_manager
        if rm_obj is None or not hasattr(rm_obj, "save_slot"):
            self._warn(
                "recipe_manager не поддерживает save_slot.",
            )
            return
        if not rm_obj.save_slot(str(slot_id), data):
            self._warn(
                f"Не удалось сохранить слот #{slot_id}.",
            )
            return
        if self._register_panel is not None:
            self._register_panel.enter_preview(slot_id)

    # --------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------

    def _read_snapshot(
        self, slot_id: int,
    ) -> dict[str, Any] | None:
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
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, "Рецепты", text)

    # --------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------

    def refresh_from_registers(self) -> None:
        if self._register_panel is not None:
            self._register_panel.refresh_from_registers()
