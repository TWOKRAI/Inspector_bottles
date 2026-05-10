# multiprocess_prototype/frontend/widgets/processing_panel_widget/model.py
"""Модель панели обработки (привязка к регистрам processor/renderer)."""

from __future__ import annotations

from dataclasses import dataclass

from multiprocess_framework.modules.frontend_module.interfaces import IRegistersManagerGui

from .schemas import ProcessingTabUiConfig


@dataclass
class ProcessingPanelModel:
    registers_manager: IRegistersManagerGui
    ui: ProcessingTabUiConfig
