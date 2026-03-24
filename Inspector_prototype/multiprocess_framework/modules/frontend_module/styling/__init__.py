# -*- coding: utf-8 -*-
"""
Стили QSS: слои токенов (глобальный → style_id → виджет → компонент), сессия, реестр.

Порядок merge токенов (слабее → сильнее): дефолты ``style_id`` → глобальная палитра
→ ``widget_layer`` → ``component_layer``.

Пример::

    session.set_global_tokens({"accent": "#2196F3", "radius": "4px"})
    session.registry.register("slider", template, {"track_height": "6px"})
    session.register(
        widget,
        style_id="slider",
        widget_layer={"panel_bg": "#2d2d2d"},
        component_layer={"accent": "#ff0000"},
    )
"""
from __future__ import annotations

from frontend_module.styling.app_style_session import (
    apply_ui_theme_dict,
    create_app_style_session,
)
from frontend_module.styling.apply_qss import apply_stylesheet
from frontend_module.styling.context import get_style_session_from_parent
from frontend_module.styling.default_bundles import (
    register_default_bundles,
    style_ids_legacy_map,
)
from frontend_module.styling.qss_utils import (
    load_qss_file,
    merge_token_layers,
    minimal_fallback_qss,
    render_qss,
    resolve_template,
)
from frontend_module.styling.registry import NamedStyleBundle, NamedStyleRegistry
from frontend_module.styling.style_session import StyleSession

__all__ = [
    "NamedStyleBundle",
    "NamedStyleRegistry",
    "StyleSession",
    "apply_stylesheet",
    "apply_ui_theme_dict",
    "create_app_style_session",
    "get_style_session_from_parent",
    "load_qss_file",
    "merge_token_layers",
    "minimal_fallback_qss",
    "register_default_bundles",
    "render_qss",
    "resolve_template",
    "style_ids_legacy_map",
]
