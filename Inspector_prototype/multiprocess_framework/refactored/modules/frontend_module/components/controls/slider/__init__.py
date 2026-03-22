# -*- coding: utf-8 -*-
"""
Пакет слайдера с привязкой к регистру.

Публичный API: ``SliderControl``, ``SliderConfig``, ``SliderRegisterExample``.
Внутренняя структура: ``schema/``, ``widget.py``, ``value_mapping.py``, ``field_sync.py``, ``styles.py``.
"""
from frontend_module.components.controls.slider.schema import SliderConfig, SliderRegisterExample
from frontend_module.components.controls.slider.widget import SliderControl

__all__ = ["SliderControl", "SliderConfig", "SliderRegisterExample"]
