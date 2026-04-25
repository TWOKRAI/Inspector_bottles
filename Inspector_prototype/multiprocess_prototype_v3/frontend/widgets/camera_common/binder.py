# multiprocess_prototype_v3/frontend/widgets/camera_common/binder.py
"""Binder — UI ↔ callbacks, presenter, регистр."""

from __future__ import annotations

from typing import Any, Callable, Optional

from multiprocess_framework.modules.frontend_module.widgets.tabs import RegisterBindingContext, callback_no_args
from multiprocess_framework.modules.frontend_module.core.qt_imports import QGroupBox, QPushButton, QVBoxLayout, QWidget

from .callbacks import SimWebcamWidgetCallbacks
from .fps_section import add_fps_section_to_layout
from .schemas import SimWebcamUiConfig


def bind_sim_webcam_ui(
    u: SimWebcamUiConfig,
    binding: RegisterBindingContext,
    callbacks: SimWebcamWidgetCallbacks,
    fps_changed: Callable[[int], None],
    touch_keyboard: Any | None = None,
) -> tuple[QWidget, Optional[object]]:
    """
    Собрать UI и привязать сигналы.

    Returns:
        (page_widget, fps_refs) — fps_refs для set_fps_label_text.
    """
    _btn = callback_no_args
    page = QWidget()
    layout = QVBoxLayout(page)

    # --- Блок: Start / Stop ---
    btn_group = QGroupBox(u.group_sim_control)
    btn_layout = QVBoxLayout(btn_group)
    btn_start = QPushButton(u.btn_start)
    btn_start.clicked.connect(_btn(callbacks.on_start))
    btn_stop = QPushButton(u.btn_stop)
    btn_stop.clicked.connect(_btn(callbacks.on_stop))
    btn_layout.addWidget(btn_start)
    btn_layout.addWidget(btn_stop)
    layout.addWidget(btn_group)

    # --- Блок: FPS (регистр или fallback слайдер) ---
    fps_group = QGroupBox(u.group_fps)
    fps_layout = QVBoxLayout(fps_group)
    fps_widgets = add_fps_section_to_layout(
        fps_layout,
        binding=binding,
        u=u,
        on_slider_changed=fps_changed,
        touch_keyboard=touch_keyboard,
    )
    layout.addWidget(fps_group)

    return page, fps_widgets
