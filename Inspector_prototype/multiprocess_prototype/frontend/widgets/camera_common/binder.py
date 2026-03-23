# multiprocess_prototype/frontend/widgets/camera_common/binder.py
"""Binder — UI ↔ callbacks, presenter, регистр."""

from __future__ import annotations

from typing import Optional

from frontend_module.components.tabs import RegisterBindingContext, callback_no_args
from frontend_module.core.qt_imports import QGroupBox, QPushButton, QVBoxLayout, QWidget

from .callbacks import SimWebcamWidgetCallbacks
from .fps_section import add_fps_section_to_layout
from .presenter import SimWebcamPresenter
from .schemas import SimWebcamUiConfig


def bind_sim_webcam_ui(
    u: SimWebcamUiConfig,
    binding: RegisterBindingContext,
    callbacks: SimWebcamWidgetCallbacks,
    presenter: SimWebcamPresenter,
) -> tuple[QWidget, Optional[object]]:
    """
    Собрать UI и привязать сигналы.

    Returns:
        (page_widget, fps_refs) — fps_refs для set_fps_label_text.
    """
    _btn = callback_no_args
    page = QWidget()
    layout = QVBoxLayout(page)

    btn_group = QGroupBox(u.group_sim_control)
    btn_layout = QVBoxLayout(btn_group)
    btn_start = QPushButton(u.btn_start)
    btn_start.clicked.connect(_btn(callbacks.on_start))
    btn_stop = QPushButton(u.btn_stop)
    btn_stop.clicked.connect(_btn(callbacks.on_stop))
    btn_layout.addWidget(btn_start)
    btn_layout.addWidget(btn_stop)
    layout.addWidget(btn_group)

    fps_group = QGroupBox(u.group_fps)
    fps_layout = QVBoxLayout(fps_group)
    fps_widgets = add_fps_section_to_layout(
        fps_layout,
        binding=binding,
        u=u,
        on_slider_changed=presenter.on_fps_changed,
    )
    layout.addWidget(fps_group)

    return page, fps_widgets
