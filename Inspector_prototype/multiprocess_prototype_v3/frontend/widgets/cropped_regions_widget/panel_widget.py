# multiprocess_prototype_v3/frontend/widgets/cropped_regions_widget/panel_widget.py
"""ROI feature widget: BaseWidget + MVP."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from frontend_module.core.qt_imports import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTimer,
    QVBoxLayout,
)
from frontend_module.core.schema_config import coerce_schema_config
from frontend_module.interfaces import IRegistersManagerGui
from frontend_module.widgets.base_widget import BaseWidget
from frontend_module.widgets.tables.structured_two_level_tree import StructuredTwoLevelTreeWidget
from frontend_module.widgets.tabs import callback_no_args

from multiprocess_prototype_v3.frontend.touch_keyboard_bind import (
    bind_touch_keyboard_line_edit,
    merge_touch_keyboard_dicts,
)
from multiprocess_prototype_v3.registers.schemas.processing_tab.names import PROCESSOR_REGISTER

from .controls import CroppedAreaControls
from .model import CroppedRegionsModel
from .presenter import CroppedRegionsPresenter
from .schemas import CroppedRegionsTabUiConfig
from .tree_adapter import CroppedRegionsTreeAdapter

CroppedControlsFactory = Callable[..., Any]


class CroppedRegionsPanelWidget(BaseWidget[CroppedRegionsModel]):
    """Регионы по камерам; запись в processor.crop_regions (вложенный dict)."""

    def __init__(
        self,
        *,
        registers_manager: IRegistersManagerGui | None = None,
        ui: CroppedRegionsTabUiConfig | dict | None = None,
        controls_factory: CroppedControlsFactory | None = None,
        touch_keyboard: Any | None = None,
        camera_registry: Any | None = None,
        action_bus: Any | None = None,
        parent: Any | None = None,
    ) -> None:
        self._controls_factory = controls_factory
        self._rm_subscribe_cb = None
        self._touch_keyboard = touch_keyboard
        self._camera_registry = camera_registry
        self._action_bus = action_bus
        super().__init__(registers_manager=registers_manager, ui=ui, parent=parent)

    def _coerce_ui(self, ui: object | None) -> CroppedRegionsTabUiConfig:
        return coerce_schema_config(ui, CroppedRegionsTabUiConfig)

    def _create_model(self) -> CroppedRegionsModel:
        u = self._ui
        default_cam = u.camera_ids[0] if u.camera_ids else "default"
        return CroppedRegionsModel(
            registers_manager=self._registers_manager,
            ui=self._ui,
            selected_camera=default_cam,
            camera_registry=self._camera_registry,
        )

    def _init_ui(self) -> None:
        u = self._ui
        tk_tree = merge_touch_keyboard_dicts(
            self._touch_keyboard, getattr(u, "touch_keyboard_tree", None)
        )
        tk_roi = merge_touch_keyboard_dicts(
            self._touch_keyboard, getattr(u, "touch_keyboard_roi", None)
        )
        tk_name = merge_touch_keyboard_dicts(tk_roi, getattr(u, "touch_keyboard_name", None))
        layout = QVBoxLayout(self)

        box = QGroupBox(u.group_regions)
        box_layout = QVBoxLayout(box)

        box_layout.addWidget(QLabel(u.table_title))
        self._tree = self._create_tree(u, tk_tree)
        self._tree_adapter = CroppedRegionsTreeAdapter(self._tree)
        box_layout.addWidget(self._tree, 1)

        btn_row = QHBoxLayout()
        self._btn_add = QPushButton(u.btn_add)
        self._btn_remove = QPushButton(u.btn_remove)
        self._btn_save = QPushButton(u.btn_save)
        btn_row.addWidget(self._btn_add)
        btn_row.addWidget(self._btn_remove)
        btn_row.addWidget(self._btn_save)
        btn_row.addStretch(1)
        box_layout.addLayout(btn_row)

        layout.addWidget(box)

        roi_box = QGroupBox(u.group_roi_params)
        roi_layout = QVBoxLayout(roi_box)

        pick_row = QHBoxLayout()
        pick_row.addWidget(QLabel(u.label_region_pick))
        self._region_combo = QComboBox()
        self._region_combo.setMinimumWidth(200)
        pick_row.addWidget(self._region_combo, 1)
        roi_layout.addLayout(pick_row)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(u.label_region_name))
        self._region_name_edit = QLineEdit()
        self._region_name_edit.setPlaceholderText(u.placeholder_name)
        bind_touch_keyboard_line_edit(self, self._region_name_edit, tk_name)
        name_row.addWidget(self._region_name_edit, 1)
        roi_layout.addLayout(name_row)

        self._controls = self._build_controls(tk_roi)
        roi_layout.addWidget(self._controls)

        layout.addWidget(roi_box)

        self._rect_label = QLabel()
        self._rect_label.setStyleSheet("font-size: 11px; color: gray;")
        layout.addWidget(self._rect_label)

        hint = QLabel(u.hint_footer)
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 10px; color: gray;")
        layout.addWidget(hint)

        self._block_table = False

    def _create_tree(
        self, u: CroppedRegionsTabUiConfig, touch_keyboard: Any | None
    ) -> StructuredTwoLevelTreeWidget:
        columns = [
            {"key": "name", "label": u.col_name, "type": "text", "editable": True},
            {"key": "x", "label": u.col_x, "type": "text", "editable": True},
            {"key": "y", "label": u.col_y, "type": "text", "editable": True},
            {"key": "width", "label": u.col_width, "type": "text", "editable": True},
            {"key": "height", "label": u.col_height, "type": "text", "editable": True},
        ]
        tree = StructuredTwoLevelTreeWidget(columns=columns, touch_keyboard=touch_keyboard)
        tree.set_row_key("region_id")
        return tree

    def _build_controls(self, touch_keyboard: Any | None) -> Any:
        u = self._ui
        kwargs = dict(
            on_changed=self._on_params_changed_slot,
            ui=u,
            touch_keyboard=touch_keyboard,
            parent=self,
        )
        if self._controls_factory is None:
            return CroppedAreaControls(**kwargs)
        return self._controls_factory(**kwargs)

    def _create_presenter(self, model: CroppedRegionsModel | None) -> CroppedRegionsPresenter:
        assert model is not None
        return CroppedRegionsPresenter(view=self, model=model, action_bus=self._action_bus)

    def _connect_signals(self) -> None:
        _btn = callback_no_args
        self._btn_add.clicked.connect(_btn(self._on_add_clicked))
        self._btn_remove.clicked.connect(_btn(self._on_remove_clicked))
        self._btn_save.clicked.connect(_btn(self._on_save_clicked))
        self._tree.currentItemChanged.connect(self._on_tree_current_changed)
        self._tree.leaf_cell_changed.connect(self._on_leaf_cell_changed_slot)
        self._region_combo.currentIndexChanged.connect(self._on_region_combo_index_changed)

    def _on_tree_current_changed(self, current: Any, previous: Any) -> None:
        if self._block_table:
            return
        cam, reg = self._tree.get_selection()
        self._presenter.on_tree_selection(cam, reg)

    def _on_leaf_cell_changed_slot(
        self, group_id: str, row_id: str, column_key: str, value: Any
    ) -> None:
        if self._block_table:
            return
        self._presenter.on_leaf_cell_changed(group_id, row_id, column_key, value)

    def _on_presenter_ready(self, **kwargs: Any) -> None:
        self._presenter.load_from_register()
        self._presenter.refresh_rect_label()
        self._attach_processor_subscribe()

    def _attach_processor_subscribe(self) -> None:
        rm = self._registers_manager
        if rm is None or self._rm_subscribe_cb is not None:
            return

        def _cb(register_name: str, field_name: str, value: Any) -> None:
            if register_name != PROCESSOR_REGISTER:
                return
            QTimer.singleShot(0, self._defer_reload_from_processor_register)

        self._rm_subscribe_cb = _cb
        rm.subscribe_all(_cb)

    def _defer_reload_from_processor_register(self) -> None:
        if self._presenter is None:
            return
        self._presenter.load_from_register()
        self._presenter.refresh_rect_label()

    def closeEvent(self, event: Any) -> None:
        rm = self._registers_manager
        if rm is not None and self._rm_subscribe_cb is not None:
            try:
                rm.unsubscribe_all(self._rm_subscribe_cb)
            except Exception:
                pass
            self._rm_subscribe_cb = None
        super().closeEvent(event)

    def _on_params_changed_slot(self) -> None:
        if self._block_table:
            return
        self._presenter.on_params_changed()

    def _on_region_combo_index_changed(self, index: int) -> None:
        if self._block_table:
            return
        if index < 0 or self._region_combo is None:
            return
        name = self._region_combo.itemText(index)
        if name:
            self._presenter.on_region_combo_selected(name)

    def _on_add_clicked(self) -> None:
        self._presenter.on_add()

    def _on_remove_clicked(self) -> None:
        self._presenter.on_remove()

    def _on_save_clicked(self) -> None:
        self._presenter.on_save_to_region()

    @property
    def ui(self) -> CroppedRegionsTabUiConfig:
        return self._ui

    def show_warning(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)

    def show_information(self, title: str, text: str) -> None:
        QMessageBox.information(self, title, text)

    def set_camera_options(self, camera_ids: list[str], selected: str) -> None:
        """Дерево строится из данных; слот сохранён для совместимости."""

    def set_region_combo_options(self, names: list[str], selected: str | None) -> None:
        if self._region_combo is None:
            return
        self._block_table = True
        self._region_combo.blockSignals(True)
        self._region_combo.clear()
        self._region_combo.addItems(names)
        if selected and selected in names:
            self._region_combo.setCurrentIndex(names.index(selected))
        else:
            self._region_combo.setCurrentIndex(-1)
        self._region_combo.blockSignals(False)
        self._block_table = False

    def get_region_combo_selection(self) -> str | None:
        if self._region_combo is None:
            return None
        i = self._region_combo.currentIndex()
        if i < 0:
            return None
        return self._region_combo.itemText(i)

    def refresh_table(self) -> None:
        if self._model is None or self._tree_adapter is None or self._tree is None:
            return
        cam, reg = self._tree.get_selection()
        ids = self._presenter.camera_ids_union()
        for cid in ids:
            self._model.crop_regions_by_camera.setdefault(cid, {})
        self._block_table = True
        self._tree.blockSignals(True)
        self._tree_adapter.refresh(self._model.crop_regions_by_camera, ids)
        if reg and cam:
            self._tree.select_leaf(cam, reg)
        elif cam:
            self._tree.select_group(cam)
        self._tree.blockSignals(False)
        self._block_table = False

    def get_tree_selection(self) -> tuple[str | None, str | None]:
        if self._tree is None:
            return (None, None)
        return self._tree.get_selection()

    def read_leaf_row(self, camera_id: str, region_name: str) -> dict[str, Any] | None:
        if self._tree_adapter is None:
            return None
        return self._tree_adapter.read_leaf_row(camera_id, region_name)

    def selected_region_key(self) -> str | None:
        _, r = self.get_tree_selection()
        return r

    def select_region(self, camera_id: str, region_name: str) -> None:
        if self._tree is None:
            return
        self._block_table = True
        self._tree.select_leaf(camera_id, region_name)
        self._block_table = False

    def clear_table_selection(self) -> None:
        if self._tree is None:
            return
        self._tree.clear_selection_only()

    def get_region_name_text(self) -> str:
        return self._region_name_edit.text().strip() if self._region_name_edit else ""

    def set_region_name_text(self, text: str) -> None:
        if self._region_name_edit is not None:
            self._region_name_edit.setText(text)

    def apply_controls_params(self, params: dict[str, Any]) -> None:
        if self._controls is not None:
            self._controls.apply_params(params)

    def get_controls_params(self) -> dict[str, Any]:
        if self._controls is None:
            return {}
        return self._controls.get_params()

    def set_rect_label_text(self, text: str) -> None:
        if self._rect_label is not None:
            self._rect_label.setText(text)
