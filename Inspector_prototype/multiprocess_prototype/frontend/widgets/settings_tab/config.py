# multiprocess_prototype/frontend/widgets/settings_tab/config.py
"""
Конфиг вкладки «Настройки»: привязки контролов к регистрам.
"""

from typing import Annotated, List, Literal

from pydantic import Field

from multiprocess_framework.refactored.modules.data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("ControlBinding")
class ControlBinding(SchemaBase):
    """Привязка контрола к register_name.field_name."""

    type: Annotated[
        Literal["slider", "checkbox"],
        FieldMeta("Тип контрола", info="slider — слайдер, checkbox — переключатель."),
    ] = "slider"
    register_name: Annotated[
        str,
        FieldMeta("Имя регистра", info="Ключ в RegistersManager."),
    ] = "draw"
    field_name: Annotated[
        str,
        FieldMeta("Имя поля", info="Поле в схеме регистра."),
    ] = "dp"

    def to_control_dict(self) -> dict:
        return {
            "type": self.type,
            "register_name": self.register_name,
            "field_name": self.field_name,
        }


def _default_draw_controls() -> List[ControlBinding]:
    return [
        ControlBinding(type="slider", register_name="draw", field_name="dp"),
        ControlBinding(type="slider", register_name="draw", field_name="minDist"),
        ControlBinding(type="checkbox", register_name="draw", field_name="circles"),
        ControlBinding(type="checkbox", register_name="draw", field_name="rectangles"),
        ControlBinding(type="checkbox", register_name="draw", field_name="draw"),
    ]


@register_schema("SettingsTabConfig")
class SettingsTabConfig(SchemaBase):
    """Конфигурация SettingsTabWidget."""

    controls: List[ControlBinding] = Field(default_factory=_default_draw_controls)
    group_title: str = "Параметры отображения"

    def to_controls_dict_list(self) -> List[dict]:
        return [c.to_control_dict() for c in self.controls]


def default_tab_item():
    from ..tabs.tab_item_config import TabItemConfig

    return TabItemConfig(id="settings", title="Настройки", widget="settings")
