# multiprocess_prototype/frontend/widgets/settings_recipe_widget/panel_widget.py
"""Панель app-рецептов (UI-схемы): BaseWidget + MVP."""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from frontend_module.core.qt_imports import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    pyqtSignal,
)
from frontend_module.core.schema_config import coerce_schema_config
from frontend_module.widgets.base_widget import BaseWidget
from frontend_module.widgets.tables.structured_two_level_tree import StructuredTwoLevelTreeWidget
from frontend_module.widgets.tabs import callback_no_args

from multiprocess_prototype_v2.frontend.coordinators import parse_clamped_recipe_slot_text
from multiprocess_prototype_v2.frontend.touch_keyboard_bind import (
    bind_touch_keyboard_line_edit,
    merge_touch_keyboard_dicts,
)
from multiprocess_prototype_v2.managers.access_context import AccessContext
from multiprocess_prototype_v2.managers.app_recipe_aggregate import build_default_app_aggregate
from multiprocess_prototype_v2.managers.recipe_manager_protocol import RecipeManagerProtocol

from .schemas import RecipesTabConfig
from .model import AppRecipeModel
from .presenter import AppRecipePresenter


class AppRecipePanelWidget(BaseWidget[AppRecipeModel]):
    """Слот и таблица полей app-рецепта (без регистровых слайдеров)."""

    load_requested = pyqtSignal(int)
    save_requested = pyqtSignal(int)
    default_requested = pyqtSignal()

    def __init__(
        self,
        *,
        ui: Optional[Union[RecipesTabConfig, dict]] = None,
        recipes_tab_dict: Optional[Dict[str, Any]] = None,
        processing_tab_ui_dict: Optional[Dict[str, Any]] = None,
        recipe_manager: Optional[RecipeManagerProtocol] = None,
        recipe_access: Optional[Union[AccessContext, dict]] = None,
        touch_keyboard: Any | None = None,
        parent: Optional[Any] = None,
    ) -> None:
        """Собрать зависимости (словари UI, менеджер рецептов, доступ) и вызвать BaseWidget."""
        self._touch_keyboard = touch_keyboard
        self._recipes_tab_dict = dict(recipes_tab_dict or {})
        self._processing_tab_ui_dict = dict(processing_tab_ui_dict or {})
        self._extra_recipe_manager = recipe_manager
        self._extra_access_ctx = (
            recipe_access
            if isinstance(recipe_access, AccessContext)
            else AccessContext.from_dict(recipe_access if isinstance(recipe_access, dict) else None)
        )
        self._initial_aggregate = build_default_app_aggregate(
            recipes_tab_dict=self._recipes_tab_dict,
            processing_tab_ui_dict=self._processing_tab_ui_dict,
        )
        super().__init__(registers_manager=None, ui=ui, parent=parent)

    def _coerce_ui(self, ui: Optional[object]) -> RecipesTabConfig:
        """Привести ui к RecipesTabConfig (dict или None → схема)."""
        return coerce_schema_config(ui, RecipesTabConfig)

    def _create_model(self) -> AppRecipeModel:
        """Создать модель с копией начального агрегата app-схем."""
        agg_copy = dict(self._initial_aggregate)
        return AppRecipeModel(
            ui=self._ui,
            recipes_tab_dict=self._recipes_tab_dict,
            processing_tab_ui_dict=self._processing_tab_ui_dict,
            recipe_manager=self._extra_recipe_manager,
            access_ctx=self._extra_access_ctx,
            app_aggregate=agg_copy,
        )

    def _init_ui(self) -> None:
        """Построить вертикальный layout: группа слота/кнопок, заголовок, таблица полей."""
        m = self._model
        assert m is not None
        u = self._ui
        tk_slot = merge_touch_keyboard_dicts(self._touch_keyboard, getattr(u, "touch_keyboard_slot", None))
        tk_tree = merge_touch_keyboard_dicts(self._touch_keyboard, getattr(u, "touch_keyboard_tree", None))
        layout = QVBoxLayout(self)

        # --- Блок: слот рецепта + кнопки Загрузить / Сохранить / По умолчанию ---
        box = QGroupBox(u.group_app_box)
        ctrl = QHBoxLayout(box)
        ctrl.addWidget(QLabel(u.label_slot))
        self._slot = QLineEdit()
        self._slot.setFixedWidth(56)
        self._slot.setText(str(m.compute_initial_slot()))
        ctrl.addWidget(self._slot)
        bind_touch_keyboard_line_edit(self, self._slot, tk_slot)
        self._btn_load = QPushButton(u.btn_load)
        self._btn_save = QPushButton(u.btn_save)
        self._btn_default = QPushButton(u.btn_default)
        ctrl.addWidget(self._btn_load)
        ctrl.addWidget(self._btn_save)
        ctrl.addWidget(self._btn_default)
        ctrl.addStretch()
        layout.addWidget(box)

        # --- Блок: подпись и дерево схема → поля (параметр / значение / инфо) ---
        layout.addWidget(QLabel(u.table_app_group_title))
        columns = [
            {"key": "param", "label": u.col_param, "type": "text", "editable": False},
            {"key": "value", "label": u.col_value, "type": "text", "editable": True},
            {"key": "info", "label": u.col_info, "type": "text", "editable": False},
        ]
        self._tree = StructuredTwoLevelTreeWidget(columns=columns, touch_keyboard=tk_tree)
        self._tree.set_row_key("field_id")
        self._block_table = False
        layout.addWidget(self._tree, 1)

    def _create_presenter(self, model: Optional[AppRecipeModel]) -> AppRecipePresenter:
        """Связать эту панель как view с презентером."""
        assert model is not None
        return AppRecipePresenter(view=self, model=model)

    def _connect_signals(self) -> None:
        """Кнопки → презентер и/или pyqtSignal; изменение ячейки таблицы → презентер."""
        _btn = callback_no_args
        mgr = self._model.recipe_manager if self._model else None

        if mgr is not None:
            self._btn_load.clicked.connect(_btn(self._on_load_with_signal))
            self._btn_save.clicked.connect(_btn(self._on_save_with_signal))
            self._btn_default.clicked.connect(_btn(self._on_default_with_signal))
        else:
            self._btn_load.clicked.connect(lambda: self.load_requested.emit(self.parse_slot()))
            self._btn_save.clicked.connect(lambda: self.save_requested.emit(self.parse_slot()))
            self._btn_default.clicked.connect(self.default_requested.emit)

        self._tree.leaf_cell_changed.connect(self._on_leaf_value_changed_slot)

    def _on_load_with_signal(self) -> None:
        """Загрузка через презентер и сигнал load_requested (с номером слота)."""
        self._presenter.on_load_clicked()
        self.load_requested.emit(self.parse_slot())

    def _on_save_with_signal(self) -> None:
        """Сохранение через презентер и сигнал save_requested."""
        idx = self.parse_slot()
        self._presenter.on_save_clicked()
        self.save_requested.emit(idx)

    def _on_default_with_signal(self) -> None:
        """Сброс к дефолту через презентер и сигнал default_requested."""
        self._presenter.on_default_clicked()
        self.default_requested.emit()

    def _on_presenter_ready(self, **kwargs: Any) -> None:
        """После готовности презентера — первичное заполнение таблицы."""
        self.refresh_table_rows()

    def parse_slot(self) -> int:
        """Номер слота из QLineEdit с ограничением по min/max из UI."""
        u = self._ui
        return parse_clamped_recipe_slot_text(
            self._slot.text(),
            min_index=u.recipe_index_min,
            max_index=u.recipe_index_max,
            fallback_on_invalid=u.recipe_index_min,
        )

    def refresh_table_rows(self) -> None:
        """Перезаполнить дерево из презентера (с блокировкой сигналов)."""
        if self._tree is None:
            return
        p = self._presenter
        self._block_table = True
        self._tree.blockSignals(True)
        self._tree.set_data(p.build_tree_groups())
        self._tree.blockSignals(False)
        self._block_table = False

    def set_leaf_value_text(self, group_id: str, field_id: str, text: str) -> None:
        if self._tree is not None:
            self._tree.set_leaf_cell_text(group_id, field_id, "value", text)

    def _on_leaf_value_changed_slot(
        self, group_id: str, field_id: str, column_key: str, value: Any
    ) -> None:
        """Редактирование колонки «значение» → презентер."""
        if self._block_table or self._tree is None:
            return
        if column_key != "value":
            return
        self._presenter.on_leaf_value_changed(group_id, field_id, column_key, str(value))
