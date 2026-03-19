# multiprocess_prototype/frontend/widgets/processing_tab.py
"""
ProcessingTabWidget — вкладка регуляторов обработки.

BGR цветовая детекция, площадь пятна, отображение (Original, Mask, Contours).
Callbacks как в CameraTabWidget.
"""

from typing import Any, Callable, Dict, Optional

from frontend_module.components import BaseTab
from frontend_module.core.qt_imports import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
    Qt,
)


class ProcessingTabWidget(BaseTab):
    """
    Вкладка обработки: BGR, min/max area, Original/Mask/Contours.

    Callbacks: on_set_color_range, on_set_min_area, on_set_max_area,
    on_set_show_original, on_set_show_mask, on_set_draw_contours.
    """

    def __init__(
        self,
        *,
        callbacks: Optional[Dict[str, Callable[..., Any]]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._callbacks = dict(callbacks) if callbacks else {}
        self._init_ui()

    def _cb(self, key: str, *args, **kwargs):
        def _f(*a, **kw):
            fn = self._callbacks.get(key)
            if fn:
                fn(*(a or args), **(kw or kwargs))
        return _f

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Цветовая детекция BGR
        color_group = QGroupBox("Цветовая детекция (BGR)")
        color_layout = QVBoxLayout(color_group)

        def _add_slider_row(name: str, default_lower: int, default_upper: int):
            row = QHBoxLayout()
            lbl = QLabel(name)
            lbl.setMinimumWidth(50)
            row.addWidget(lbl)
            sl_lo = QSlider(Qt.Horizontal)
            sl_lo.setRange(0, 255)
            sl_lo.setValue(default_lower)
            sl_hi = QSlider(Qt.Horizontal)
            sl_hi.setRange(0, 255)
            sl_hi.setValue(default_upper)
            row.addWidget(sl_lo, 1)
            row.addWidget(sl_hi, 1)
            return sl_lo, sl_hi, row

        self._sl_b_lo, self._sl_b_hi, r_b = _add_slider_row("B", 0, 100)
        self._sl_g_lo, self._sl_g_hi, r_g = _add_slider_row("G", 0, 100)
        self._sl_r_lo, self._sl_r_hi, r_r = _add_slider_row("R", 150, 255)

        color_layout.addLayout(r_b)
        color_layout.addLayout(r_g)
        color_layout.addLayout(r_r)

        self._color_label = QLabel("Lower | Upper")
        self._color_label.setStyleSheet("font-size: 10px; color: gray;")
        color_layout.addWidget(self._color_label)

        for sl in (self._sl_b_lo, self._sl_b_hi, self._sl_g_lo, self._sl_g_hi,
                   self._sl_r_lo, self._sl_r_hi):
            sl.valueChanged.connect(self._on_color_range_changed)

        layout.addWidget(color_group)

        # Площадь пятна
        area_group = QGroupBox("Площадь пятна")
        area_layout = QVBoxLayout(area_group)
        self._area_label = QLabel("Мин: 500 px")
        self._area_slider = QSlider(Qt.Horizontal)
        self._area_slider.setRange(10, 5000)
        self._area_slider.setValue(500)
        self._area_slider.valueChanged.connect(self._on_min_area_changed)
        area_layout.addWidget(self._area_label)
        area_layout.addWidget(self._area_slider)
        self._max_area_label = QLabel("Макс: 50000 px (0=без огр.)")
        self._max_area_slider = QSlider(Qt.Horizontal)
        self._max_area_slider.setRange(0, 50000)
        self._max_area_slider.setValue(50000)
        self._max_area_slider.valueChanged.connect(self._on_max_area_changed)
        area_layout.addWidget(self._max_area_label)
        area_layout.addWidget(self._max_area_slider)
        layout.addWidget(area_group)

        # Отображение
        display_group = QGroupBox("Отображение")
        display_layout = QVBoxLayout(display_group)
        self._cb_original = QCheckBox("Original")
        self._cb_original.setChecked(True)
        self._cb_original.stateChanged.connect(self._on_show_original_changed)
        display_layout.addWidget(self._cb_original)
        self._cb_mask = QCheckBox("Mask")
        self._cb_mask.setChecked(True)
        self._cb_mask.stateChanged.connect(self._on_show_mask_changed)
        display_layout.addWidget(self._cb_mask)
        self._cb_contours = QCheckBox("Contours")
        self._cb_contours.setChecked(True)
        self._cb_contours.stateChanged.connect(self._on_draw_contours_changed)
        display_layout.addWidget(self._cb_contours)
        layout.addWidget(display_group)

        layout.addStretch()

    def _on_color_range_changed(self, _value=None) -> None:
        self._color_label.setText(
            f"B[{self._sl_b_lo.value()}-{self._sl_b_hi.value()}] "
            f"G[{self._sl_g_lo.value()}-{self._sl_g_hi.value()}] "
            f"R[{self._sl_r_lo.value()}-{self._sl_r_hi.value()}]"
        )
        fn = self._callbacks.get("on_set_color_range")
        if fn:
            fn(
                self._sl_b_lo.value(),
                self._sl_g_lo.value(),
                self._sl_r_lo.value(),
                self._sl_b_hi.value(),
                self._sl_g_hi.value(),
                self._sl_r_hi.value(),
            )

    def _on_min_area_changed(self, value: int) -> None:
        self._area_label.setText(f"Мин: {value} px")
        fn = self._callbacks.get("on_set_min_area")
        if fn:
            fn(value)

    def _on_max_area_changed(self, value: int) -> None:
        self._max_area_label.setText(
            f"Макс: {value} px" + (" (без огр.)" if value == 0 else "")
        )
        fn = self._callbacks.get("on_set_max_area")
        if fn:
            fn(value)

    def _on_show_original_changed(self, state) -> None:
        fn = self._callbacks.get("on_set_show_original")
        if fn:
            fn(state == Qt.Checked)

    def _on_show_mask_changed(self, state) -> None:
        fn = self._callbacks.get("on_set_show_mask")
        if fn:
            fn(state == Qt.Checked)

    def _on_draw_contours_changed(self, state) -> None:
        fn = self._callbacks.get("on_set_draw_contours")
        if fn:
            fn(state == Qt.Checked)
