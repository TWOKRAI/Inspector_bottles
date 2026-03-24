# -*- coding: utf-8 -*-
"""
Готовые экземпляры `CheckboxViewConfig` для типичных раскладок (метка слева/справа).

Использовать вместо ручного `CheckboxViewConfig(position=...)` в конфигах окон.
"""
from frontend_module.components.checkbox.config import CheckboxViewConfig

# Метка слева от квадрата (то же, что дефолт у CheckboxViewConfig.position).
checkbox_left = CheckboxViewConfig(position="left")
# Метка справа от квадрата.
checkbox_right = CheckboxViewConfig(position="right")
