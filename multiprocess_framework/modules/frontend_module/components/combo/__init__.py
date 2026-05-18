# -*- coding: utf-8 -*-
"""ComboControl — выпадающий список с binding к регистру (form_ctx-aware).

Компонент по образцу CheckboxControl: config + view + presenter + facade + defaults + registers.

ComboRegister (Django-style дескриптор для str-полей) живёт в `combo/registers.py` —
pure Python без Qt-зависимостей. Документация и схемы: `combo/README.md`.
"""

from multiprocess_framework.modules.frontend_module.components.combo.config import ComboViewConfig
from multiprocess_framework.modules.frontend_module.components.combo.defaults import (
    combo_default,
    combo_with_placeholder,
)
from multiprocess_framework.modules.frontend_module.components.combo.facade import (
    ComboControl,
    ComboControlResult,
)
from multiprocess_framework.modules.frontend_module.components.combo.presenter import ComboPresenter
from multiprocess_framework.modules.frontend_module.components.combo.registers import ComboRegister
from multiprocess_framework.modules.frontend_module.components.combo.view import ComboView

__all__ = [
    "ComboViewConfig",
    "ComboView",
    "ComboPresenter",
    "ComboControl",
    "ComboControlResult",
    "ComboRegister",
    "combo_default",
    "combo_with_placeholder",
]
