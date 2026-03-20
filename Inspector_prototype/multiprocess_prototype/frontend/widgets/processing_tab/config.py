# multiprocess_prototype/frontend/widgets/processing_tab/config.py
"""Параметры вкладки «Обработка» как компонента UI (не строки контролов)."""

from multiprocess_framework.refactored.modules.data_schema_module import SchemaBase, register_schema


@register_schema("ProcessingTabConfig")
class ProcessingTabConfig(SchemaBase):
    """
    Настройки самой вкладки (раскладка, поведение).

    Подписи групп, слайдеров и чекбоксов — в `widgets.processing_tab.ui_config.ProcessingTabUiConfig`
    (единый источник типов/текстов для фронта и при необходимости бэкенда).
    """

    pass


def default_tab_item():
    """Строка вкладки в TabWidget (см. `widgets/tabs/tabs_config.py`)."""
    from ..tabs.tab_item_config import TabItemConfig

    return TabItemConfig(id="processing", title="Обработка", widget="processing")
