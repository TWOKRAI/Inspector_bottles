# -*- coding: utf-8 -*-
"""
Дефолтные конфиги числовых контролов.
"""
from multiprocess_framework.modules.frontend_module.components.numeric.config import NumericViewConfig

# Числовые
slider_default = NumericViewConfig(view_type="slider")
spinbox_default = NumericViewConfig(view_type="spinbox")
bgr_slider_default = NumericViewConfig(
    view_type="slider",
    min_val=0.0,
    max_val=255.0,
)
