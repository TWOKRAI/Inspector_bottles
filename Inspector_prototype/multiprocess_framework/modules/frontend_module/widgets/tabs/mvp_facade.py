# -*- coding: utf-8 -*-
"""
MvpTabBase — MVP-вкладки на базе BaseWidget.

Тот же жизненный цикл, что у BaseWidget (в т.ч. опциональный Model через _create_model).
Отличие по умолчанию: _connect_signals — no-op (презентер подписывается при создании
или в _on_presenter_ready). При необходимости переопределите _connect_signals, как у
полноценного BaseWidget.

Подкласс реализует _coerce_callbacks, _coerce_ui, _init_ui, _create_presenter(model),
при необходимости _create_model, _connect_signals, _on_presenter_ready и View Protocol.
"""
from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.frontend_module.widgets.base_widget.base_widget import BaseWidget


class MvpTabBase(BaseWidget[Any]):
    """
    Базовый класс для MVP-вкладок: наследует BaseWidget, единая точка расширения.

    Реализуйте в подклассе:
    - _coerce_callbacks, _coerce_ui
    - _init_ui, _create_presenter(model)
    - при необходимости _create_model, _connect_signals, _on_presenter_ready
    - методы View Protocol
    """

    def _connect_signals(self) -> None:
        """
        По умолчанию отдельный шаг не требуется: презентер монтируется в _create_presenter.
        Переопределите для сценария как у HikvisionWidget (кнопки → presenter/model).
        """
        pass
