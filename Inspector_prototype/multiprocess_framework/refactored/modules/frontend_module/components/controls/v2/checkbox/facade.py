# -*- coding: utf-8 -*-
"""
CheckboxControl — фасад для создания чекбокса с привязкой к регистру.

Пример::

    result = CheckboxControl.create(
        rm,
        BindingConfig(register_name="renderer", field_name="show_mask"),
        CheckboxViewConfig(position="left"),
    )
    layout.addWidget(result.widget)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from frontend_module.components.controls.v2.base import RegisterAdapter
from frontend_module.components.controls.v2.base.config import BindingConfig
from frontend_module.components.controls.v2.checkbox.config import CheckboxViewConfig
from frontend_module.components.controls.v2.checkbox.presenter import CheckboxPresenter
from frontend_module.components.controls.v2.checkbox.view import CheckboxView
from frontend_module.core.qt_imports import QWidget


@dataclass
class CheckboxControlResult:
    """Результат CheckboxControl.create(): виджет и presenter."""

    widget: QWidget
    presenter: CheckboxPresenter


class CheckboxControl:
    """Фасад для создания чекбокса."""

    @staticmethod
    def create(
        registers_manager: Any,
        binding: BindingConfig,
        view_config: CheckboxViewConfig | None = None,
        current_access_level: int = 0,
    ) -> CheckboxControlResult:
        """Создать чекбокс. Returns CheckboxControlResult(widget, presenter)."""
        view_config = view_config or CheckboxViewConfig()
        adapter = RegisterAdapter(registers_manager)
        presenter = CheckboxPresenter(
            binding, adapter, view_config, current_access_level
        )

        view = CheckboxView(position=view_config.position)
        presenter.attach_view(view)

        return CheckboxControlResult(widget=view, presenter=presenter)
