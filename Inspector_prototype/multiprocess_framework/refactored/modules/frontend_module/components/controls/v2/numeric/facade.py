# -*- coding: utf-8 -*-
"""
NumericControl — фасад для создания числового контрола.

Выбор View по view_config.view_type (slider | spinbox).
Возвращает (widget, presenter) для явного управления жизненным циклом.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from frontend_module.components.controls.v2.base import RegisterAdapter
from frontend_module.components.controls.v2.base.config import BindingConfig
from frontend_module.components.controls.v2.base.traits import LegacySyncContext
from frontend_module.components.controls.v2.numeric.config import NumericViewConfig
from frontend_module.components.controls.v2.numeric.presenter import NumericPresenter
from frontend_module.components.controls.v2.group.view import create_labeled_numeric_view
from frontend_module.core.qt_imports import QWidget


@dataclass
class NumericControlResult:
    """Результат NumericControl.create(): виджет и presenter."""

    widget: QWidget
    presenter: NumericPresenter


def _create_numeric_view(
    view_type: Literal["slider", "spinbox"],
    view_config: NumericViewConfig,
) -> QWidget:
    """Группа Label + Value (slider/spinbox)."""
    return create_labeled_numeric_view(
        view_type=view_type,
        value_config=view_config,
        label_position=view_config.label_position,
    )


class NumericControl:
    """Фасад для создания числового контрола (Slider/SpinBox)."""

    @staticmethod
    def create(
        registers_manager: Any,
        binding: BindingConfig,
        view_config: NumericViewConfig | None = None,
        current_access_level: int = 0,
        legacy_context: LegacySyncContext | None = None,
    ) -> NumericControlResult:
        """
        Создать числовой контрол.

        Returns:
            NumericControlResult(widget, presenter).
            layout.addWidget(result.widget)
        """
        view_config = view_config or NumericViewConfig()
        adapter = RegisterAdapter(registers_manager)
        presenter = NumericPresenter(
            binding,
            adapter,
            view_config,
            current_access_level,
            legacy_context=legacy_context,
            registers_manager=registers_manager,
        )

        view = _create_numeric_view(view_config.view_type, view_config)
        presenter.attach_view(view)

        return NumericControlResult(widget=view, presenter=presenter)
