# -*- coding: utf-8 -*-
"""Инфраструктура v2: адаптеры, трансформеры, утилиты."""
from frontend_module.components.base.infrastructure.register_adapter import (
    RegisterAdapter,
)
from frontend_module.components.base.infrastructure.signal_utils import (
    block_signals,
)
from frontend_module.components.base.infrastructure.value_transformer import (
    ValueTransformer,
)

__all__ = [
    "RegisterAdapter",
    "ValueTransformer",
    "block_signals",
]
