# -*- coding: utf-8 -*-
"""SliderRegister — Django-style дескриптор для int-полей со слайдером.

Pure Python без Qt-зависимостей. Связка с виджетом — на стороне фабрики форм
через FieldMeta.widget == "slider".

Использование в плагине:

    class MyRegisters(SchemaBase, metaclass=DescriptorSchemaMeta):
        interval = SliderRegister(name="Interval", default=1, min=1, max=60, unit="s")
"""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import RegisterDescriptor


class SliderRegister(RegisterDescriptor):
    """Int-поле; UI рендерится через QSlider/QSpinBox (widget='slider')."""

    python_type = int
    widget = "slider"
