# -*- coding: utf-8 -*-
"""ComboRegister — Django-style дескриптор для str-полей с выпадающим списком.

Pure Python без Qt-зависимостей. Связка с виджетом — на стороне фабрики форм
через FieldMeta.widget == "combo".

Использование в плагине:

    class MyRegisters(SchemaBase, metaclass=DescriptorSchemaMeta):
        mode = ComboRegister(name="Режим", default="auto")
"""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import RegisterDescriptor


class ComboRegister(RegisterDescriptor):
    """Str-поле; UI рендерится через QComboBox (widget='combo')."""

    python_type = str
    widget = "combo"
