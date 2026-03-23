# multiprocess_prototype/frontend/widgets/camera_tab/pages/sim_webcam.py
"""
Страница стека для Simulator и Webcam: Start/Stop и блок FPS.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from frontend_module.components.tabs import RegisterBindingContext
from frontend_module.core.qt_imports import QGroupBox, QPushButton, QVBoxLayout, QWidget

from ..fps_section import FpsFallbackWidgets, add_fps_section_to_layout
from ..schemas import CameraTabUiConfig


@dataclass
class SimWebcamPageRefs:
    """Виджеты, к которым обращается виджет вкладки (FPS label/slider в fallback)."""

    btn_start: QPushButton
    btn_stop: QPushButton
    fps: FpsFallbackWidgets


def build_sim_webcam_page(
    u: CameraTabUiConfig,
    binding: RegisterBindingContext,
    *,
    on_start: Callable[[], None],
    on_stop: Callable[[], None],
    on_fps_slider_changed: Callable[[int], None],
) -> tuple[QWidget, SimWebcamPageRefs]:
    """Страница Simulator/Webcam: Start/Stop, FPS (NumericControl или fallback-слайдер)."""
    page = QWidget()
    layout = QVBoxLayout(page)

    btn_group = QGroupBox(u.group_sim_control)
    btn_layout = QVBoxLayout(btn_group)
    btn_start = QPushButton(u.btn_start)
    btn_start.clicked.connect(on_start)
    btn_stop = QPushButton(u.btn_stop)
    btn_stop.clicked.connect(on_stop)
    btn_layout.addWidget(btn_start)
    btn_layout.addWidget(btn_stop)
    layout.addWidget(btn_group)

    fps_group = QGroupBox(u.group_fps)
    fps_layout = QVBoxLayout(fps_group)
    fps_widgets = add_fps_section_to_layout(
        fps_layout,
        binding=binding,
        u=u,
        on_slider_changed=on_fps_slider_changed,
    )
    layout.addWidget(fps_group)

    refs = SimWebcamPageRefs(btn_start=btn_start, btn_stop=btn_stop, fps=fps_widgets)
    return page, refs
