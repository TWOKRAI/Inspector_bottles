# multiprocess_prototype/frontend/widgets/tabs_setting/processing_tab/widget.py
"""
ProcessingTabWidget — вкладка регуляторов обработки.

Использует control_v2: NumericControl, CompoundNumericControl, CheckboxControl.
Поля ProcessorRegisters / RendererRegisters. Подписи — ProcessingTabUiConfig.

Доступность контролов: RegisterBindingContext + IRegistersManagerGui; при
отсутствии rm — заглушка (см. TAB_STRUCTURE.md).
"""

from __future__ import annotations

from typing import Optional, Union

from frontend_module.widgets.tabs import BaseTab
from frontend_module.widgets.tabs import RegisterBindingContext, create_registers_placeholder
from frontend_module.components import (
    BindingConfig,
    CheckboxControl,
    CheckboxViewConfig,
    CompoundNumericControl,
    CompoundNumericConfig,
    NumericControl,
    NumericViewConfig,
)
from frontend_module.core.qt_imports import QGroupBox, QLabel, QVBoxLayout, QWidget
from frontend_module.core.schema_config import coerce_schema_config
from frontend_module.interfaces import IRegistersManagerGui

from multiprocess_prototype.registers.schemas.processing_tab import (
    PROCESSOR_REGISTER,
    RENDERER_REGISTER,
)

from .schemas import ProcessingTabUiConfig


class ProcessingTabWidget(BaseTab):
    """
    Вкладка обработки: BGR, min/max area, Original/Mask/Contours.

    Все контролы — control_v2. Изменения через set_field_value → register_update.
    """

    def __init__(
        self,
        *,
        registers_manager: Optional[IRegistersManagerGui] = None,
        ui: Optional[Union[ProcessingTabUiConfig, dict]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._u = coerce_schema_config(ui, ProcessingTabUiConfig)
        self._init_ui()

    @property
    def registers_manager(self) -> Optional[IRegistersManagerGui]:
        return self._registers_manager

    def _init_ui(self) -> None:
        u = self._u
        layout = QVBoxLayout(self)
        binding = RegisterBindingContext(rm=self._registers_manager)

        if not binding.can_bind:
            layout.addWidget(create_registers_placeholder("Обработка"))
            layout.addStretch()
            return

        rm = binding.rm
        assert rm is not None  # согласовано с can_bind

        # Цветовая детекция: BGR lower/upper
        color_group = QGroupBox(u.group_color)
        color_layout = QVBoxLayout(color_group)
        bgr_view = NumericViewConfig(min_val=0.0, max_val=255.0)
        labels = [u.channel_b, u.channel_g, u.channel_r]
        lower_cfg = CompoundNumericConfig(
            binding=BindingConfig(PROCESSOR_REGISTER, "color_lower"),
            labels=labels,
            view_config=bgr_view,
        )
        upper_cfg = CompoundNumericConfig(
            binding=BindingConfig(PROCESSOR_REGISTER, "color_upper"),
            labels=labels,
            view_config=bgr_view,
        )
        lower_result = CompoundNumericControl.create(rm, lower_cfg)
        upper_result = CompoundNumericControl.create(rm, upper_cfg)
        color_layout.addWidget(lower_result.widget)
        color_layout.addWidget(upper_result.widget)
        self._color_label = QLabel(u.color_hint)
        self._color_label.setStyleSheet("font-size: 10px; color: gray;")
        color_layout.addWidget(self._color_label)
        layout.addWidget(color_group)

        # Площадь пятна: min_area, max_area
        area_group = QGroupBox(u.group_area)
        area_layout = QVBoxLayout(area_group)
        min_r = NumericControl.create(
            rm,
            BindingConfig(PROCESSOR_REGISTER, "min_area"),
            NumericViewConfig(label=f"{u.label_min_area_prefix} ({u.label_px})"),
        )
        max_r = NumericControl.create(
            rm,
            BindingConfig(PROCESSOR_REGISTER, "max_area"),
            NumericViewConfig(label=f"{u.label_max_area_prefix} ({u.label_px})"),
        )
        area_layout.addWidget(min_r.widget)
        area_layout.addWidget(max_r.widget)
        layout.addWidget(area_group)

        # Отображение: show_original, show_mask, draw_contours, draw_bboxes, save_frames
        display_group = QGroupBox(u.group_display)
        display_layout = QVBoxLayout(display_group)
        for reg_name, field_name, label in [
            (RENDERER_REGISTER, "show_original", u.checkbox_original),
            (RENDERER_REGISTER, "show_mask", u.checkbox_mask),
            (RENDERER_REGISTER, "draw_contours", u.checkbox_contours),
            (RENDERER_REGISTER, "draw_bboxes", u.checkbox_bbox),
            (RENDERER_REGISTER, "save_frames", u.checkbox_save_frames),
        ]:
            r = CheckboxControl.create(
                rm,
                BindingConfig(reg_name, field_name),
                CheckboxViewConfig(label=label),
            )
            display_layout.addWidget(r.widget)
        layout.addWidget(display_group)

        layout.addStretch()
