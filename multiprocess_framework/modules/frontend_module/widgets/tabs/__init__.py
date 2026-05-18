# -*- coding: utf-8 -*-
"""
Вкладки: виджет с табами, BaseTab, MVP (MvpTabBase, TabPresenterBase),
привязка к регистрам, колбэки и заглушки.

Модули: tab_widget, mvp_pattern, mvp_facade, binding_context,
callbacks_base, placeholder_utils.
"""

from .binding_context import RegisterBindingContext
from .current_page_stack import CurrentPageStack
from .callbacks_base import (
    callback_no_args,
    tab_callbacks_from_dict,
    tab_callbacks_to_dict,
)
from .mvp_facade import MvpTabBase
from .panel_tab_base import PanelTabBase
from .mvp_pattern import TabPresenterBase, TabViewProtocol
from .section_protocol import SectionProtocol, SectionWithEvents
from .section_spec import SectionSpec
from .placeholder_utils import create_registers_placeholder
from .tab_widget import BaseTab, TabWidget

__all__ = [
    "BaseTab",
    "CurrentPageStack",
    "MvpTabBase",
    "PanelTabBase",
    "RegisterBindingContext",
    "SectionProtocol",
    "SectionSpec",
    "SectionWithEvents",
    "TabPresenterBase",
    "TabViewProtocol",
    "TabWidget",
    "callback_no_args",
    "create_registers_placeholder",
    "tab_callbacks_from_dict",
    "tab_callbacks_to_dict",
]
