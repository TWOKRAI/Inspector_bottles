# multiprocess_prototype_v3/frontend/widgets/tabs_setting/sources_tab/schemas.py
"""Конфиг вкладки «Источники» — объединяет камеру и регионы."""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import SchemaBase, register_schema

from ..tab_item_config import TabItemConfig


@register_schema("SourcesTabUiConfig")
class SourcesTabUiConfig(SchemaBase):
    """Минимальный конфиг — делегирует дочерним виджетам."""

    splitter_ratio: list[int] = [1, 1]


def default_tab_item() -> TabItemConfig:
    return TabItemConfig(id="sources", widget="sources", title="Источники")
