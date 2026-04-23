# multiprocess_prototype_v3/frontend/widgets/tabs_setting/graph_editor_tab/schemas.py
"""Схема конфигурации вкладки графового редактора."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import SchemaBase, register_schema
from multiprocess_prototype_v3.frontend.widgets.tabs_setting.tab_item_config import TabItemConfig


def default_tab_item() -> TabItemConfig:
    """TabItemConfig вкладки «Граф»."""
    return TabItemConfig(id="graph_editor", widget="graph_editor", title="Граф")


@register_schema("GraphEditorTabConfig")
class GraphEditorTabConfig(SchemaBase):
    """Конфиг вкладки графового редактора."""

    # Автоматически переключать на графовый вид при открытии
    auto_switch_to_graph: bool = False
