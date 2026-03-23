# multiprocess_prototype/frontend/widgets/tabs/
"""
Полоса вкладок главного окна: TabItemConfig + TabsConfig.

TabItemConfig — описание одной вкладки (id, title, widget key).
TabsConfig — список вкладок, собирается из default_tab_item() каждой фичи.
"""

from .tab_item_config import TabItemConfig
from .tabs_config import TabsConfig

__all__ = ["TabItemConfig", "TabsConfig"]
