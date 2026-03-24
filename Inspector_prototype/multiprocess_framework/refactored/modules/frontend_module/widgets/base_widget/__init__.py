# -*- coding: utf-8 -*-
"""
BaseWidget — базовый MVP-виджет с опциональным слоем Model.

Используется как основа для виджетов-вкладок (Hikvision, SimWebcam и др.)
и для standalone виджетов (диалоги, боковые панели).
Совместим с BaseTab (наследует его для хуков on_tab_selected/on_tab_deselected).
"""
from ..widget_signal_bus import WidgetSignalBus
from .base_widget import BaseWidget, TModel

__all__ = ["BaseWidget", "TModel", "WidgetSignalBus"]
