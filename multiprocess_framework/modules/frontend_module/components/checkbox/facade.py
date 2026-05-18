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
from typing import TYPE_CHECKING, Optional

from multiprocess_framework.modules.frontend_module.components.base import RegisterAdapter
from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
from multiprocess_framework.modules.frontend_module.components.base.control_hooks import ControlHooks
from multiprocess_framework.modules.frontend_module.components.base.interfaces import RegistersManagerLike
from multiprocess_framework.modules.frontend_module.components.checkbox.config import CheckboxViewConfig
from multiprocess_framework.modules.frontend_module.components.checkbox.presenter import CheckboxPresenter
from multiprocess_framework.modules.frontend_module.components.checkbox.view import CheckboxView
from multiprocess_framework.modules.frontend_module.core.qt_imports import QWidget

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext


@dataclass
class CheckboxControlResult:
    """
    Итог фабрики: готовый виджет для layout и presenter для смены прав доступа.

    Attributes:
        widget: Корневой виджет (`CheckboxView`) — добавлять в layout родителя.
        presenter: Вызов `set_access_level`, сценарии без эмуляции Qt-событий.
    """

    widget: QWidget
    presenter: CheckboxPresenter


class CheckboxControl:
    """Статическая фабрика: собирает `RegisterAdapter`, `CheckboxPresenter` и `CheckboxView`."""

    @staticmethod
    def create(
        registers_manager: Optional[RegistersManagerLike],
        binding: BindingConfig,
        view_config: CheckboxViewConfig | None = None,
        current_access_level: int = 0,
        hooks: ControlHooks | None = None,
        *,
        form_ctx: "FormContext | None" = None,
    ) -> CheckboxControlResult:
        """
        Создать чекбокс, привязанный к полю регистра.

        Args:
            registers_manager: Менеджер регистров или None (операции чтения/записи станут no-op/ошибкой).
            binding: Имя регистра и поля.
            view_config: Позиция метки и опциональные переопределения подписи; по умолчанию слева.
            current_access_level: Начальный уровень доступа пользователя.
            hooks: Передаётся в ``CheckboxPresenter``; при записи presenter вызывает
                ``on_write_committed`` / ``on_write_rejected`` (ответ регистра) и
                ``on_access_denied``, если пользователь меняет значение при ``not can_modify()``.
            form_ctx: FormContext — управляет маршрутом записи значения.

                **Production-путь (form_ctx передан):** write идёт через ``ActionBus``
                с coalescing, undo/redo и IPC bridge (``TopologyBridge``). Обязателен
                в plugin-формах (PluginsTab, InspectorPanel, ServicesTab) — без него
                изменение не попадёт в undo-стек и не разойдётся по IPC-таргетам.

                **Legacy-путь (form_ctx is None):** прямая запись через
                ``RegisterAdapter.write`` → ``rm.set_field_value``. Допустим только в
                FW unit-тестах (``_examples/``) и GUI-локальных формах без plugin binding
                (например, SettingsSystem). При тиражировании паттерна на новые controls
                (SpinBox, Slider, Numeric, ...) — следуй этому контракту: передавай
                ``form_ctx`` в production и оставляй ``None`` только для legacy callers.

        Returns:
            Виджет и presenter с уже выполненным `attach_view`.
        """
        view_config = view_config or CheckboxViewConfig()
        adapter = RegisterAdapter(registers_manager)
        presenter = CheckboxPresenter(
            binding,
            adapter,
            view_config,
            current_access_level,
            hooks=hooks,
            form_ctx=form_ctx,
        )

        view = CheckboxView(position=view_config.position)
        presenter.attach_view(view)

        return CheckboxControlResult(widget=view, presenter=presenter)
