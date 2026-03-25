# -*- coding: utf-8 -*-
"""
Составные контролы — CompoundNumericControl, CompoundControl, ControlFactory.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Union

from frontend_module.components.base.config import BindingConfig
from frontend_module.components.base.control_hooks import ControlHooks
from frontend_module.components.base.traits import LegacySyncContext
from frontend_module.components.checkbox.config import CheckboxViewConfig
from frontend_module.components.checkbox.facade import (
    CheckboxControl,
    CheckboxControlResult,
)
from frontend_module.components.compound.config import (
    CompoundControlConfig,
    CompoundNumericConfig,
)
from frontend_module.components.numeric.config import NumericViewConfig
from frontend_module.components.numeric.facade import (
    NumericControl,
    NumericControlResult,
)
from frontend_module.core.qt_imports import QHBoxLayout, QVBoxLayout, QWidget


@dataclass
class CompoundNumericControlResult:
    """Результат create(): виджет-контейнер и список (widget, presenter) для каждого индекса."""

    widget: QWidget
    results: List[NumericControlResult]


def _ensure_labels(labels: List[str], count: int = 3) -> List[str]:
    default = ["0", "1", "2"]
    out = list(labels) if labels else []
    while len(out) < count:
        out.append(default[len(out)] if len(out) < len(default) else str(len(out)))
    return out[:count]


class CompoundNumericControl:
    """Фасад для создания составного контрола из 3 NumericControls."""

    @staticmethod
    def create(
        registers_manager: Any,
        config: CompoundNumericConfig,
        current_access_level: int = 0,
        legacy_context: Optional[LegacySyncContext] = None,
        hooks: Optional[ControlHooks] = None,
    ) -> CompoundNumericControlResult:
        """
        Создать составной контрол: 3 слайдера для индексов 0,1,2.

        Args:
            hooks: Общий набор колбэков для всех трёх дочерних ``NumericControl`` (см. ``NumericControl.create``).

        Returns:
            CompoundNumericControlResult(widget, results).
        """
        labels = _ensure_labels(config.labels)
        view_config = config.view_config or NumericViewConfig()
        container = QWidget()
        layout = QHBoxLayout(container)

        results: List[NumericControlResult] = []
        for i in range(3):
            binding = BindingConfig(
                register_name=config.binding.register_name,
                field_name=config.binding.field_name,
                access_level=config.binding.access_level,
                index=i,
            )
            vc = NumericViewConfig(
                view_type=view_config.view_type,
                label=labels[i],
                show_ticks=view_config.show_ticks,
                tick_interval=view_config.tick_interval,
                touch_keyboard=view_config.touch_keyboard,
                touch_keyboard_factory=view_config.touch_keyboard_factory,
                min_val=view_config.min_val,
                max_val=view_config.max_val,
            )
            r = NumericControl.create(
                registers_manager,
                binding,
                view_config=vc,
                current_access_level=current_access_level,
                legacy_context=legacy_context,
                hooks=hooks,
            )
            results.append(r)
            layout.addWidget(r.widget)
            if i < 2:
                layout.addSpacing(10)

        return CompoundNumericControlResult(widget=container, results=results)


class CompoundControlResult:
    """Результат CompoundControl.create()."""

    def __init__(self, widget: QWidget, results: list) -> None:
        self.widget = widget
        self.results = results


class CompoundControl:
    """Универсальный составной контрол из любых дочерних контролов."""

    @staticmethod
    def create(
        registers_manager: Any,
        config: CompoundControlConfig,
        current_access_level: int = 0,
        legacy_context: Optional[LegacySyncContext] = None,
        hooks: Optional[ControlHooks] = None,
    ) -> CompoundControlResult:
        """
        Создать составной контрол.

        Array mode: binding + array_children.
        Mixed mode: items (list of (binding, view_config)).

        Args:
            hooks: Пробрасывается в каждый дочерний ``NumericControl.create`` / ``ControlFactory.create``.
        """
        container = QWidget()
        is_horizontal = config.orientation == "horizontal"
        layout = QHBoxLayout(container) if is_horizontal else QVBoxLayout(container)
        layout.setSpacing(config.spacing)

        results = []

        if config.array_children is not None and config.binding is not None:
            for i, child_config in enumerate(config.array_children):
                binding = BindingConfig(
                    register_name=config.binding.register_name,
                    field_name=config.binding.field_name,
                    access_level=config.binding.access_level,
                    index=i,
                )
                r = NumericControl.create(
                    registers_manager,
                    binding,
                    view_config=child_config,
                    current_access_level=current_access_level,
                    legacy_context=legacy_context,
                    hooks=hooks,
                )
                results.append(r)
                layout.addWidget(r.widget)
                if i < len(config.array_children) - 1:
                    layout.addSpacing(config.spacing)
        elif config.items is not None:
            for i, (binding, child_config) in enumerate(config.items):
                r = ControlFactory.create(
                    registers_manager,
                    child_config,
                    binding=binding,
                    current_access_level=current_access_level,
                    legacy_context=legacy_context,
                    hooks=hooks,
                )
                results.append(r)
                layout.addWidget(r.widget)
                if i < len(config.items) - 1:
                    layout.addSpacing(config.spacing)
        else:
            raise ValueError(
                "CompoundControlConfig: задайте либо (binding + array_children), "
                "либо items"
            )

        return CompoundControlResult(widget=container, results=results)


ControlResult = Union[
    NumericControlResult,
    CheckboxControlResult,
    CompoundNumericControlResult,
    CompoundControlResult,
]


class ControlFactory:
    """Единая фабрика контролов."""

    @staticmethod
    def create(
        registers_manager: Any,
        config: Union[NumericViewConfig, CheckboxViewConfig, CompoundControlConfig],
        binding: Optional[BindingConfig] = None,
        current_access_level: int = 0,
        legacy_context: Optional[LegacySyncContext] = None,
        hooks: Optional[ControlHooks] = None,
    ) -> ControlResult:
        """
        Создать контрол по конфигу.

        config — NumericViewConfig, CheckboxViewConfig или CompoundControlConfig.
        binding — обязателен для Numeric/Boolean; для CompoundControlConfig — внутри config.
        hooks — передаётся в presenter создаваемого контрола (успех/ошибка записи, отказ по правам).

        Returns виджет через .widget (и при необходимости .presenter).
        """
        if isinstance(config, NumericViewConfig):
            if binding is None:
                raise ValueError(
                    "ControlFactory.create: binding обязателен для NumericViewConfig"
                )
            return NumericControl.create(
                registers_manager,
                binding,
                view_config=config,
                current_access_level=current_access_level,
                legacy_context=legacy_context,
                hooks=hooks,
            )
        if isinstance(config, CheckboxViewConfig):
            if binding is None:
                raise ValueError(
                    "ControlFactory.create: binding обязателен для CheckboxViewConfig"
                )
            return CheckboxControl.create(
                registers_manager,
                binding,
                view_config=config,
                current_access_level=current_access_level,
                hooks=hooks,
            )
        if isinstance(config, CompoundControlConfig):
            return CompoundControl.create(
                registers_manager,
                config,
                current_access_level=current_access_level,
                legacy_context=legacy_context,
                hooks=hooks,
            )
        raise TypeError(f"Unknown config type: {type(config).__name__}")
