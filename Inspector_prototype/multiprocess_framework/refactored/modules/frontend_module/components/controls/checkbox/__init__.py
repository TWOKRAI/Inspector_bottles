# -*- coding: utf-8 -*-
"""
Пакет чекбокса с привязкой к регистру.

Публичный API: ``CheckboxControl``, ``CheckboxConfig``, ``CheckboxRegisterExample``.
Внутренняя структура: ``schema/``, ``widget.py``, ``layout_builder.py``, ``field_sync.py``, ``styles.py``.
"""
from frontend_module.components.controls.checkbox.schema import (
    CheckboxConfig,
    CheckboxRegisterExample,
)
from frontend_module.components.controls.checkbox.widget import CheckboxControl

__all__ = ["CheckboxControl", "CheckboxConfig", "CheckboxRegisterExample"]
