# multiprocess_prototype/frontend/widgets/processing_tab/widget.py
"""
ProcessingTabWidget — вкладка регуляторов обработки.

С RegistersManager: поля ProcessorRegisters / RendererRegisters + контролы frontend_module;
шесть слайдеров BGR ↔ списки color_lower / color_upper. Подписи групп — ProcessingTabUiConfig.

Без registers_manager: прежние callbacks (тесты / минимальный режим).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from frontend_module.components import BaseTab, CheckboxControl, SliderControl
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

from multiprocess_prototype.registers.schemas.processing_tab import (
    PROCESSOR_REGISTER,
    RENDERER_REGISTER,
)

from .ui_config import ProcessingTabUiConfig


def _coerce_processing_ui(
    ui: Optional[Union[ProcessingTabUiConfig, dict]],
) -> ProcessingTabUiConfig:
    if ui is None:
        return ProcessingTabUiConfig()
    if isinstance(ui, ProcessingTabUiConfig):
        return ui
    return ProcessingTabUiConfig.model_validate(ui)


def _clamp_byte(x: int) -> int:
    return max(0, min(255, int(x)))


class ProcessingTabWidget(BaseTab):
    """
    Вкладка обработки: BGR, min/max area, Original/Mask/Contours.

    При наличии registers_manager изменения идут через set_field_value → register_update.
    Иначе callbacks: on_set_color_range, on_set_min_area, on_set_max_area,
    on_set_show_original, on_set_show_mask, on_set_draw_contours.
    """

    def __init__(
        self,
        *,
        registers_manager: Optional[Any] = None,
        callbacks: Optional[Dict[str, Callable[..., Any]]] = None,
        ui: Optional[Union[ProcessingTabUiConfig, dict]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._callbacks = dict(callbacks) if callbacks else {}
        self._u = _coerce_processing_ui(ui)
        self._mute_register_subscriptions = False
        self._init_ui()
        self._wire_register_subscriptions()

    @property
    def registers_manager(self) -> Optional[Any]:
        return self._registers_manager

    def _rm(self) -> Optional[Any]:
        return self._registers_manager

    def _init_ui(self) -> None:
        u = self._u
        layout = QVBoxLayout(self)

        color_group = QGroupBox(u.group_color)
        color_layout = QVBoxLayout(color_group)

        self._sl_b_lo, self._sl_b_hi, _ = self._make_bgr_row(u.channel_b, color_layout)
        self._sl_g_lo, self._sl_g_hi, _ = self._make_bgr_row(u.channel_g, color_layout)
        self._sl_r_lo, self._sl_r_hi, _ = self._make_bgr_row(u.channel_r, color_layout)

        self._color_label = QLabel(u.color_hint)
        self._color_label.setStyleSheet("font-size: 10px; color: gray;")
        color_layout.addWidget(self._color_label)

        for sl in (
            self._sl_b_lo,
            self._sl_b_hi,
            self._sl_g_lo,
            self._sl_g_hi,
            self._sl_r_lo,
            self._sl_r_hi,
        ):
            sl.valueChanged.connect(self._on_color_range_changed)

        layout.addWidget(color_group)

        area_group = QGroupBox(u.group_area)
        area_layout = QVBoxLayout(area_group)
        rm = self._rm()
        if rm and hasattr(rm, "set_field_value"):
            self._area_slider = SliderControl(
                register_name=PROCESSOR_REGISTER,
                field_name="min_area",
                registers_manager=rm,
                parent=self,
                label=f"{u.label_min_area_prefix} ({u.label_px})",
            )
            self._max_area_slider = SliderControl(
                register_name=PROCESSOR_REGISTER,
                field_name="max_area",
                registers_manager=rm,
                parent=self,
                label=f"{u.label_max_area_prefix} ({u.label_px})",
            )
            area_layout.addWidget(self._area_slider)
            area_layout.addWidget(self._max_area_slider)
        else:
            self._area_label = QLabel(f"{u.label_min_area_prefix} 500 {u.label_px}")
            self._area_slider = QSlider(Qt.Horizontal)
            self._area_slider.setRange(10, 5000)
            self._area_slider.setValue(500)
            self._area_slider.valueChanged.connect(self._on_min_area_changed)
            area_layout.addWidget(self._area_label)
            area_layout.addWidget(self._area_slider)
            self._max_area_label = QLabel(
                f"{u.label_max_area_prefix} 50000 {u.label_px}{u.label_max_area_initial_suffix}"
            )
            self._max_area_slider = QSlider(Qt.Horizontal)
            self._max_area_slider.setRange(0, 50000)
            self._max_area_slider.setValue(50000)
            self._max_area_slider.valueChanged.connect(self._on_max_area_changed)
            area_layout.addWidget(self._max_area_label)
            area_layout.addWidget(self._max_area_slider)
        layout.addWidget(area_group)

        display_group = QGroupBox(u.group_display)
        display_layout = QVBoxLayout(display_group)
        if rm and hasattr(rm, "set_field_value"):
            display_layout.addWidget(
                CheckboxControl(
                    register_name=RENDERER_REGISTER,
                    field_name="show_original",
                    registers_manager=rm,
                    parent=self,
                    label=u.checkbox_original,
                )
            )
            display_layout.addWidget(
                CheckboxControl(
                    register_name=RENDERER_REGISTER,
                    field_name="show_mask",
                    registers_manager=rm,
                    parent=self,
                    label=u.checkbox_mask,
                )
            )
            display_layout.addWidget(
                CheckboxControl(
                    register_name=RENDERER_REGISTER,
                    field_name="draw_contours",
                    registers_manager=rm,
                    parent=self,
                    label=u.checkbox_contours,
                )
            )
        else:
            self._cb_original = QCheckBox(u.checkbox_original)
            self._cb_original.setChecked(True)
            self._cb_original.stateChanged.connect(self._on_show_original_changed)
            display_layout.addWidget(self._cb_original)
            self._cb_mask = QCheckBox(u.checkbox_mask)
            self._cb_mask.setChecked(True)
            self._cb_mask.stateChanged.connect(self._on_show_mask_changed)
            display_layout.addWidget(self._cb_mask)
            self._cb_contours = QCheckBox(u.checkbox_contours)
            self._cb_contours.setChecked(True)
            self._cb_contours.stateChanged.connect(self._on_draw_contours_changed)
            display_layout.addWidget(self._cb_contours)
        layout.addWidget(display_group)

        layout.addStretch()

        self._sync_color_sliders_from_register()
        self._update_color_hint()

    def _make_bgr_row(
        self, name: str, color_layout: QVBoxLayout
    ) -> Tuple[QSlider, QSlider, QHBoxLayout]:
        row = QHBoxLayout()
        lbl = QLabel(name)
        lbl.setMinimumWidth(50)
        row.addWidget(lbl)
        sl_lo = QSlider(Qt.Horizontal)
        sl_lo.setRange(0, 255)
        sl_hi = QSlider(Qt.Horizontal)
        sl_hi.setRange(0, 255)
        row.addWidget(sl_lo, 1)
        row.addWidget(sl_hi, 1)
        color_layout.addLayout(row)
        return sl_lo, sl_hi, row

    def _read_colors(self) -> Tuple[List[int], List[int]]:
        rm = self._rm()
        if not rm:
            return [0, 0, 150], [100, 100, 255]
        reg = rm.get_register(PROCESSOR_REGISTER)
        if not reg:
            return [0, 0, 150], [100, 100, 255]
        lo = list(getattr(reg, "color_lower", None) or [0, 0, 150])
        hi = list(getattr(reg, "color_upper", None) or [100, 100, 255])
        while len(lo) < 3:
            lo.append(0)
        while len(hi) < 3:
            hi.append(255)
        return lo[:3], hi[:3]

    def _sync_color_sliders_from_register(self) -> None:
        lo, hi = self._read_colors()
        pairs = (
            (self._sl_b_lo, lo[0]),
            (self._sl_g_lo, lo[1]),
            (self._sl_r_lo, lo[2]),
            (self._sl_b_hi, hi[0]),
            (self._sl_g_hi, hi[1]),
            (self._sl_r_hi, hi[2]),
        )
        for sl, v in pairs:
            sl.blockSignals(True)
            sl.setValue(_clamp_byte(v))
            sl.blockSignals(False)

    def _wire_register_subscriptions(self) -> None:
        rm = self._rm()
        if not rm or not hasattr(rm, "subscribe"):
            return
        rm.subscribe(PROCESSOR_REGISTER, "color_lower", self._on_register_color_lower)
        rm.subscribe(PROCESSOR_REGISTER, "color_upper", self._on_register_color_upper)

    def _on_register_color_lower(self, value: Any) -> None:
        if self._mute_register_subscriptions:
            return
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            return
        for sl, v in zip(
            (self._sl_b_lo, self._sl_g_lo, self._sl_r_lo),
            value[:3],
        ):
            sl.blockSignals(True)
            sl.setValue(_clamp_byte(int(v)))
            sl.blockSignals(False)
        self._update_color_hint()

    def _on_register_color_upper(self, value: Any) -> None:
        if self._mute_register_subscriptions:
            return
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            return
        for sl, v in zip(
            (self._sl_b_hi, self._sl_g_hi, self._sl_r_hi),
            value[:3],
        ):
            sl.blockSignals(True)
            sl.setValue(_clamp_byte(int(v)))
            sl.blockSignals(False)
        self._update_color_hint()

    def _update_color_hint(self) -> None:
        self._color_label.setText(
            f"B[{self._sl_b_lo.value()}-{self._sl_b_hi.value()}] "
            f"G[{self._sl_g_lo.value()}-{self._sl_g_hi.value()}] "
            f"R[{self._sl_r_lo.value()}-{self._sl_r_hi.value()}]"
        )

    def _on_color_range_changed(self, _value: Optional[int] = None) -> None:
        self._update_color_hint()
        rm = self._rm()
        if rm and hasattr(rm, "set_field_value"):
            lo = [self._sl_b_lo.value(), self._sl_g_lo.value(), self._sl_r_lo.value()]
            hi = [self._sl_b_hi.value(), self._sl_g_hi.value(), self._sl_r_hi.value()]
            self._mute_register_subscriptions = True
            try:
                rm.set_field_value(PROCESSOR_REGISTER, "color_lower", lo)
                rm.set_field_value(PROCESSOR_REGISTER, "color_upper", hi)
            finally:
                self._mute_register_subscriptions = False
            return
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
        u = self._u
        self._area_label.setText(f"{u.label_min_area_prefix} {value} {u.label_px}")
        fn = self._callbacks.get("on_set_min_area")
        if fn:
            fn(value)

    def _on_max_area_changed(self, value: int) -> None:
        u = self._u
        tail = u.label_max_area_unlimited if value == 0 else ""
        self._max_area_label.setText(
            f"{u.label_max_area_prefix} {value} {u.label_px}{tail}"
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
