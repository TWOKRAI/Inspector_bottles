# multiprocess_prototype/frontend/widgets/hikvision_widget/params_section.py
"""Секция параметров Hikvision: NumericControl или QLineEdit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from frontend_module.components.control_v2 import (
    BindingConfig,
    NumericControl,
    NumericViewConfig,
)
from frontend_module.components.tabs import RegisterBindingContext
from frontend_module.core.qt_imports import QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from multiprocess_prototype.registers.schemas.camera_tab import CAMERA_REGISTER

from .schemas import HikvisionUiConfig


@dataclass
class HikvisionParamsRefs:
    """Ссылки на line edits (fallback) или None при bind."""

    line_edits: List[Optional[QLineEdit]]


def _labeled_line_row(
    label_text: str, placeholder: str, max_width: int
) -> Tuple[QHBoxLayout, QLineEdit]:
    row = QHBoxLayout()
    row.addWidget(QLabel(label_text))
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    edit.setMaximumWidth(max_width)
    row.addWidget(edit)
    return row, edit


def build_params_group(
    u: HikvisionUiConfig,
    binding: RegisterBindingContext,
    *,
    on_get_parameters: Callable[[], None],
    on_set_parameters_clicked: Callable[[], None],
) -> Tuple[QGroupBox, HikvisionParamsRefs]:
    """QGroupBox с полями параметров и кнопками Get/Set."""
    group = QGroupBox(u.group_params)
    layout = QVBoxLayout(group)
    line_edits: List[Optional[QLineEdit]] = []

    if binding.can_bind and binding.rm is not None:
        for spec in u.hikvision_spinbox_rows:
            label = u.spinbox_label_for_row(spec)
            result = NumericControl.create(
                binding.rm,
                BindingConfig(CAMERA_REGISTER, spec.register_field),
                NumericViewConfig(
                    view_type="spinbox",
                    label=label,
                    min_val=spec.min_val,
                    max_val=spec.max_val,
                ),
            )
            layout.addWidget(result.widget)
        line_edits = [None] * len(u.hikvision_spinbox_rows)
    else:
        placeholders = (u.placeholder_fps, u.placeholder_exposure, u.placeholder_gain)
        for spec, ph in zip(u.hikvision_spinbox_rows, placeholders):
            row, edit = _labeled_line_row(
                u.spinbox_label_for_row(spec), ph, u.hikvision_line_edit_max_width
            )
            layout.addLayout(row)
            line_edits.append(edit)

    row_btns = QHBoxLayout()
    btn_get = QPushButton(u.btn_get_parameters)
    btn_get.clicked.connect(on_get_parameters)
    btn_set = QPushButton(u.btn_set_parameters)
    btn_set.clicked.connect(on_set_parameters_clicked)
    row_btns.addWidget(btn_get)
    row_btns.addWidget(btn_set)
    layout.addLayout(row_btns)

    return group, HikvisionParamsRefs(line_edits=line_edits)
