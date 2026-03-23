# multiprocess_prototype/frontend/widgets/settings_tab/schemas.py
"""
Конфиг вкладки «Настройки»: привязки контролов к регистрам.

UI-схема рядом с виджетом. Register keys — PROCESSOR_REGISTER / RENDERER_REGISTER
из registers.schemas.processing_tab (единый источник имён).
"""

from __future__ import annotations

from typing import Annotated, Dict, List, Literal, Optional

from pydantic import Field

from multiprocess_framework.refactored.modules.data_schema_module import FieldMeta, SchemaBase, register_schema

from multiprocess_prototype.registers.schemas.processing_tab import (
    PROCESSOR_REGISTER,
    RENDERER_REGISTER,
)


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
    component_config: Annotated[
        Optional[Dict[str, object]],
        FieldMeta("Конфиг компонента", info="Label, transfer_k, position и др."),
    ] = None

    def to_control_dict(self) -> dict:
        """Словарь для _create_control (type, register_name, field_name, component_config)."""
        d: dict = {
            "type": self.type,
            "register_name": self.register_name,
            "field_name": self.field_name,
        }
        if self.component_config is not None:
            d["component_config"] = self.component_config
        return d


def _default_draw_controls() -> List[ControlBinding]:
    """Контролы по умолчанию — processor (min/max area), renderer (отображение)."""
    return [
        ControlBinding(type="slider", register_name=PROCESSOR_REGISTER, field_name="min_area"),
        ControlBinding(type="slider", register_name=PROCESSOR_REGISTER, field_name="max_area"),
        ControlBinding(type="checkbox", register_name=RENDERER_REGISTER, field_name="show_original"),
        ControlBinding(type="checkbox", register_name=RENDERER_REGISTER, field_name="show_mask"),
        ControlBinding(type="checkbox", register_name=RENDERER_REGISTER, field_name="draw_contours"),
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
