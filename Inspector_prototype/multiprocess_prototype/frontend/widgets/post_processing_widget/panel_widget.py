# multiprocess_prototype/frontend/widgets/post_processing_widget/panel_widget.py
"""Постобработка: BaseWidget + TwoLevelTreeWithToolbar + форма региона."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

from frontend_module.core.qt_imports import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTimer,
    QVBoxLayout,
)
from frontend_module.core.schema_config import coerce_schema_config
from frontend_module.interfaces import IRegistersManagerGui
from frontend_module.widgets.base_widget import BaseWidget
from frontend_module.widgets.tables.tree_with_toolbar import TwoLevelTreeWithToolbar
from frontend_module.widgets.tabs import callback_no_args

from .model import PostProcessingModel
from .params import regions_to_table_rows
from .presenter import PostProcessingPresenter
from .schemas import PostProcessingTabUiConfig

from multiprocess_prototype.frontend.touch_keyboard_bind import (
    bind_touch_keyboard_line_edit,
    merge_touch_keyboard_dicts,
)
from multiprocess_prototype.registers.schemas.processing_tab.names import PROCESSOR_REGISTER


class PostProcessingPanelWidget(BaseWidget[PostProcessingModel]):
    """Регионы постобработки по камерам; запись в processor.post_processing_regions."""

    def __init__(
        self,
        *,
        registers_manager: Optional[IRegistersManagerGui] = None,
        ui: Optional[Union[PostProcessingTabUiConfig, dict]] = None,
        touch_keyboard: Any | None = None,
        parent: Optional[Any] = None,
    ) -> None:
        self._rm_subscribe_cb = None
        self._touch_keyboard = touch_keyboard
        super().__init__(registers_manager=registers_manager, ui=ui, parent=parent)

    def _coerce_ui(self, ui: Optional[object]) -> PostProcessingTabUiConfig:
        return coerce_schema_config(ui, PostProcessingTabUiConfig)

    def _create_model(self) -> PostProcessingModel:
        u = self._ui
        default_cam = u.camera_ids[0] if u.camera_ids else "default"
        return PostProcessingModel(
            registers_manager=self._registers_manager,
            ui=self._ui,
            selected_camera=default_cam,
        )

    def _init_ui(self) -> None:
        u = self._ui
        tk_tree = merge_touch_keyboard_dicts(self._touch_keyboard, getattr(u, "touch_keyboard_tree", None))
        tk_form = merge_touch_keyboard_dicts(self._touch_keyboard, getattr(u, "touch_keyboard_form", None))
        layout = QVBoxLayout(self)

        regions_box = QGroupBox(u.group_regions)
        regions_layout = QVBoxLayout(regions_box)

        columns = [
            {"key": "name", "label": u.col_name, "type": "text", "editable": False},
            {"key": "enabled", "label": u.col_enabled, "type": "checkbox"},
            {"key": "is_main", "label": u.col_is_main, "type": "checkbox"},
            {"key": "processing_enabled", "label": u.col_processing, "type": "checkbox"},
            {"key": "coords", "label": u.col_coords, "type": "text", "editable": False},
        ]
        self._regions_tree = TwoLevelTreeWithToolbar(
            columns=columns,
            parent=self,
            show_add_delete=True,
            show_move=True,
            show_copy_paste=True,
            touch_keyboard=tk_tree,
        )
        self._regions_tree.set_row_key("region_id")
        regions_layout.addWidget(self._regions_tree)

        view_btns = QHBoxLayout()
        view_btns.setSpacing(30)
        self._btn_show = QPushButton(u.btn_show)
        self._btn_show.setMinimumHeight(60)
        self._btn_show.setMinimumWidth(200)
        self._btn_back = QPushButton(u.btn_back_main)
        self._btn_back.setMinimumHeight(60)
        self._btn_back.setMinimumWidth(200)
        view_btns.addWidget(self._btn_show, 1)
        view_btns.addWidget(self._btn_back, 1)
        view_btns.addStretch()
        regions_layout.addLayout(view_btns)

        layout.addWidget(regions_box)

        edit_box = QGroupBox(u.group_edit)
        edit_layout = QGridLayout(edit_box)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(u.placeholder_name)
        bind_touch_keyboard_line_edit(self, self._name_edit, tk_form)
        r = 0
        edit_layout.addWidget(QLabel("Имя:"), r, 0)
        edit_layout.addWidget(self._name_edit, r, 1)
        r += 1

        self._x1 = QSpinBox()
        self._x1.setRange(0, 100000)
        self._y1 = QSpinBox()
        self._y1.setRange(0, 100000)
        self._x2 = QSpinBox()
        self._x2.setRange(0, 100000)
        self._y2 = QSpinBox()
        self._y2.setRange(0, 100000)
        for lab, w in (("x1:", self._x1), ("y1:", self._y1), ("x2:", self._x2), ("y2:", self._y2)):
            edit_layout.addWidget(QLabel(lab), r, 0)
            edit_layout.addWidget(w, r, 1)
            le = w.lineEdit()
            if le is not None:
                bind_touch_keyboard_line_edit(self, le, tk_form)
            r += 1

        self._chk_enabled = QCheckBox("Включен")
        self._chk_is_main = QCheckBox("Основное изображение")
        self._chk_processing = QCheckBox("Включить обработку")
        edit_layout.addWidget(self._chk_enabled, r, 0, 1, 2)
        r += 1
        edit_layout.addWidget(self._chk_is_main, r, 0, 1, 2)
        r += 1
        edit_layout.addWidget(self._chk_processing, r, 0, 1, 2)

        layout.addWidget(edit_box)

        hint = QLabel(u.hint_footer)
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 10px; color: gray;")
        layout.addWidget(hint)

        self._block_table = False
        self._block_form = False

    def _create_presenter(self, model: Optional[PostProcessingModel]) -> PostProcessingPresenter:
        assert model is not None
        return PostProcessingPresenter(view=self, model=model)

    def _connect_signals(self) -> None:
        _btn = callback_no_args
        tr = self._regions_tree.tree
        tr.currentItemChanged.connect(self._on_tree_current_changed)
        tr.leaf_cell_changed.connect(self._on_leaf_cell_changed_slot)
        self._regions_tree.add_clicked.connect(_btn(self._presenter.on_add))
        self._regions_tree.delete_clicked.connect(_btn(self._presenter.on_remove))
        self._regions_tree.move_up_clicked.connect(lambda: self._presenter.on_move(-1))
        self._regions_tree.move_down_clicked.connect(lambda: self._presenter.on_move(1))
        self._regions_tree.copy_clicked.connect(_btn(self._presenter.on_copy))
        self._regions_tree.paste_clicked.connect(_btn(self._presenter.on_paste))
        self._btn_show.clicked.connect(_btn(self._presenter.on_show_region_stub))
        self._btn_back.clicked.connect(_btn(self._presenter.on_back_to_main_stub))

        self._name_edit.editingFinished.connect(self._on_form_slot)
        self._x1.valueChanged.connect(self._on_form_slot)
        self._y1.valueChanged.connect(self._on_form_slot)
        self._x2.valueChanged.connect(self._on_form_slot)
        self._y2.valueChanged.connect(self._on_form_slot)
        self._chk_enabled.stateChanged.connect(self._on_form_slot)
        self._chk_is_main.stateChanged.connect(self._on_form_slot)
        self._chk_processing.stateChanged.connect(self._on_form_slot)

    def _on_tree_current_changed(self, current: Any, previous: Any) -> None:
        if self._block_table:
            return
        cam, reg = self._regions_tree.tree.get_selection()
        self._presenter.on_tree_selection(cam, reg)

    def _on_leaf_cell_changed_slot(
        self, group_id: str, row_id: str, column_key: str, value: object
    ) -> None:
        if self._block_table:
            return
        self._presenter.on_leaf_cell_changed(group_id, row_id, column_key, value)

    def _on_presenter_ready(self, **kwargs: Any) -> None:
        self._presenter.load_from_register()
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

    def closeEvent(self, event: Any) -> None:
        rm = self._registers_manager
        if rm is not None and self._rm_subscribe_cb is not None:
            try:
                rm.unsubscribe_all(self._rm_subscribe_cb)
            except Exception:
                pass
            self._rm_subscribe_cb = None
        super().closeEvent(event)

    def _on_form_slot(self) -> None:
        if self._block_form:
            return
        self._presenter.on_form_apply()

    @property
    def ui(self) -> PostProcessingTabUiConfig:
        return self._ui

    def show_warning(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)

    def show_information(self, title: str, text: str) -> None:
        QMessageBox.information(self, title, text)

    def confirm_delete(self, text: str) -> bool:
        reply = QMessageBox.question(
            self,
            self._ui.group_regions,
            text,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def get_tree_selection(self) -> Tuple[Optional[str], Optional[str]]:
        return self._regions_tree.tree.get_selection()

    def select_region(self, camera_id: str, region_name: str) -> None:
        self._block_table = True
        self._regions_tree.tree.select_leaf(camera_id, region_name)
        self._block_table = False

    def refresh_table(self) -> None:
        if self._model is None:
            return
        tr = self._regions_tree.tree
        cam, reg = tr.get_selection()
        ids = self._presenter.camera_ids_union()
        for cid in ids:
            self._model.post_regions_by_camera.setdefault(cid, [])
        self._block_table = True
        tr.blockSignals(True)
        groups: List[tuple[str, List[Dict[str, Any]]]] = []
        for cid in ids:
            regions = self._model.post_regions_by_camera.get(cid, [])
            groups.append((cid, regions_to_table_rows(regions)))
        tr.set_data(groups)
        if reg and cam:
            tr.select_leaf(cam, reg)
        elif cam:
            tr.select_group(cam)
        tr.blockSignals(False)
        self._block_table = False

    def apply_form_from_region(self, region: Optional[Dict[str, Any]]) -> None:
        self.block_form_signals(True)
        if not region:
            self._name_edit.clear()
            self._x1.setValue(0)
            self._y1.setValue(0)
            self._x2.setValue(0)
            self._y2.setValue(0)
            self._chk_enabled.setChecked(True)
            self._chk_is_main.setChecked(False)
            self._chk_processing.setChecked(True)
        else:
            self._name_edit.setText(str(region.get("name", "")))
            self._x1.setValue(int(region.get("x1", 0)))
            self._y1.setValue(int(region.get("y1", 0)))
            self._x2.setValue(int(region.get("x2", 0)))
            self._y2.setValue(int(region.get("y2", 0)))
            self._chk_enabled.setChecked(bool(region.get("enabled", True)))
            self._chk_is_main.setChecked(bool(region.get("is_main", False)))
            self._chk_processing.setChecked(bool(region.get("processing_enabled", True)))
        self.block_form_signals(False)

    def read_form_region(self) -> Dict[str, Any]:
        return {
            "name": self._name_edit.text().strip(),
            "x1": self._x1.value(),
            "y1": self._y1.value(),
            "x2": self._x2.value(),
            "y2": self._y2.value(),
            "enabled": self._chk_enabled.isChecked(),
            "is_main": self._chk_is_main.isChecked(),
            "processing_enabled": self._chk_processing.isChecked(),
        }

    def block_form_signals(self, block: bool) -> None:
        self._block_form = block
        self._name_edit.blockSignals(block)
        self._x1.blockSignals(block)
        self._y1.blockSignals(block)
        self._x2.blockSignals(block)
        self._y2.blockSignals(block)
        self._chk_enabled.blockSignals(block)
        self._chk_is_main.blockSignals(block)
        self._chk_processing.blockSignals(block)
