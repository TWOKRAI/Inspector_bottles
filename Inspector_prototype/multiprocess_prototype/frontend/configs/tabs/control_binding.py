# multiprocess_prototype/frontend/configs/tabs/control_binding.py
"""
ControlBinding — привязка UI-контрола к полю регистра.

Используется в SettingsTabConfig для декларативного описания слайдеров и чекбоксов.
Метаданные (min, max, label) берутся из схемы регистра в runtime.
"""

from typing import Annotated, Literal

from multiprocess_framework.refactored.modules.data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("ControlBinding")
class ControlBinding(SchemaBase):
    """Привязка контрола к register_name.field_name."""

    type: Annotated[
        Literal["slider", "checkbox"],
        FieldMeta("Тип контрола", info="slider — числовой слайдер, checkbox — переключатель."),
    ] = "slider"
    register_name: Annotated[
        str,
        FieldMeta("Имя регистра", info="Ключ в RegistersManager (draw, processor, renderer)."),
    ] = "draw"
    field_name: Annotated[
        str,
        FieldMeta("Имя поля", info="Поле в схеме регистра (dp, minDist, circles и т.д.)."),
    ] = "dp"

    def to_control_dict(self) -> dict:
        """Преобразовать в dict для SliderControl/CheckboxControl."""
        return {
            "type": self.type,
            "register_name": self.register_name,
            "field_name": self.field_name,
        }
