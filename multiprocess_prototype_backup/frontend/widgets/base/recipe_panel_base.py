# multiprocess_prototype/frontend/widgets/base/recipe_panel_base.py
"""Базовый класс для панелей рецептов: общий UI (слот + кнопки + дерево)."""

from __future__ import annotations

from typing import Any, TypeVar

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    Signal,
)
from multiprocess_framework.modules.frontend_module.core.schema_config import coerce_schema_config
from multiprocess_framework.modules.frontend_module.widgets.base_widget import BaseWidget
from multiprocess_framework.modules.frontend_module.widgets.tables.structured_two_level_tree import (
    StructuredTwoLevelTreeWidget,
)
from multiprocess_framework.modules.frontend_module.widgets.tabs import callback_no_args

from multiprocess_prototype.frontend.coordinators import parse_clamped_recipe_slot_text
from multiprocess_prototype.frontend.touch_keyboard_bind import merge_touch_keyboard_dicts

from ..recipes.recipes_widget.auto_save import AutoSaveConfig, QtDebounceAdapter, RecipeAutoSave
from ..recipes.recipes_widget.slot_combo_model import RecipeSlotComboModel
from ..recipes.settings_recipe_widget.schemas import RecipesTabConfig

_DEFAULT_AUTOSAVE_DEBOUNCE_MS = 1500

TModel = TypeVar("TModel")


class RecipePanelBase(BaseWidget[TModel]):
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

    PySide6 + abc.ABCMeta несовместимы (Shiboken metaclass ломает _abc_impl).
    Поэтому вместо @abstractmethod используется NotImplementedError —
    instantiation базового класса не блокируется, но вызов абстрактного метода
    падает с понятным сообщением. Подклассы обязаны переопределить методы ниже.
    """

    load_requested = Signal(int)
    save_requested = Signal(int)
    default_requested = Signal()

    # ------------------------------------------------------------------
    # Абстрактные методы — подкласс ОБЯЗАН реализовать
    # ------------------------------------------------------------------

    def _get_box_title(self) -> str:
        """Заголовок QGroupBox (слот + кнопки)."""
        raise NotImplementedError(f"{type(self).__name__}._get_box_title() must be implemented")

    def _get_table_title(self) -> str:
        """Подпись над деревом полей."""
        raise NotImplementedError(f"{type(self).__name__}._get_table_title() must be implemented")

    def _build_tree_data(self) -> list:
        """Построить данные для дерева (groups для set_data)."""
        raise NotImplementedError(f"{type(self).__name__}._build_tree_data() must be implemented")

    # ------------------------------------------------------------------
    # Общая реализация
    # ------------------------------------------------------------------

    def _coerce_ui(self, ui: object | None) -> RecipesTabConfig:
        """Привести ui к RecipesTabConfig."""
        return coerce_schema_config(ui, RecipesTabConfig)

    def _init_ui(self) -> None:
        """Создать виджеты и расположить в layout по умолчанию."""
        self._create_core_widgets()
        self._arrange_default_layout()

    def _create_core_widgets(self) -> None:
        """Создать все виджеты как self._* атрибуты (без добавления в layout).

        Подкласс может вызвать только _create_core_widgets() и расположить
        виджеты в собственном layout, минуя _arrange_default_layout().
        """
        m = self._model
        assert m is not None
        u = self._ui
        tk_tree = merge_touch_keyboard_dicts(
            self._touch_keyboard, getattr(u, "touch_keyboard_tree", None)
        )

        # --- Слот-модель ---
        self._slot_combo_model = RecipeSlotComboModel.from_manager(
            m.recipe_manager,
            u.recipe_index_min,
            u.recipe_index_max,
        )
        initial_slot = str(m.compute_initial_slot())
        self._slot_combo_model.current_index = self._slot_combo_model.index_for_slot_id(initial_slot)

        # --- Виджеты управления ---
        self._slot_combo = QComboBox()
        self._slot_combo.setMinimumWidth(96)
        self._slot_combo.addItems(self._slot_combo_model.labels)
        self._slot_combo.setCurrentIndex(self._slot_combo_model.current_index)
        self._btn_load = QPushButton(u.btn_load)
        self._btn_save = QPushButton(u.btn_save)
        self._btn_default = QPushButton(u.btn_default)

        # --- Auto-save с debounce + версионированием ---
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

        # --- Дерево (параметр / значение / описание) ---
        columns = [
            {"key": "param", "label": u.col_param, "type": "text", "editable": False},
            {"key": "value", "label": u.col_value, "type": "text", "editable": True},
            {"key": "info", "label": u.col_info, "type": "text", "editable": False},
        ]
        self._tree = StructuredTwoLevelTreeWidget(columns=columns, touch_keyboard=tk_tree)
        self._tree.set_row_key("field_id")
        self._block_table = False

    def _arrange_default_layout(self) -> None:
        """Расположить виджеты в layout по умолчанию: QGroupBox + дерево.

        Подкласс может переопределить для другого layout.
        """
        u = self._ui
        layout = QVBoxLayout(self)

        # --- Блок: слот (ComboBox) + Загрузить / Сохранить / По умолчанию ---
        box = QGroupBox(self._get_box_title())
        ctrl = QHBoxLayout(box)
        ctrl.addWidget(QLabel(u.label_slot))
        ctrl.addWidget(self._slot_combo)
        ctrl.addWidget(self._btn_load)
        ctrl.addWidget(self._btn_save)
        ctrl.addWidget(self._btn_default)
        ctrl.addStretch()
        layout.addWidget(box)

        # --- Заголовок + дерево ---
        layout.addWidget(QLabel(self._get_table_title()))
        layout.addWidget(self._tree, 1)

    def _connect_signals(self) -> None:
        """Кнопки → презентер и/или Signal; изменение ячейки → презентер."""
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
        """load через презентер + Signal load_requested."""
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

    def set_slot_index(self, slot_id: int) -> None:
        """Внешнее переключение слота — синхронизирует ComboBox.

        Меняет currentIndex в `_slot_combo`; через `currentIndexChanged` это
        триггерит `_on_slot_index_changed` → `presenter.on_load_clicked()`.
        Используется панелью кнопок-сортов вместо клика по ComboBox.
        """
        if self._slot_combo_model is None:
            return
        idx = self._slot_combo_model.index_for_slot_id(str(slot_id))
        if 0 <= idx < self._slot_combo.count():
            self._slot_combo.setCurrentIndex(idx)

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
        """Редактирование «значение» → презентер. Auto-save пропускается в preview."""
        if self._block_table or self._tree is None:
            return
        if column_key != "value":
            return
        self._presenter.on_leaf_value_changed(group_id, field_id, column_key, str(value))
        # Autosave пишет рецепт в YAML по таймеру — в preview-режиме это нежелательно
        # (там есть отдельные кнопки «Сохранить» и «Применить» с подтверждением).
        in_preview = bool(getattr(self._presenter, "is_preview_mode", lambda: False)())
        if in_preview:
            return
        if self._auto_save_debouncer is not None and self._auto_save is not None:
            self._auto_save_debouncer.schedule(
                delay_ms=_DEFAULT_AUTOSAVE_DEBOUNCE_MS,
                callback=self._auto_save.flush,
            )
