# multiprocess_prototype_v3/frontend/widgets/_recipe_panel_base.py
"""Базовый класс для панелей рецептов: общий UI (слот + кнопки + дерево)."""

from __future__ import annotations

import abc
from typing import Any, Optional, TypeVar

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

from multiprocess_prototype_v3.frontend.coordinators import parse_clamped_recipe_slot_text
from multiprocess_prototype_v3.frontend.touch_keyboard_bind import (
    bind_touch_keyboard_line_edit,
    merge_touch_keyboard_dicts,
)
from multiprocess_prototype_v3.frontend.managers.access_context import AccessContext
from multiprocess_prototype_v3.frontend.managers.recipe_manager_protocol import RecipeManagerProtocol

from .settings_recipe_widget.schemas import RecipesTabConfig

TModel = TypeVar("TModel")


class RecipePanelBase(BaseWidget[TModel], abc.ABC):
    """
    Базовый класс для RegisterRecipePanelWidget и AppRecipePanelWidget.

    Общее:
    - Сигналы load_requested / save_requested / default_requested
    - UI: QGroupBox (слот + кнопки) + StructuredTwoLevelTreeWidget
    - Логика кнопок: presenter.on_load/save/default + сигнал
    - parse_slot, set_leaf_value_text, _on_leaf_value_changed_slot

    Подкласс реализует:
    - _get_box_title() → str — заголовок QGroupBox
    - _get_table_title() → str — подпись над деревом
    - _build_tree_data() → list — данные для дерева
    """

    load_requested = pyqtSignal(int)
    save_requested = pyqtSignal(int)
    default_requested = pyqtSignal()

    # ------------------------------------------------------------------
    # Абстрактные методы — подкласс ОБЯЗАН реализовать
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def _get_box_title(self) -> str:
        """Заголовок QGroupBox (слот + кнопки)."""

    @abc.abstractmethod
    def _get_table_title(self) -> str:
        """Подпись над деревом полей."""

    @abc.abstractmethod
    def _build_tree_data(self) -> list:
        """Построить данные для дерева (groups для set_data)."""

    # ------------------------------------------------------------------
    # Общая реализация
    # ------------------------------------------------------------------

    def _coerce_ui(self, ui: Optional[object]) -> RecipesTabConfig:
        """Привести ui к RecipesTabConfig."""
        return coerce_schema_config(ui, RecipesTabConfig)

    def _init_ui(self) -> None:
        """QGroupBox со слотом и кнопками; заголовок; дерево полей."""
        m = self._model
        assert m is not None
        u = self._ui
        tk_slot = merge_touch_keyboard_dicts(
            self._touch_keyboard, getattr(u, "touch_keyboard_slot", None)
        )
        tk_tree = merge_touch_keyboard_dicts(
            self._touch_keyboard, getattr(u, "touch_keyboard_tree", None)
        )
        layout = QVBoxLayout(self)

        # --- Блок: слот + Загрузить / Сохранить / По умолчанию ---
        box = QGroupBox(self._get_box_title())
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

        # --- Блок: заголовок и дерево (параметр / значение / описание) ---
        layout.addWidget(QLabel(self._get_table_title()))
        columns = [
            {"key": "param", "label": u.col_param, "type": "text", "editable": False},
            {"key": "value", "label": u.col_value, "type": "text", "editable": True},
            {"key": "info", "label": u.col_info, "type": "text", "editable": False},
        ]
        self._tree = StructuredTwoLevelTreeWidget(columns=columns, touch_keyboard=tk_tree)
        self._tree.set_row_key("field_id")
        self._block_table = False
        layout.addWidget(self._tree, 1)

    def _connect_signals(self) -> None:
        """Кнопки → презентер и/или pyqtSignal; изменение ячейки → презентер."""
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
        """load через презентер + pyqtSignal load_requested."""
        self._presenter.on_load_clicked()
        self.load_requested.emit(self.parse_slot())

    def _on_save_with_signal(self) -> None:
        """save через презентер + save_requested."""
        idx = self.parse_slot()
        self._presenter.on_save_clicked()
        self.save_requested.emit(idx)

    def _on_default_with_signal(self) -> None:
        """Сброс к дефолту через презентер + default_requested."""
        self._presenter.on_default_clicked()
        self.default_requested.emit()

    def parse_slot(self) -> int:
        """Номер слота из QLineEdit (min/max из UI)."""
        u = self._ui
        return parse_clamped_recipe_slot_text(
            self._slot.text(),
            min_index=u.recipe_index_min,
            max_index=u.recipe_index_max,
            fallback_on_invalid=u.recipe_index_min,
        )

    def refresh_table_rows(self) -> None:
        """Перезаполнить дерево с блокировкой сигналов."""
        if self._tree is None:
            return
        groups = self._build_tree_data()
        self._block_table = True
        self._tree.blockSignals(True)
        self._tree.set_data(groups)
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
