# -*- coding: utf-8 -*-
"""
Дефолтные схемы групп.

Каждая схема включает конфиги дочерних компонентов + параметры группы.
"""
from frontend_module.components.group.config import LabeledNumericGroupConfig
from frontend_module.components.label.config import LabelConfig
from frontend_module.components.slider.config import SliderConfig
from frontend_module.components.spinbox.config import SpinBoxConfig

# Группа: подпись слева + слайдер
label_slider_default = LabeledNumericGroupConfig(
    label_config=LabelConfig(position="left"),
    value_config=SliderConfig(show_ticks=False),
    spacing=5,
)

# Группа: подпись слева + спинбокс
label_spinbox_default = LabeledNumericGroupConfig(
    label_config=LabelConfig(position="left"),
    value_config=SpinBoxConfig(),
    spacing=5,
)

# Группа для BGR (0–255)
label_bgr_slider_default = LabeledNumericGroupConfig(
    label_config=LabelConfig(position="left"),
    value_config=SliderConfig(min_val=0.0, max_val=255.0),
    spacing=5,
)
