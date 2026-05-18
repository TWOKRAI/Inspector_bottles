# -*- coding: utf-8 -*-
"""
ComboControl — фасад для создания выпадающего списка с привязкой к регистру.

Пример::

    result = ComboControl.create(
        rm,
        BindingConfig(register_name="config", field_name="mode"),
        ComboViewConfig(),
        items=["auto", "manual", "off"],
    )
    layout.addWidget(result.widget)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional

from multiprocess_framework.modules.frontend_module.components.base import RegisterAdapter
from multiprocess_framework.modules.frontend_module.components.base.config import BindingConfig
from multiprocess_framework.modules.frontend_module.components.base.control_hooks import ControlHooks
from multiprocess_framework.modules.frontend_module.components.base.interfaces import RegistersManagerLike
from multiprocess_framework.modules.frontend_module.components.combo.config import ComboViewConfig
from multiprocess_framework.modules.frontend_module.components.combo.presenter import ComboPresenter
from multiprocess_framework.modules.frontend_module.components.combo.view import ComboView
from multiprocess_framework.modules.frontend_module.core.qt_imports import QWidget

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.forms.form_context import FormContext


@dataclass
class ComboControlResult:
    """Итог фабрики: готовый виджет и presenter."""

    widget: QWidget
    presenter: ComboPresenter


class ComboControl:
    """Статическая фабрика: собирает RegisterAdapter, ComboPresenter и ComboView."""

    @staticmethod
    def create(
        registers_manager: Optional[RegistersManagerLike],
        binding: BindingConfig,
        view_config: ComboViewConfig | None = None,
        current_access_level: int = 0,
        hooks: ControlHooks | None = None,
        items: List[str] | None = None,
        *,
        form_ctx: "FormContext | None" = None,
    ) -> ComboControlResult:
        """
        Создать выпадающий список, привязанный к полю регистра.

        Args:
            registers_manager: Менеджер регистров или None (операции чтения/записи станут no-op/ошибкой).
            binding: Имя регистра и поля.
            view_config: UI-опции (label, tooltip, placeholder, items).
            current_access_level: Начальный уровень доступа пользователя.
            hooks: Колбэки для логирования (on_write_committed / on_write_rejected / on_access_denied).
            items: Список строковых вариантов. Если None — используются items из view_config.items.
            form_ctx: Production-путь (передан): write через ActionBus (undo/redo, IPC bridge).
                Legacy-путь (None): прямая запись через RegisterAdapter.

        Returns:
            ComboControlResult с виджетом и presenter (attach_view уже выполнен).
        """
        view_config = view_config or ComboViewConfig()
        # Эффективный список items: явный параметр приоритетнее view_config.items
        effective_items = items if items is not None else (view_config.items or [])
        adapter = RegisterAdapter(registers_manager)
        presenter = ComboPresenter(
            binding,
            adapter,
            view_config,
            current_access_level,
            hooks=hooks,
            items=effective_items,
            form_ctx=form_ctx,
        )
        view = ComboView()
        presenter.attach_view(view)
        return ComboControlResult(widget=view, presenter=presenter)
