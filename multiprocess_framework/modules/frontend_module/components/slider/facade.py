# -*- coding: utf-8 -*-
"""
SliderControl — фасад для создания слайдера с привязкой к регистру.

Пример::

    result = SliderControl.create(
        rm,
        BindingConfig(register_name="processor", field_name="min_area"),
        SliderConfig(label_position="left"),
    )
    layout.addWidget(result.widget)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext

from multiprocess_framework.modules.frontend_module.components.base import RegisterAdapter
from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
from multiprocess_framework.modules.frontend_module.components.base.control_hooks import ControlHooks
from multiprocess_framework.modules.frontend_module.components.base.traits import LegacySyncContext
from multiprocess_framework.modules.frontend_module.components.numeric.config import NumericViewConfig
from multiprocess_framework.modules.frontend_module.components.group.labeled_numeric_factory import (
    create_labeled_numeric_view,
)
from multiprocess_framework.modules.frontend_module.components.slider.config import SliderConfig
from multiprocess_framework.modules.frontend_module.components.slider.presenter import SliderPresenter
from multiprocess_framework.modules.frontend_module.core.qt_imports import QWidget


@dataclass
class SliderControlResult:
    """
    Итог фабрики: готовый виджет для layout и presenter для смены прав доступа.

    Attributes:
        widget: Корневой виджет (Label + SliderValueView) — добавлять в layout родителя.
        presenter: ``SliderPresenter`` (те же трейты, что у числового контрола).
    """

    widget: QWidget
    presenter: SliderPresenter


def _slider_config_to_numeric_view_config(config: SliderConfig) -> NumericViewConfig:
    """Преобразование SliderConfig в NumericViewConfig с view_type=slider."""
    return NumericViewConfig(
        view_type="slider",
        label=config.label,
        tooltip=config.tooltip,
        enabled=config.enabled,
        access_level=config.access_level,
        show_ticks=config.show_ticks,
        tick_interval=config.tick_interval,
        min_val=config.min_val,
        max_val=config.max_val,
        label_position=config.label_position,
    )


class SliderControl:
    """Статическая фабрика: ``SliderPresenter`` + labeled group (без прокси через NumericControl)."""

    @staticmethod
    def create(
        registers_manager: Optional[Any],
        binding: BindingConfig,
        view_config: SliderConfig | None = None,
        current_access_level: int = 0,
        legacy_context: Optional[LegacySyncContext] = None,
        hooks: ControlHooks | None = None,
        *,
        form_ctx: "FormContext | None" = None,
    ) -> SliderControlResult:
        """
        Создать слайдер, привязанный к полю регистра.

        Args:
            registers_manager: Менеджер регистров или None (операции чтения/записи станут no-op/ошибкой).
            binding: Имя регистра и поля.
            view_config: UI-опции слайдера; по умолчанию SliderConfig().
            current_access_level: Начальный уровень доступа пользователя.
            legacy_context: Контекст для LegacySyncTrait (ui_elements, controls и т.д.).
            hooks: См. ``NumericPresenter``: успех/ошибка записи в регистр и ``on_access_denied``
                при изменении без ``can_modify()``.
            form_ctx: FormContext — управляет маршрутом записи значения.

                **Production-путь (form_ctx передан):** write идёт через ``ActionBus``
                с coalescing, undo/redo и IPC bridge (``TopologyBridge``). Обязателен
                в plugin-формах (PluginsTab, InspectorPanel, ServicesTab) — без него
                изменение не попадёт в undo-стек и не разойдётся по IPC-таргетам.

                **Legacy-путь (form_ctx is None):** прямая запись через
                ``SyncTrait.write`` → ``RegisterAdapter`` → ``rm.set_field_value``.
                Допустим только в FW unit-тестах и GUI-локальных формах без plugin
                binding (например, SettingsSystem).

                При тиражировании паттерна на другие controls (Numeric, ...)
                следуй этому контракту: передавай ``form_ctx`` в production и оставляй
                ``None`` только для legacy callers.

        Returns:
            SliderControlResult(widget, presenter).
        """
        view_config = view_config or SliderConfig()
        numeric_config = _slider_config_to_numeric_view_config(view_config)
        adapter = RegisterAdapter(registers_manager)
        presenter = SliderPresenter(
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
            view_type="slider",
            value_config=numeric_config,
            label_position=numeric_config.label_position,
        )
        presenter.attach_view(view)
        return SliderControlResult(widget=view, presenter=presenter)
