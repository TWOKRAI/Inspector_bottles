# -*- coding: utf-8 -*-
"""
SpinBoxControl — фасад для спинбокса с привязкой к регистру.

``SpinBoxPresenter`` + labeled group (без прокси через ``NumericControl``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from frontend_module.components.control_v2.base import RegisterAdapter
from frontend_module.components.control_v2.base.config import BindingConfig
from frontend_module.components.control_v2.base.control_hooks import ControlHooks
from frontend_module.components.control_v2.base.traits import LegacySyncContext
from frontend_module.components.control_v2.group.labeled_numeric_factory import (
    create_labeled_numeric_view,
)
from frontend_module.components.control_v2.numeric.config import NumericViewConfig
from frontend_module.components.control_v2.spinbox.config import SpinBoxConfig
from frontend_module.components.control_v2.spinbox.presenter import SpinBoxPresenter
from frontend_module.core.qt_imports import QWidget


@dataclass
class SpinBoxControlResult:
    """Итог фабрики: виджет группы Label+SpinBox и ``SpinBoxPresenter``."""

    widget: QWidget
    presenter: SpinBoxPresenter


def _spinbox_config_to_numeric_view_config(config: SpinBoxConfig) -> NumericViewConfig:
    """SpinBoxConfig → NumericViewConfig с ``view_type="spinbox"``."""
    return NumericViewConfig(
        view_type="spinbox",
        label=config.label,
        tooltip=config.tooltip,
        enabled=config.enabled,
        access_level=config.access_level,
        min_val=config.min_val,
        max_val=config.max_val,
        label_position=config.label_position,
    )


class SpinBoxControl:
    """Статическая фабрика: ``SpinBoxPresenter`` + labeled group."""

    @staticmethod
    def create(
        registers_manager: Optional[Any],
        binding: BindingConfig,
        view_config: SpinBoxConfig | None = None,
        current_access_level: int = 0,
        legacy_context: Optional[LegacySyncContext] = None,
        hooks: ControlHooks | None = None,
    ) -> SpinBoxControlResult:
        """
        Создать спинбокс, привязанный к полю регистра.

        Args:
            hooks: См. ``NumericPresenter`` / ``SliderControl.create``: колбэки записи и
                ``on_access_denied`` при недостаточных правах.
        """
        view_config = view_config or SpinBoxConfig()
        numeric_config = _spinbox_config_to_numeric_view_config(view_config)
        adapter = RegisterAdapter(registers_manager)
        presenter = SpinBoxPresenter(
            binding,
            adapter,
            numeric_config,
            current_access_level,
            legacy_context=legacy_context,
            registers_manager=registers_manager,
            hooks=hooks,
        )
        view = create_labeled_numeric_view(
            view_type="spinbox",
            value_config=numeric_config,
            label_position=numeric_config.label_position,
        )
        presenter.attach_view(view)
        return SpinBoxControlResult(widget=view, presenter=presenter)
