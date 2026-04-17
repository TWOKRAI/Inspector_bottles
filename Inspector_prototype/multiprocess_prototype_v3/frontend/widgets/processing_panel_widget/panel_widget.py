# multiprocess_prototype_v3/frontend/widgets/processing_panel_widget/panel_widget.py
"""Фиче-виджет обработки: BaseWidget + контролы processor/renderer."""

from __future__ import annotations

from typing import Any, Optional, Union

from frontend_module.components import (
    BindingConfig,
    CheckboxControl,
    CheckboxViewConfig,
    CompoundNumericControl,
    CompoundNumericConfig,
    NumericControl,
    NumericViewConfig,
)
from frontend_module.components.base.touch_keyboard_config import coerce_touch_keyboard
from frontend_module.core.qt_imports import QGroupBox, QLabel, QVBoxLayout
from frontend_module.core.schema_config import coerce_schema_config
from frontend_module.interfaces import IRegistersManagerGui
from frontend_module.widgets.base_widget import BaseWidget

from multiprocess_prototype_v3.frontend.touch_keyboard_bind import merge_touch_keyboard_dicts
from multiprocess_prototype_v3.registers.schemas.processing_tab import (
    PROCESSOR_REGISTER,
    RENDERER_REGISTER,
)

from .model import ProcessingPanelModel
from .presenter import ProcessingPanelPresenter
from .schemas import ProcessingTabUiConfig


class ProcessingPanelWidget(BaseWidget[ProcessingPanelModel]):
    """BGR, площадь, чекбоксы отображения — через NumericControl / CheckboxControl."""

    def __init__(
        self,
        *,
        registers_manager: IRegistersManagerGui,
        ui: Optional[Union[ProcessingTabUiConfig, dict]] = None,
        touch_keyboard: Any | None = None,
        parent: Optional[Any] = None,
    ) -> None:
        """Панель привязана к живому RegistersManager (processor/renderer)."""
        self._touch_keyboard = touch_keyboard
        super().__init__(registers_manager=registers_manager, ui=ui, parent=parent)

    def _coerce_ui(self, ui: Optional[object]) -> ProcessingTabUiConfig:
        """dict/None → ProcessingTabUiConfig."""
        return coerce_schema_config(ui, ProcessingTabUiConfig)

    def _create_model(self) -> ProcessingPanelModel:
        """Модель: rm + подписи UI."""
        assert self._registers_manager is not None
        return ProcessingPanelModel(registers_manager=self._registers_manager, ui=self._ui)

    def _init_ui(self) -> None:
        """Три QGroupBox: BGR lower/upper, площадь, чекбоксы renderer."""
        m = self._model
        assert m is not None
        rm = m.registers_manager
        u = m.ui
        layout = QVBoxLayout(self)

        tk_base = self._touch_keyboard
        tk_bgr = merge_touch_keyboard_dicts(tk_base, getattr(u, "touch_keyboard_bgr", None))
        tk_area = merge_touch_keyboard_dicts(tk_base, getattr(u, "touch_keyboard_area", None))
        bgr_cfg = coerce_touch_keyboard(tk_bgr)
        area_cfg = coerce_touch_keyboard(tk_area)

        # --- Блок: цветовая детекция — два CompoundNumericControl (lower/upper BGR) ---
        color_group = QGroupBox(u.group_color)
        color_layout = QVBoxLayout(color_group)
        bgr_view = NumericViewConfig(min_val=0.0, max_val=255.0, touch_keyboard=bgr_cfg)
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

        # --- Блок: min_area / max_area ---
        area_group = QGroupBox(u.group_area)
        area_layout = QVBoxLayout(area_group)
        min_r = NumericControl.create(
            rm,
            BindingConfig(PROCESSOR_REGISTER, "min_area"),
            NumericViewConfig(
                label=f"{u.label_min_area_prefix} ({u.label_px})",
                touch_keyboard=area_cfg,
            ),
        )
        max_r = NumericControl.create(
            rm,
            BindingConfig(PROCESSOR_REGISTER, "max_area"),
            NumericViewConfig(
                label=f"{u.label_max_area_prefix} ({u.label_px})",
                touch_keyboard=area_cfg,
            ),
        )
        area_layout.addWidget(min_r.widget)
        area_layout.addWidget(max_r.widget)
        layout.addWidget(area_group)

        # --- Блок: флаги отображения и сохранения кадров (renderer) ---
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

    def _create_presenter(self, model: Optional[ProcessingPanelModel]) -> ProcessingPanelPresenter:
        """Заготовка под логику; контролы уже пишут в rm."""
        assert model is not None
        return ProcessingPanelPresenter(view=self, model=model)

    def _connect_signals(self) -> None:
        """Сигналы идут из NumericControl/CheckboxControl; здесь пусто."""
        pass
