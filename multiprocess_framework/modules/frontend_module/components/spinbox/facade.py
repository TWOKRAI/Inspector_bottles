# -*- coding: utf-8 -*-
"""
SpinBoxControl — фасад для спинбокса с привязкой к регистру.

``SpinBoxPresenter`` + labeled group (без прокси через ``NumericControl``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from multiprocess_framework.modules.frontend_module.components.base import RegisterAdapter
from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
from multiprocess_framework.modules.frontend_module.components.base.control_hooks import ControlHooks
from multiprocess_framework.modules.frontend_module.components.base.traits import LegacySyncContext
from multiprocess_framework.modules.frontend_module.components.group.labeled_numeric_factory import (
    create_labeled_numeric_view,
)
from multiprocess_framework.modules.frontend_module.components.numeric.config import NumericViewConfig
from multiprocess_framework.modules.frontend_module.components.spinbox.config import SpinBoxConfig
from multiprocess_framework.modules.frontend_module.components.spinbox.presenter import SpinBoxPresenter
from multiprocess_framework.modules.frontend_module.core.qt_imports import QWidget

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext


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
        touch_keyboard=config.touch_keyboard,
        touch_keyboard_factory=config.touch_keyboard_factory,
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
        *,
        form_ctx: "FormContext | None" = None,
    ) -> SpinBoxControlResult:
        """
        Создать спинбокс, привязанный к полю регистра.

        Args:
            registers_manager: Менеджер регистров или None.
            binding: Имя регистра и поля.
            view_config: Конфигурация визуального вида; по умолчанию SpinBoxConfig().
            current_access_level: Начальный уровень доступа пользователя.
            legacy_context: Контекст легаси-синхронизации (старый API).
            hooks: Колбэки записи и ``on_access_denied`` при недостаточных правах.
            form_ctx: FormContext — управляет маршрутом записи значения.

                **Production-путь (form_ctx передан):** write идёт через ``ActionBus``
                с coalescing, undo/redo и IPC bridge (``TopologyBridge``). Обязателен
                в plugin-формах (PluginsTab, InspectorPanel, ServicesTab) — без него
                изменение не попадёт в undo-стек и не разойдётся по IPC-таргетам.

                **Legacy-путь (form_ctx is None):** прямая запись через
                ``SyncTrait.write`` → ``RegisterAdapter`` → ``rm.set_field_value``.
                Допустим только в FW unit-тестах и GUI-локальных формах без plugin
                binding (например, SettingsSystem).

                При тиражировании паттерна на другие controls (Slider, Numeric, ...)
                следуй этому контракту: передавай ``form_ctx`` в production и оставляй
                ``None`` только для legacy callers.

        Returns:
            Виджет и presenter с уже выполненным `attach_view`.
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
            form_ctx=form_ctx,
        )
        view = create_labeled_numeric_view(
            view_type="spinbox",
            value_config=numeric_config,
            label_position=numeric_config.label_position,
        )
        presenter.attach_view(view)
        return SpinBoxControlResult(widget=view, presenter=presenter)
