# multiprocess_prototype/frontend/widgets/hikvision_camera_mvp/view.py
"""Qt-view: разметка Hikvision MVP и методы для презентера."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from frontend_module.core.qt_imports import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from frontend_module.widgets.tabs import RegisterBindingContext
from frontend_module.widgets.tabs.numeric_bind_or_lineedit import (
    append_spinbox_numeric_or_line_fallback,
)

from multiprocess_prototype_v2.frontend.touch_keyboard_bind import merge_touch_keyboard_dicts
from multiprocess_prototype_v2.app_registers.camera_tab import (
    CAMERA_REGISTER,
    HikvisionParamRow,
)

from .schemas import HikvisionCameraMvpUiConfig

if TYPE_CHECKING:
    pass


def _parse_values_from_line_edits(
    rows: List[HikvisionParamRow],
    line_edits: List[Optional[QLineEdit]],
) -> Tuple[float, ...]:
    if len(line_edits) != len(rows):
        return tuple(r.default_value for r in rows)
    out: list[float] = []
    try:
        for row, ed in zip(rows, line_edits):
            if ed is None:
                out.append(row.default_value)
                continue
            text = ed.text().strip()
            if not text:
                out.append(float(row.default_value))
            else:
                out.append(float(text))
        return tuple(out)
    except (ValueError, TypeError):
        return tuple(r.default_value for r in rows)


def _apply_params_to_line_edits(
    rows: List[HikvisionParamRow],
    line_edits: List[Optional[QLineEdit]],
    params: Dict[str, Any],
) -> None:
    for row, ed in zip(rows, line_edits):
        if ed is None or row.api_key not in params:
            continue
        raw = float(params[row.api_key])
        ed.setText(format(raw, row.format_spec))


@dataclass
class HikvisionCameraMvpParamsRefs:
    """Ссылки на QLineEdit в режиме fallback (параллельно param_rows)."""

    rows: List[HikvisionParamRow]
    line_edits: List[Optional[QLineEdit]]


class HikvisionCameraMvpView(QWidget):
    """Виджеты вкладки Hikvision без привязки сигналов (делает HikvisionCameraMvpWidget)."""

    def __init__(
        self,
        parent: Optional[QWidget],
        *,
        registers_manager: Any,
        ui: HikvisionCameraMvpUiConfig,
        touch_keyboard_parent: Any,
        param_rows: List[HikvisionParamRow],
    ) -> None:
        super().__init__(parent)
        self._ui = ui
        self._param_rows = param_rows
        self._devices: list = []
        self._touch_keyboard_parent = touch_keyboard_parent

        binding = RegisterBindingContext(rm=registers_manager)
        page = QWidget()
        layout = QVBoxLayout(page)

        dev_group = QGroupBox(ui.group_device)
        dev_layout = QVBoxLayout(dev_group)
        hint = QLabel(ui.device_list_hint)
        hint.setWordWrap(True)
        dev_layout.addWidget(hint)
        self.list_devices = QListWidget()
        self.list_devices.setMinimumHeight(ui.device_list_min_height)
        self.list_devices.setSelectionMode(QAbstractItemView.SingleSelection)
        dev_layout.addWidget(self.list_devices)

        self.btn_enum = QPushButton(ui.btn_enum_devices)
        dev_layout.addWidget(self.btn_enum)
        row_open = QHBoxLayout()
        self.btn_open = QPushButton(ui.btn_open)
        self.btn_close = QPushButton(ui.btn_close)
        row_open.addWidget(self.btn_open)
        row_open.addWidget(self.btn_close)
        dev_layout.addLayout(row_open)
        layout.addWidget(dev_group)

        grab_group = QGroupBox(ui.group_grabbing)
        grab_layout = QVBoxLayout(grab_group)
        self.btn_start_grabbing = QPushButton(ui.btn_start_grabbing)
        self.btn_stop_grabbing = QPushButton(ui.btn_stop_grabbing)
        grab_layout.addWidget(self.btn_start_grabbing)
        grab_layout.addWidget(self.btn_stop_grabbing)
        layout.addWidget(grab_group)

        params_group, self._hik_params = self._build_params_group(binding, param_rows)
        layout.addWidget(params_group)

        root_layout = QVBoxLayout(self)
        root_layout.addWidget(page)

    def _build_params_group(
        self,
        binding: RegisterBindingContext,
        rows: List[HikvisionParamRow],
    ) -> tuple:
        u = self._ui
        group = QGroupBox(u.group_params)
        layout = QVBoxLayout(group)
        placeholders = tuple(r.placeholder for r in rows)
        tk = merge_touch_keyboard_dicts(
            self._touch_keyboard_parent,
            getattr(u, "touch_keyboard", None),
        )
        line_edits = append_spinbox_numeric_or_line_fallback(
            layout,
            binding=binding,
            register_name=CAMERA_REGISTER,
            row_specs=rows,
            label_for_row=lambda row: row.label,
            placeholders=placeholders,
            line_edit_max_width=u.hikvision_line_edit_max_width,
            touch_keyboard=tk,
            host_widget=group,
        )

        row_btns = QHBoxLayout()
        self.btn_get_parameters = QPushButton(u.btn_get_parameters)
        self.btn_set_parameters = QPushButton(u.btn_set_parameters)
        row_btns.addWidget(self.btn_get_parameters)
        row_btns.addWidget(self.btn_set_parameters)
        layout.addLayout(row_btns)

        return group, HikvisionCameraMvpParamsRefs(rows=rows, line_edits=line_edits)

    def set_devices_list(self, devices: list) -> None:
        self._devices = devices or []
        lst = self.list_devices
        lst.clear()
        for dev in self._devices:
            display = dev.get("display_name", f"[{dev.get('index', '?')}]")
            lst.addItem(display)
        if self._devices:
            lst.setCurrentRow(0)

    def set_hikvision_params_lines(self, params: dict) -> None:
        hp = self._hik_params
        if not hp:
            return
        _apply_params_to_line_edits(hp.rows, hp.line_edits, params)

    def get_params_from_lines(self) -> tuple[float, ...]:
        hp = self._hik_params
        if not hp:
            return tuple(r.default_value for r in self._param_rows)
        return _parse_values_from_line_edits(hp.rows, hp.line_edits)

    def show_error(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)

    def selected_camera_index(self) -> int:
        if not self._devices:
            return 0
        row = self.list_devices.currentRow()
        if row < 0 or row >= len(self._devices):
            return int(self._devices[0].get("index", 0))
        return int(self._devices[row].get("index", 0))
