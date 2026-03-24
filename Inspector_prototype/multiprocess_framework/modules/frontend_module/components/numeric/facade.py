# -*- coding: utf-8 -*-
"""
NumericControl — фасад для создания числового контрола.

Выбор View по view_config.view_type (slider | spinbox).
Возвращает (widget, presenter) для явного управления жизненным циклом.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from frontend_module.components.base import RegisterAdapter
from frontend_module.components.base.config import BindingConfig
from frontend_module.components.base.control_hooks import ControlHooks
from frontend_module.components.base.traits import LegacySyncContext
from frontend_module.components.numeric.config import NumericViewConfig
from frontend_module.components.numeric.presenter import NumericPresenter
from frontend_module.components.group.labeled_numeric_factory import (
    create_labeled_numeric_view,
)
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
        hooks: ControlHooks | None = None,
    ) -> NumericControlResult:
        """
        Создать числовой контрол.

        Args:
            hooks: Передаётся в ``NumericPresenter``; presenter эмитит колбэки при успешной записи,
                отказе ``SyncTrait.write`` и при попытке изменить значение без прав (``on_access_denied``).

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
            hooks=hooks,
        )

        view = _create_numeric_view(view_config.view_type, view_config)
        presenter.attach_view(view)

        return NumericControlResult(widget=view, presenter=presenter)
