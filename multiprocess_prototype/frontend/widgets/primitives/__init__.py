"""Примитивные виджеты — универсальные компоненты без зависимости от AppContext.

Каждый виджет принимает чистые данные и выдаёт Qt Signal.
Символы [FW] перенесены в multiprocess_framework и реэкспортируются отсюда.
"""

# [FW] Перенесены в framework (Phase 1A/A2) — re-export для обратной совместимости
from multiprocess_framework.modules.frontend_module.components.primitives import (
    StatusIndicator,
    EntityCard,
    CardAction,
    CrudTable,
    MasterDetailLayout,
)

# Локальные виджеты (в активной разработке или зависимы от прото)
from .action_toolbar import ActionToolbar
from .base_admin_panel import BaseAdminPanel
from .slot_selector import SlotSelector
from .sectioned_form import SectionedForm
from .side_nav_layout import SideNavLayout
from .standard_tab_layout import StandardTabLayout
from .diff_scroll_tab_layout import DiffScrollTabLayout
from .tree_nav_widget import TreeNavWidget

__all__ = [
    "StatusIndicator",
    "EntityCard",
    "CardAction",
    "ActionToolbar",
    "BaseAdminPanel",
    "MasterDetailLayout",
    "SideNavLayout",
    "SlotSelector",
    "CrudTable",
    "SectionedForm",
    "StandardTabLayout",
    "DiffScrollTabLayout",
    "TreeNavWidget",
]
