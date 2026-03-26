# multiprocess_prototype/frontend/widgets/recipes_widget/panel_widget.py
"""Панель рецептов регистров: BaseWidget + MVP."""

from __future__ import annotations

from typing import Any, Callable, Optional, Union

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
from frontend_module.interfaces import IRegistersManagerGui
from frontend_module.widgets.base_widget import BaseWidget
from frontend_module.widgets.tables.structured_two_level_tree import StructuredTwoLevelTreeWidget
from frontend_module.widgets.tabs import callback_no_args

from multiprocess_prototype.frontend.coordinators import parse_clamped_recipe_slot_text
from multiprocess_prototype.frontend.touch_keyboard_bind import (
    bind_touch_keyboard_line_edit,
    merge_touch_keyboard_dicts,
)
from multiprocess_prototype.managers.access_context import AccessContext
from multiprocess_prototype.managers.recipe_manager_protocol import RecipeManagerProtocol

from ..settings_recipe_widget.schemas import RecipesTabConfig
from .model import RegisterRecipeModel
from .presenter import RegisterRecipePresenter
from .recipe_rows import group_rows_by_register


class RegisterRecipePanelWidget(BaseWidget[RegisterRecipeModel]):
    """Слот, загрузка/сохранение рецепта регистров, таблица полей."""

    load_requested = pyqtSignal(int)
    save_requested = pyqtSignal(int)
    default_requested = pyqtSignal()

    def __init__(
        self,
        *,
        registers_manager: Optional[IRegistersManagerGui] = None,
        rm: Optional[IRegistersManagerGui] = None,
        ui: Optional[Union[RecipesTabConfig, dict]] = None,
        recipe_manager: Optional[RecipeManagerProtocol] = None,
        recipe_access: Optional[Union[AccessContext, dict]] = None,
        on_recipe_applied: Optional[Callable[[int], None]] = None,
        on_recipe_saved: Optional[Callable[[int], None]] = None,
        touch_keyboard: Any | None = None,
        parent: Optional[Any] = None,
    ) -> None:
        """Требуется rm/registers_manager; опционально recipe_manager и колбэки после load/save."""
        resolved = rm if rm is not None else registers_manager
        if resolved is None:
            raise TypeError("RegisterRecipePanelWidget requires rm or registers_manager")
        self._touch_keyboard = touch_keyboard
        self._extra_recipe_manager = recipe_manager
        self._extra_access_ctx = (
            recipe_access
            if isinstance(recipe_access, AccessContext)
            else AccessContext.from_dict(recipe_access if isinstance(recipe_access, dict) else None)
        )
        self._on_recipe_applied_cb = on_recipe_applied
        self._on_recipe_saved_cb = on_recipe_saved
        super().__init__(registers_manager=resolved, ui=ui, parent=parent)

    def _coerce_ui(self, ui: Optional[object]) -> RecipesTabConfig:
        """Привести ui к RecipesTabConfig."""
        return coerce_schema_config(ui, RecipesTabConfig)

    def _create_model(self) -> RegisterRecipeModel:
        """Модель: RegistersManager + доступ к recipe_manager и колбэкам."""
        assert self._registers_manager is not None
        return RegisterRecipeModel(
            rm=self._registers_manager,
            recipe_manager=self._extra_recipe_manager,
            access_ctx=self._extra_access_ctx,
            ui=self._ui,
            on_recipe_applied=self._on_recipe_applied_cb,
            on_recipe_saved=self._on_recipe_saved_cb,
        )

    def _init_ui(self) -> None:
        """QGroupBox со слотом и кнопками; таблица полей регистров."""
        m = self._model
        assert m is not None
        u = self._ui
        tk_slot = merge_touch_keyboard_dicts(self._touch_keyboard, getattr(u, "touch_keyboard_slot", None))
        tk_tree = merge_touch_keyboard_dicts(self._touch_keyboard, getattr(u, "touch_keyboard_tree", None))
        layout = QVBoxLayout(self)

        # --- Блок: слот + Загрузить / Сохранить / По умолчанию (рецепт регистров) ---
        box = QGroupBox(u.group_register_box)
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

        # --- Блок: заголовок и дерево регистр → поля (параметр / значение / описание) ---
        layout.addWidget(QLabel(u.table_group_title))
        columns = [
            {"key": "param", "label": u.col_param, "type": "text", "editable": False},
            {"key": "value", "label": u.col_value, "type": "text", "editable": True},
            {"key": "info", "label": u.col_info, "type": "text", "editable": False},
        ]
        self._tree = StructuredTwoLevelTreeWidget(columns=columns, touch_keyboard=tk_tree)
        self._tree.set_row_key("field_id")
        self._block_table = False
        layout.addWidget(self._tree, 1)

    def _create_presenter(self, model: Optional[RegisterRecipeModel]) -> RegisterRecipePresenter:
        """Презентер с view=self."""
        assert model is not None
        return RegisterRecipePresenter(view=self, model=model)

    def _connect_signals(self) -> None:
        """Кнопки и itemChanged таблицы (аналогично AppRecipePanel)."""
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
        """load в регистры + pyqtSignal load_requested."""
        self._presenter.on_load_clicked()
        self.load_requested.emit(self.parse_slot())

    def _on_save_with_signal(self) -> None:
        """save из регистров + save_requested."""
        idx = self.parse_slot()
        self._presenter.on_save_clicked()
        self.save_requested.emit(idx)

    def _on_default_with_signal(self) -> None:
        """Загрузка слота 0 (заводской пресет) + default_requested."""
        self._presenter.on_default_clicked()
        self.default_requested.emit()

    def _on_presenter_ready(self, **kwargs: Any) -> None:
        """После инициализации — таблица из текущих регистров."""
        self._presenter.refresh_from_registers()

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
        """set_data из build_rows презентера с блокировкой сигналов."""
        if self._tree is None or self._model is None:
            return
        p = self._presenter
        rows = p.build_rows()
        groups = group_rows_by_register(rows)
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
        """Изменение колонки значения → set_field_value через презентер."""
        if self._block_table or self._tree is None:
            return
        if column_key != "value":
            return
        self._presenter.on_leaf_value_changed(group_id, field_id, column_key, str(value))

    def refresh_from_registers(self) -> None:
        """Публичный вызов: обновить таблицу после внешней правки регистров."""
        self._presenter.refresh_from_registers()
