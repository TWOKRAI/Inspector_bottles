# -*- coding: utf-8 -*-
"""
Примитивы UI — design system primitives.

Включает два слоя:
- control-primitives: фабрики элементов управления (label, slider, numeric_input)
- widget-primitives: переиспользуемые виджеты (карточки, таблицы, master-detail)

Оба слоя живут в одном пакете: это «design system primitives» и контролы,
и контейнеры идут в один пакет без семантического конфликта.
"""

from multiprocess_framework.modules.frontend_module.components.primitives.control_label import (
    create_control_label,
)
from multiprocess_framework.modules.frontend_module.components.primitives.numeric_line_edit import (
    create_numeric_line_edit,
)
from multiprocess_framework.modules.frontend_module.components.primitives.styled_slider import (
    create_styled_horizontal_slider,
)
from multiprocess_framework.modules.frontend_module.components.primitives.value_bridge import (
    SLIDER_COMMIT_DELAY_MS,
    schedule_slider_value_commit,
)
from multiprocess_framework.modules.frontend_module.components.primitives.status_indicator import (
    StatusIndicator,
)
from multiprocess_framework.modules.frontend_module.components.primitives.entity_card import (
    EntityCard,
    CardAction,
)
from multiprocess_framework.modules.frontend_module.components.primitives.crud_table import (
    CrudTable,
)
from multiprocess_framework.modules.frontend_module.components.primitives.master_detail import (
    MasterDetailLayout,
)

__all__ = [
    # control-primitives
    "create_control_label",
    "create_numeric_line_edit",
    "create_styled_horizontal_slider",
    "SLIDER_COMMIT_DELAY_MS",
    "schedule_slider_value_commit",
    # widget-primitives (перенесены из прото Phase 1A/A2)
    "StatusIndicator",
    "EntityCard",
    "CardAction",
    "CrudTable",
    "MasterDetailLayout",
]
