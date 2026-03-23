# multiprocess_prototype/frontend/widgets/hikvision_widget/binder.py
"""Binder — привязки UI ↔ callbacks, presenter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from frontend_module.components.tabs import RegisterBindingContext, callback_no_args
from frontend_module.core.qt_imports import QComboBox, QGroupBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from .params_section import build_params_group
from .schemas import HikvisionUiConfig

if TYPE_CHECKING:
    from .callbacks import HikvisionWidgetCallbacks
    from .presenter import HikvisionPresenter


def bind_hikvision_ui(
    u: HikvisionUiConfig,
    binding: RegisterBindingContext,
    callbacks: "HikvisionWidgetCallbacks",
    presenter: "HikvisionPresenter",
) -> tuple[QWidget, object]:
    """Собрать UI и привязать сигналы. Returns (page, refs с combo_devices, hik_params)."""
    _btn = callback_no_args
    page = QWidget()
    layout = QVBoxLayout(page)

    dev_group = QGroupBox(u.group_device)
    dev_layout = QVBoxLayout(dev_group)
    combo_devices = QComboBox()
    combo_devices.addItem(u.device_combo_placeholder)
    dev_layout.addWidget(combo_devices)
    btn_enum = QPushButton(u.btn_enum_devices)
    btn_enum.clicked.connect(_btn(callbacks.on_enum_devices))
    dev_layout.addWidget(btn_enum)
    row_open = QHBoxLayout()
    btn_open = QPushButton(u.btn_open)
    btn_open.clicked.connect(presenter.on_open)
    btn_close = QPushButton(u.btn_close)
    btn_close.clicked.connect(_btn(callbacks.on_close))
    row_open.addWidget(btn_open)
    row_open.addWidget(btn_close)
    dev_layout.addLayout(row_open)
    layout.addWidget(dev_group)

    grab_group = QGroupBox(u.group_grabbing)
    grab_layout = QVBoxLayout(grab_group)
    btn_start_grabbing = QPushButton(u.btn_start_grabbing)
    btn_start_grabbing.clicked.connect(presenter.on_start_grabbing)
    btn_stop_grabbing = QPushButton(u.btn_stop_grabbing)
    btn_stop_grabbing.clicked.connect(_btn(callbacks.on_stop_grabbing))
    grab_layout.addWidget(btn_start_grabbing)
    grab_layout.addWidget(btn_stop_grabbing)
    layout.addWidget(grab_group)

    params_group, hik_params = build_params_group(
        u,
        binding,
        on_get_parameters=_btn(callbacks.on_get_parameters),
        on_set_parameters_clicked=presenter.on_set_parameters_clicked,
    )
    layout.addWidget(params_group)

    refs = type("Refs", (), {"combo_devices": combo_devices, "hik_params": hik_params})()
    return page, refs
