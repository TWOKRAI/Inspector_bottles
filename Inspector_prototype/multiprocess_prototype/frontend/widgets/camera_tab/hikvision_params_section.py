# multiprocess_prototype/frontend/widgets/camera_tab/hikvision_params_section.py
"""
Группа «Параметры камеры» (Hikvision): frame_rate, exposure, gain.

При наличии RegistersManager — три `NumericControl` (spinbox), спецификации из ``hikvision_spinbox_rows``.
Иначе — три пары QLabel + QLineEdit (ширина из ``hikvision_line_edit_max_width``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

from frontend_module.components.control_v2 import (
    BindingConfig,
    NumericControl,
    NumericViewConfig,
)
from frontend_module.core.qt_imports import QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from frontend_module.components.tabs import RegisterBindingContext
from multiprocess_prototype.registers.schemas.camera_tab import CAMERA_REGISTER

from .schemas import CameraTabUiConfig


@dataclass
class HikvisionParamsRefs:
    """Ссылки для чтения fallback-полей и синхронизации из `update_camera_parameters` (порядок = api map)."""

    line_edits: List[Optional[QLineEdit]]


def _labeled_line_row(
    label_text: str,
    placeholder: str,
    max_width: int,
) -> Tuple[QHBoxLayout, QLineEdit]:
    row = QHBoxLayout()
    row.addWidget(QLabel(label_text))
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    edit.setMaximumWidth(max_width)
    row.addWidget(edit)
    return row, edit


def build_hikvision_params_group(
    u: CameraTabUiConfig,
    binding: RegisterBindingContext,
    *,
    on_get_parameters: Callable[[], None],
    on_set_parameters_clicked: Callable[[], None],
) -> Tuple[QGroupBox, HikvisionParamsRefs]:
    """
    QGroupBox с полями параметров и кнопками Get / Set.

    `on_set_parameters_clicked` — обычно обёртка виджета: прочитать регистр или line edit,
    затем вызвать пользовательский `on_set_parameters`.
    """
    group = QGroupBox(u.group_params)
    layout = QVBoxLayout(group)

    line_edits: List[Optional[QLineEdit]] = []

    # С RegistersManager — NumericControl (spinbox); без — QLabel + QLineEdit
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
                u.spinbox_label_for_row(spec),
                ph,
                u.hikvision_line_edit_max_width,
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
