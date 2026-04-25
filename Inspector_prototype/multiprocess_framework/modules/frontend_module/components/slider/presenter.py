# -*- coding: utf-8 -*-
"""
SliderPresenter — тот же состав трейтов, что у ``NumericPresenter``, отдельный тип для API слайдера.
"""
from __future__ import annotations

from typing import Optional

from multiprocess_framework.modules.frontend_module.components.base import RegisterAdapter
from multiprocess_framework.modules.frontend_module.components.base.control_hooks import ControlHooks
from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
from multiprocess_framework.modules.frontend_module.components.base.traits import LegacySyncContext
from multiprocess_framework.modules.frontend_module.components.numeric.config import NumericViewConfig
from multiprocess_framework.modules.frontend_module.components.numeric.presenter import NumericPresenter


class SliderPresenter(NumericPresenter):
    """Числовой presenter для ``view_type=slider``; наследует логику ``NumericPresenter``."""

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
            control_kind="slider",
        )
