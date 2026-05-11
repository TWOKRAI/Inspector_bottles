"""Примитивные виджеты — универсальные компоненты без зависимости от AppContext.

Каждый виджет принимает чистые данные и выдаёт Qt Signal.
Помечены [FW] если могут переехать в multiprocess_framework.
"""
from .status_indicator import StatusIndicator
from .entity_card import CardAction, EntityCard
from .action_toolbar import ActionToolbar
from .master_detail import MasterDetailLayout
from .slot_selector import SlotSelector
from .crud_table import CrudTable
from .sectioned_form import SectionedForm
from .side_nav_layout import SideNavLayout
from .standard_tab_layout import StandardTabLayout

__all__ = [
    "StatusIndicator",
    "EntityCard",
    "CardAction",
    "ActionToolbar",
    "MasterDetailLayout",
    "SideNavLayout",
    "SlotSelector",
    "CrudTable",
    "SectionedForm",
    "StandardTabLayout",
]
