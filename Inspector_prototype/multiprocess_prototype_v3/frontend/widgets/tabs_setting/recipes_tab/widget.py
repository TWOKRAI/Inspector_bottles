# multiprocess_prototype_v3/frontend/widgets/tabs_setting/recipes_tab/widget.py
"""
RecipesTabWidget — вкладка рецептов: только рецепты регистров (параметры алгоритма).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
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

from multiprocess_prototype_v3.frontend.managers.access_context import AccessContext
from multiprocess_prototype_v3.frontend.managers.recipe_manager_protocol import (
    RecipeManagerProtocol,
)
from multiprocess_prototype_v3.frontend.touch_keyboard_bind import merge_touch_keyboard_dicts

from ...recipes_cards import RecipesCardsView
from ...recipes_widget import RegisterRecipePanelWidget as RegisterRecipePanel
from ...search_filter_bar import SearchFilterBar
from ...settings_recipe_widget.schemas import RecipesTabConfig
from ...settings_tab.prefs_store import KEY_RECIPES_MODE, get_view_mode, set_view_mode
from ...view_mode_toggle import ViewModeToggle


class RecipesTabWidget(BaseTab):
    """Вкладка «Рецепты»: слот и таблица полей регистров."""

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
        """Панель рецептов регистров в QScrollArea или заглушка без rm."""
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
        self._init_ui()

    @property
    def registers_manager(self) -> IRegistersManagerGui | None:
        """Rm для внешних обновлений."""
        return self._registers_manager

    def _init_ui(self) -> None:
        """Placeholder или RegisterRecipePanel + CardsView с toggle."""
        layout = QVBoxLayout(self)
        binding = RegisterBindingContext(rm=self._registers_manager)

        # --- Нет регистров: только заглушка ---
        if not binding.can_bind:
            layout.addWidget(create_registers_placeholder("Рецепты"))
            layout.addStretch()
            return

        rm = binding.rm
        assert rm is not None

        initial_mode = get_view_mode(KEY_RECIPES_MODE, default=0)

        # Toolbar: toggle справа
        toolbar = QHBoxLayout()
        toolbar.addStretch()
        self._view_toggle = ViewModeToggle()
        self._view_toggle.set_mode(initial_mode)
        self._view_toggle.mode_changed.connect(self._on_mode_changed)
        toolbar.addWidget(self._view_toggle)
        layout.addLayout(toolbar)

        # SearchFilterBar (общий для обоих режимов)
        self._search_bar = SearchFilterBar()
        self._search_bar.filter_changed.connect(self._on_filter_changed)
        self._search_bar.sort_changed.connect(self._on_sort_changed)
        layout.addWidget(self._search_bar)

        # Страница 0: карточки слотов
        self._cards_view = RecipesCardsView(
            slot_min=self._ui.recipe_index_min,
            slot_max=self._ui.recipe_index_max,
        )
        self._cards_view.load_requested.connect(self._on_card_load)
        self._cards_view.save_requested.connect(self.recipe_save_requested.emit)

        # Страница 1: существующая таблица в ScrollArea
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

        self._stack = QStackedWidget()
        self._stack.addWidget(self._cards_view)  # 0=карточки (default)
        self._stack.addWidget(scroll)  # 1=таблица
        self._stack.setCurrentIndex(initial_mode)
        layout.addWidget(self._stack, 1)

        # Подсветить текущий слот в карточках на старте
        if self._recipe_manager is not None and hasattr(
            self._recipe_manager, "get_current_app_recipe_number"
        ):
            try:
                current = int(self._recipe_manager.get_current_app_recipe_number())
                self._cards_view.set_active_slot(current)
            except (TypeError, ValueError):
                pass

        # Состояние фильтра
        self._filter_text = ""
        self._filter_category = ""
        self._sort_field = ""
        self._sort_asc = True

    def _on_mode_changed(self, mode: int) -> None:
        """Переключить между карточками (0) и таблицей (1) + persistence."""
        set_view_mode(KEY_RECIPES_MODE, mode)
        if hasattr(self, "_stack"):
            self._stack.setCurrentIndex(mode)

    def _on_card_load(self, slot_id: int) -> None:
        """Клик 'Загрузить' на карточке: подсветить + проксировать сигнал наверх."""
        if hasattr(self, "_cards_view"):
            self._cards_view.set_active_slot(slot_id)
        self.recipe_load_requested.emit(slot_id)

    def _on_filter_changed(self, text: str, category: str) -> None:
        self._filter_text = text
        self._filter_category = category
        # Фильтрация в таблице через tree items
        if self._register_panel is not None:
            tree = getattr(self._register_panel, "_tree", None)
            if tree is not None:
                self._apply_tree_filter(tree, text, category)

    def _on_sort_changed(self, sort_field: str, asc: bool) -> None:
        self._sort_field = sort_field
        self._sort_asc = asc

    def _apply_tree_filter(self, tree: QWidget, text: str, category: str) -> None:
        """Фильтровать элементы дерева по тексту и категории."""
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
        """Обновить таблицу регистров (например после внешней загрузки рецепта)."""
        if self._register_panel is not None:
            self._register_panel.refresh_from_registers()
