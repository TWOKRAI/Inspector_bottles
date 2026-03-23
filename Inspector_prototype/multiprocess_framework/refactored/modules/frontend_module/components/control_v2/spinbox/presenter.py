# -*- coding: utf-8 -*-
"""
SpinBoxPresenter — тот же состав трейтов, что у ``NumericPresenter``, отдельный тип для спинбокса.
"""
from __future__ import annotations

from typing import Optional

from frontend_module.components.control_v2.base import RegisterAdapter
from frontend_module.components.control_v2.base.control_hooks import ControlHooks
from frontend_module.components.control_v2.base.config import BindingConfig
from frontend_module.components.control_v2.base.traits import LegacySyncContext
from frontend_module.components.control_v2.numeric.config import NumericViewConfig
from frontend_module.components.control_v2.numeric.presenter import NumericPresenter


class SpinBoxPresenter(NumericPresenter):
    """Числовой presenter для ``view_type=spinbox``; наследует логику ``NumericPresenter``."""

    def __init__(
        self,
        binding: BindingConfig,
        adapter: RegisterAdapter,
        view_config: NumericViewConfig | None = None,
        current_access_level: int = 0,
        legacy_context: LegacySyncContext | None = None,
        registers_manager: Optional[object] = None,
        hooks: ControlHooks | None = None,
    ) -> None:
        super().__init__(
            binding,
            adapter,
            view_config,
            current_access_level,
            legacy_context=legacy_context,
            registers_manager=registers_manager,
            hooks=hooks,
            control_kind="spinbox",
        )
