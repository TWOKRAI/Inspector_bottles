# multiprocess_prototype/frontend/widgets/camera_tab/pages/hikvision.py
"""
Страница Hikvision: устройство, grabbing, параметры (spinbox или line edit).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from frontend_module.components.tabs import RegisterBindingContext
from frontend_module.core.qt_imports import QComboBox, QGroupBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ..hikvision_params_section import HikvisionParamsRefs, build_hikvision_params_group
from ..schemas import CameraTabUiConfig


@dataclass
class HikvisionPageRefs:
    """Виджеты для `update_camera_devices`, выбора индекса и fallback-синхронизации."""

    combo_devices: QComboBox
    hik_params: HikvisionParamsRefs
    btn_start_grabbing: QPushButton
    btn_stop_grabbing: QPushButton


def build_hikvision_page(
    u: CameraTabUiConfig,
    binding: RegisterBindingContext,
    *,
    on_enum_devices: Callable[[], None],
    on_open: Callable[[], None],
    on_close: Callable[[], None],
    on_start_grabbing: Callable[[], None],
    on_stop_grabbing: Callable[[], None],
    on_get_parameters: Callable[[], None],
    on_set_parameters_clicked: Callable[[], None],
) -> tuple[QWidget, HikvisionPageRefs]:
    """Страница Hikvision: устройство, Open/Close, Grabbing, параметры (spinbox или line edit)."""
    page = QWidget()
    layout = QVBoxLayout(page)

    dev_group = QGroupBox(u.group_device)
    dev_layout = QVBoxLayout(dev_group)
    combo_devices = QComboBox()
    combo_devices.addItem(u.device_combo_placeholder)
    dev_layout.addWidget(combo_devices)

    btn_enum = QPushButton(u.btn_enum_devices)
    btn_enum.clicked.connect(on_enum_devices)
    dev_layout.addWidget(btn_enum)

    row_open = QHBoxLayout()
    btn_open = QPushButton(u.btn_open)
    btn_open.clicked.connect(on_open)
    btn_close = QPushButton(u.btn_close)
    btn_close.clicked.connect(on_close)
    row_open.addWidget(btn_open)
    row_open.addWidget(btn_close)
    dev_layout.addLayout(row_open)
    layout.addWidget(dev_group)

    grab_group = QGroupBox(u.group_grabbing)
    grab_layout = QVBoxLayout(grab_group)
    btn_start_grabbing = QPushButton(u.btn_start_grabbing)
    btn_start_grabbing.clicked.connect(on_start_grabbing)
    btn_stop_grabbing = QPushButton(u.btn_stop_grabbing)
    btn_stop_grabbing.clicked.connect(on_stop_grabbing)
    grab_layout.addWidget(btn_start_grabbing)
    grab_layout.addWidget(btn_stop_grabbing)
    layout.addWidget(grab_group)

    params_group, hik_params = build_hikvision_params_group(
        u,
        binding,
        on_get_parameters=on_get_parameters,
        on_set_parameters_clicked=on_set_parameters_clicked,
    )
    layout.addWidget(params_group)

    refs = HikvisionPageRefs(
        combo_devices=combo_devices,
        hik_params=hik_params,
        btn_start_grabbing=btn_start_grabbing,
        btn_stop_grabbing=btn_stop_grabbing,
    )
    return page, refs
