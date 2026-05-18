# -*- coding: utf-8 -*-
"""
Готовые экземпляры `ComboViewConfig` для типичных сценариев (с/без placeholder).

Использовать вместо ручного `ComboViewConfig(placeholder=...)` в конфигах окон.
"""

from multiprocess_framework.modules.frontend_module.components.combo.config import ComboViewConfig

# Самый частый случай в factory.py: items берутся извне (из Literal-типа поля).
combo_default = ComboViewConfig()
# Combo с подсказкой при пустом выборе (вставляется как первый пустой item).
combo_with_placeholder = ComboViewConfig(placeholder="— выберите —")
