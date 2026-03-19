# multiprocess_prototype/frontend/configs/tabs/settings_tab_config.py
"""
SettingsTabConfig — конфигурация вкладки настроек.

Список ControlBinding — привязка к регистрам. Метаданные (min, max, label)
читаются из RegistersManager.get_register(name).get_field_meta(field_name) в runtime.
"""

from typing import List

from pydantic import Field

from multiprocess_framework.refactored.modules.data_schema_module import SchemaBase, register_schema

from .control_binding import ControlBinding


def _default_draw_controls() -> List[ControlBinding]:
    """Контролы по умолчанию для DrawRegisters."""
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
        """Список dict для передачи в SettingsTabWidget."""
        return [c.to_control_dict() for c in self.controls]
