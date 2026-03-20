# multiprocess_prototype/frontend/widgets/camera_tab/config.py
"""Параметры вкладки «Камера» как компонента UI (не строки контролов)."""

from multiprocess_framework.refactored.modules.data_schema_module import SchemaBase, register_schema


@register_schema("CameraTabConfig")
class CameraTabConfig(SchemaBase):
    """
    Настройки самой вкладки (раскладка, поведение).

    Подписи и тексты — в `widgets.camera_tab.ui_config.CameraTabUiConfig`.
    """

    pass


def default_tab_item():
    """Строка вкладки в TabWidget (см. `widgets/tabs/tabs_config.py`)."""
    from ..tabs.tab_item_config import TabItemConfig

    return TabItemConfig(id="camera", title="Камера", widget="camera")
