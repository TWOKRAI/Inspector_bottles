"""Утилиты привязки виджетов к permissions через AuthState (PR3)."""
from __future__ import annotations

from .permission_gate import (
    bind_edit_permission,
    gate_edit_widgets,
    gate_register_view,
    install_permission_aware_enable,
    propagate_access_context_to_tree,
)

__all__ = [
    "bind_edit_permission",
    "gate_edit_widgets",
    "gate_register_view",
    "install_permission_aware_enable",
    "propagate_access_context_to_tree",
]
