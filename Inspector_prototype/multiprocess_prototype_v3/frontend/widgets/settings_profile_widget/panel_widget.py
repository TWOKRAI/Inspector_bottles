# multiprocess_prototype_v3/frontend/widgets/settings_profile_widget/panel_widget.py
"""Панель профилей настроек приложения: SettingsProfilePanelWidget (Phase 2, Task 2.4)."""

from __future__ import annotations

from typing import Any

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

from .model import SettingsProfileModel
from .presenter import SettingsProfilePresenter
from .profile_combo_model import from_profile_manager, sync_current
from .schemas import SettingsProfileTabConfig


class SettingsProfilePanelWidget(BaseWidget[SettingsProfileModel]):
    """Панель профилей настроек: ComboBox + кнопки + таблица параметров приложения."""

    # Сигнал: profile_id после успешного switch
    profile_changed = pyqtSignal(str)

    def __init__(
        self,
        *,
        profile_manager: Any | None = None,
        registers_manager: Any | None = None,
        ui: Any | None = None,
        touch_keyboard: Any | None = None,
        action_bus: Any | None = None,
        parent: Any | None = None,
    ) -> None:
        # Сохраняем до вызова super().__init__ — он вызывает lifecycle-методы
        self._profile_manager = profile_manager
        self._touch_keyboard = touch_keyboard
        self._action_bus = action_bus
        super().__init__(registers_manager=registers_manager, ui=ui, parent=parent)

    # ------------------------------------------------------------------
    # BaseWidget lifecycle
    # ------------------------------------------------------------------

    def _coerce_ui(self, ui: object | None) -> SettingsProfileTabConfig:
        """Привести ui к SettingsProfileTabConfig."""
        return coerce_schema_config(ui, SettingsProfileTabConfig)

    def _create_model(self) -> SettingsProfileModel:
        """Собрать модель: combo_model из profile_manager + sync current."""
        combo_model = from_profile_manager(self._profile_manager)
        sync_current(combo_model, self._profile_manager)
        return SettingsProfileModel(
            ui=self._ui,
            profile_manager=self._profile_manager,
            rm=self._registers_manager,
            combo_model=combo_model,
        )

    def _init_ui(self) -> None:
        """QGroupBox с ComboBox и кнопками + заголовок + StructuredTwoLevelTreeWidget."""
        assert self._model is not None
        u = self._ui
        m = self._model

        layout = QVBoxLayout(self)

        # --- Блок: метка + ComboBox + кнопки ---
        box = QGroupBox(u.group_box_title)
        ctrl = QHBoxLayout(box)
        ctrl.addWidget(QLabel(u.label_profile))

        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(120)
        self._profile_combo.addItems(m.combo_model.labels)
        self._profile_combo.setCurrentIndex(m.combo_model.current_index)
        ctrl.addWidget(self._profile_combo)

        self._btn_apply = QPushButton(u.btn_apply)
        self._btn_save = QPushButton(u.btn_save)
        self._btn_default = QPushButton(u.btn_default)
        ctrl.addWidget(self._btn_apply)
        ctrl.addWidget(self._btn_save)
        ctrl.addWidget(self._btn_default)
        ctrl.addStretch()
        layout.addWidget(box)

        # --- Блок: заголовок и дерево (параметр / значение / описание) ---
        layout.addWidget(QLabel(u.table_title))
        columns = [
            {"key": "param", "label": u.col_param, "type": "text", "editable": False},
            {"key": "value", "label": u.col_value, "type": "text", "editable": True},
            {"key": "info", "label": u.col_info, "type": "text", "editable": False},
        ]
        self._tree = StructuredTwoLevelTreeWidget(
            columns=columns, touch_keyboard=self._touch_keyboard
        )
        self._tree.set_row_key("field_id")
        self._block_table = False
        layout.addWidget(self._tree, 1)

    def _create_presenter(self, model: SettingsProfileModel | None) -> SettingsProfilePresenter:
        assert model is not None
        return SettingsProfilePresenter(view=self, model=model, action_bus=self._action_bus)

    def _connect_signals(self) -> None:
        """Кнопки → presenter; изменение ячейки → presenter; смена профиля → model."""
        _btn = callback_no_args
        self._btn_apply.clicked.connect(_btn(self._on_apply_with_signal))
        self._btn_save.clicked.connect(_btn(self._presenter.on_save_clicked))
        self._btn_default.clicked.connect(_btn(self._on_default_with_signal))
        self._tree.leaf_cell_changed.connect(self._on_leaf_value_changed_slot)
        self._profile_combo.currentIndexChanged.connect(self._on_profile_index_changed)

    def _on_presenter_ready(self, **kwargs: Any) -> None:
        """Инициализировать таблицу после подключения сигналов."""
        self.refresh_table_rows()

    # ------------------------------------------------------------------
    # SettingsProfilePanelViewProtocol
    # ------------------------------------------------------------------

    def current_profile_id(self) -> str:
        """Profile-id из текущего выбора ComboBox."""
        combo_idx = self._profile_combo.currentIndex()
        return self._model.combo_model.slot_id_for_index(combo_idx)

    def refresh_table_rows(self) -> None:
        """Перезаполнить дерево с блокировкой сигналов."""
        if self._tree is None:
            return
        groups = self._presenter.build_tree_groups()
        self._block_table = True
        self._tree.blockSignals(True)
        self._tree.set_data(groups)
        self._tree.blockSignals(False)
        self._block_table = False

    def set_leaf_value_text(self, group_id: str, field_id: str, text: str) -> None:
        """Установить текст ячейки value у листа дерева."""
        if self._tree is not None:
            self._tree.set_leaf_cell_text(group_id, field_id, "value", text)

    def show_error(self, message: str) -> None:
        """Показать диалог с сообщением об ошибке."""
        from frontend_module.core.qt_imports import QMessageBox  # lazy import

        QMessageBox.warning(self, "Ошибка профиля", message)

    # ------------------------------------------------------------------
    # Внутренние слоты
    # ------------------------------------------------------------------

    def _on_apply_with_signal(self) -> None:
        """Применить профиль через presenter; при успехе — испустить profile_changed."""
        ok = self._presenter.on_apply_clicked()
        if ok:
            self.profile_changed.emit(self.current_profile_id())

    def _on_default_with_signal(self) -> None:
        """Применить 'default' через presenter; при успехе — испустить profile_changed."""
        ok = self._presenter.on_default_clicked()
        if ok:
            self.profile_changed.emit("default")

    def _on_profile_index_changed(self, index: int) -> None:
        """Синхронизировать current_index модели с ComboBox (без auto-apply)."""
        if self._model is not None:
            self._model.combo_model.current_index = index

    def _on_leaf_value_changed_slot(
        self, group_id: str, field_id: str, column_key: str, value: Any
    ) -> None:
        """Редактирование ячейки → presenter."""
        if self._block_table:
            return
        self._presenter.on_leaf_value_changed(group_id, field_id, column_key, str(value))


__all__ = ["SettingsProfilePanelWidget"]
