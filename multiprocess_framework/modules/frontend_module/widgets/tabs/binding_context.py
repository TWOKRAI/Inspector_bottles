# -*- coding: utf-8 -*-
"""
RegisterBindingContext — контекст привязки к регистрам для секций вкладок.

Убирает размазанные проверки `hasattr(rm, "set_field_value")`: секции получают
контекст и используют `can_bind` / `rm` вместо сырого `Optional[RegistersManager]`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from multiprocess_framework.modules.frontend_module.interfaces import IRegistersManagerGui


@dataclass(frozen=True)
class RegisterBindingContext:
    """Есть ли rm для NumericControl; при отсутствии — fallback (слайдер / line edit)."""

    rm: Optional[IRegistersManagerGui]
    action_bus: Optional[object] = None

    @property
    def can_bind(self) -> bool:
        return self.rm is not None
