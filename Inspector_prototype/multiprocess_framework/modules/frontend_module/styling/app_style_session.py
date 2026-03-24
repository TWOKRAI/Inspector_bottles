# -*- coding: utf-8 -*-
"""
Сборка `StyleSession` с встроенными QSS фреймворка и опциональным `ui_theme` (dict).

Прототип передаёт ``config["ui_theme"]`` (см. ``UiThemeConfig``).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from frontend_module.styling.default_bundles import register_default_bundles
from frontend_module.styling.registry import NamedStyleRegistry
from frontend_module.styling.style_session import StyleSession


def apply_ui_theme_dict(session: StyleSession, theme: Optional[Dict[str, Any]]) -> None:
    """Применить словарь темы (``global_tokens``, ``bundle_overrides``) и обновить виджеты."""
    if not theme:
        return
    g = theme.get("global_tokens") or {}
    if g:
        session.set_global_tokens(dict(g))
    for style_id, partial in (theme.get("bundle_overrides") or {}).items():
        if isinstance(partial, dict) and partial:
            session.registry.merge_default_tokens(style_id, dict(partial))
    session.refresh()


def create_app_style_session(ui_theme: Optional[Dict[str, Any]] = None) -> StyleSession:
    """
    Реестр встроенных стилей + опционально merge из конфига темы.

    Args:
        ui_theme: обычно ``config["ui_theme"]`` из сборки frontend config.
    """
    reg = NamedStyleRegistry()
    register_default_bundles(reg)
    session = StyleSession(registry=reg)
    session.set_global_tokens({})
    apply_ui_theme_dict(session, ui_theme)
    return session
