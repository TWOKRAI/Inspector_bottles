# multiprocess_prototype_v3/frontend/widgets/_recipe_panel_base.py
"""Базовый класс для панелей рецептов: общий UI (слот + кнопки + дерево)."""

from __future__ import annotations

import abc
from typing import Any, TypeVar

from frontend_module.core.qt_imports import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    pyqtSignal,
)
from frontend_module.core.schema_config import coerce_schema_config
from frontend_module.widgets.base_widget import BaseWidget
from frontend_module.widgets.tables.structured_two_level_tree import StructuredTwoLevelTreeWidget
from frontend_module.widgets.tabs import callback_no_args

from multiprocess_prototype_v3.frontend.coordinators import parse_clamped_recipe_slot_text
from multiprocess_prototype_v3.frontend.touch_keyboard_bind import merge_touch_keyboard_dicts

from .recipes_widget.auto_save import AutoSaveConfig, QtDebounceAdapter, RecipeAutoSave
from .recipes_widget.slot_combo_model import RecipeSlotComboModel
from .settings_recipe_widget.schemas import RecipesTabConfig

_DEFAULT_AUTOSAVE_DEBOUNCE_MS = 1500

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

    def _coerce_ui(self, ui: object | None) -> RecipesTabConfig:
        """Привести ui к RecipesTabConfig."""
        return coerce_schema_config(ui, RecipesTabConfig)

    def _init_ui(self) -> None:
        """QGroupBox со слотом и кнопками; заголовок; дерево полей."""
        m = self._model
        assert m is not None
        u = self._ui
        tk_tree = merge_touch_keyboard_dicts(
            self._touch_keyboard, getattr(u, "touch_keyboard_tree", None)
        )
        layout = QVBoxLayout(self)

        # --- Блок: слот (ComboBox) + Загрузить / Сохранить / По умолчанию ---
        self._slot_combo_model = RecipeSlotComboModel.from_manager(
            m.recipe_manager,
            u.recipe_index_min,
            u.recipe_index_max,
        )
        initial_slot = str(m.compute_initial_slot())
        self._slot_combo_model.current_index = self._slot_combo_model.index_for_slot_id(initial_slot)

        box = QGroupBox(self._get_box_title())
        ctrl = QHBoxLayout(box)
        ctrl.addWidget(QLabel(u.label_slot))
        self._slot_combo = QComboBox()
        self._slot_combo.setMinimumWidth(96)
        self._slot_combo.addItems(self._slot_combo_model.labels)
        self._slot_combo.setCurrentIndex(self._slot_combo_model.current_index)
        ctrl.addWidget(self._slot_combo)
        self._btn_load = QPushButton(u.btn_load)
        self._btn_save = QPushButton(u.btn_save)
        self._btn_default = QPushButton(u.btn_default)
        ctrl.addWidget(self._btn_load)
        ctrl.addWidget(self._btn_save)
        ctrl.addWidget(self._btn_default)
        ctrl.addStretch()
        layout.addWidget(box)

        # --- Auto-save с debounce + версионированием (Task 1.4) ---
        self._auto_save: RecipeAutoSave | None = None
        self._auto_save_debouncer: QtDebounceAdapter | None = None
        if m.recipe_manager is not None:
            self._auto_save = RecipeAutoSave(
                recipe_manager=m.recipe_manager,
                slot_getter=self._current_slot_id,
                rm_snapshot_fn=self._capture_snapshot,
                config=AutoSaveConfig(),
            )
            self._auto_save_debouncer = QtDebounceAdapter(parent=self)

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
        self._slot_combo.currentIndexChanged.connect(self._on_slot_index_changed)

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
        """Номер слота из QComboBox (min/max из UI).

        ComboBox-индекс конвертируется в slot-id через `RecipeSlotComboModel`,
        затем `parse_clamped_recipe_slot_text` клампит к диапазону UI и возвращает int.
        Fallback на `recipe_index_min` при нечисловом slot-id (например, если будущие
        профили имеют строковые идентификаторы).
        """
        u = self._ui
        combo_idx = self._slot_combo.currentIndex()
        slot_id = self._slot_combo_model.slot_id_for_index(combo_idx)
        return parse_clamped_recipe_slot_text(
            slot_id,
            min_index=u.recipe_index_min,
            max_index=u.recipe_index_max,
            fallback_on_invalid=u.recipe_index_min,
        )

    def _on_slot_index_changed(self, index: int) -> None:
        """Смена слота в ComboBox — загрузка рецепта через presenter (Task 1.4)."""
        if self._slot_combo_model is not None:
            self._slot_combo_model.current_index = index
        if self._model and self._model.recipe_manager is not None:
            # Отменяем pending auto-save от предыдущего слота — иначе он запишет его
            # данные в только что выбранный слот.
            if self._auto_save_debouncer is not None:
                self._auto_save_debouncer.cancel()
            self._presenter.on_load_clicked()

    def _current_slot_id(self) -> str:
        """Slot-id текущего выбора (для slot_getter в RecipeAutoSave)."""
        if self._slot_combo_model is None:
            return ""
        return self._slot_combo_model.current_slot_id()

    def _capture_snapshot(self) -> dict[str, Any]:
        """Снимок регистров для записи (для rm_snapshot_fn в RecipeAutoSave)."""
        if self._model is None:
            return {}
        rm = self._model.rm
        if rm is None or not hasattr(rm, "model_dump_all"):
            return {}
        return rm.model_dump_all()

    def closeEvent(self, event: Any) -> None:  # noqa: N802 — Qt API naming
        """Отменить pending auto-save при закрытии виджета."""
        if self._auto_save_debouncer is not None:
            self._auto_save_debouncer.cancel()
        if self._auto_save is not None:
            self._auto_save.cancel()
        super().closeEvent(event)

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
        """Редактирование колонки «значение» → презентер + auto-save (Task 1.4)."""
        if self._block_table or self._tree is None:
            return
        if column_key != "value":
            return
        self._presenter.on_leaf_value_changed(group_id, field_id, column_key, str(value))
        if self._auto_save_debouncer is not None and self._auto_save is not None:
            self._auto_save_debouncer.schedule(
                delay_ms=_DEFAULT_AUTOSAVE_DEBOUNCE_MS,
                callback=self._auto_save.flush,
            )
